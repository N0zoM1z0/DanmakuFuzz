from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from ..corpus.pbg3 import Pbg3Archive
from ..headless.baseline import DEFAULT_GAME_DIR
from ..repo import ARTIFACTS_DIR, ensure_directory
from .signatures import normalize_wine_primary_signature, retail_signature_key


RETAIL_EXECUTABLE_CANDIDATES = (
    "東方紅魔郷.exe",
    "th06.exe",
)
TITLE_WINDOW_NAME = "東方紅魔郷"
PRIMARY_STAGE_ARCHIVE = "紅魔郷ST.DAT"
FALLBACK_STAGE_ARCHIVES = ("峠杺嫿ST.DAT",)
FULL_UNLOCK_SCORE_SHA256 = (
    "54cd436d5d8a7a904190c792a977bf270ab1cb759fd72101e51e94d26b749c71"
)
CANONICAL_CONFIG_NAME = "東方紅魔郷.cfg"
CONFIG_SIZE = 0x38
CONTROLLER_MAPPING = (0, 1, 2, 4, -1, -1, -1, -1, 3)
VERSION_OFFSET = 0x14
VERSION_102H = 0x102
COLOR_MODE_16BIT_OFFSET = 0x1A
WINDOWED_OFFSET = 0x1E
DISPLAY_BASE = 190
TAP_HOLD_SECONDS = 0.30
TAP_SETTLE_SECONDS = 0.80
MENU_TAP_HOLD_SECONDS = 0.02
MENU_TAP_SETTLE_SECONDS = 0.10
DEFAULT_STARTUP_SECONDS = 5.0
DEFAULT_STAGE_ENTRY_WAIT_SECONDS = 3.0
DEFAULT_STAGE_ENTRY_MIN_FRAME = 60
DEFAULT_PROGRESS_PROBE_SECONDS = 2.0
DEFAULT_PROGRESS_PROBE_FRAMES = 120
DEFAULT_SCREEN_SIZE = "1024x768x24"
DEFAULT_STARTUP_NORMALIZATION_DELAY_SECONDS = 1.0
STARTUP_NORMALIZATION_MARKER = "DANMAKUFUZZ_TH06_STARTUP_NORMALIZED=1"
BASELINE_EQUIVALENCE_RATIO = 0.001
BASELINE_VISUAL_DRIFT_RATIO = 0.05
LOW_INFORMATION_UNIQUE_COLOR_LIMIT = 256
LOW_INFORMATION_TOP_TWO_COLOR_RATIO = 0.995
MENU_READ_TIMEOUT_SECONDS = 15.0
MENU_STATE_PRE_INPUT = 1
MENU_STATE_MAIN_MENU = 2
MENU_STATE_DIFFICULTY_SELECT = 7
MENU_STATE_CHARACTER_SELECT = 9
MENU_STATE_SHOT_SELECT = 11
MENU_STATE_PRACTICE_STAGE_SELECT = 17
MENU_STATE_NAMES = {
    MENU_STATE_PRE_INPUT: "pre-input",
    MENU_STATE_MAIN_MENU: "main-menu",
    MENU_STATE_DIFFICULTY_SELECT: "difficulty-select",
    MENU_STATE_CHARACTER_SELECT: "character-select",
    MENU_STATE_SHOT_SELECT: "shot-select",
    MENU_STATE_PRACTICE_STAGE_SELECT: "practice-stage-select",
}
ADDR_MAIN_MENU = 0x006D46C0
MAIN_MENU_CURSOR_OFFSET = 0x81A0
MAIN_MENU_STATE_OFFSET = 0x81F0
MAIN_MENU_TIMER_OFFSET = 0x81F4
ADDR_MAIN_MENU_CURSOR = ADDR_MAIN_MENU + MAIN_MENU_CURSOR_OFFSET
ADDR_MAIN_MENU_STATE = ADDR_MAIN_MENU + MAIN_MENU_STATE_OFFSET
ADDR_MAIN_MENU_TIMER = ADDR_MAIN_MENU + MAIN_MENU_TIMER_OFFSET
ADDR_SUPERVISOR = 0x006C6D18
SUPERVISOR_STATES_OFFSET = 0x188
ADDR_GAME_MANAGER = 0x0069BCA0
GAME_TIME_STOPPED_OFFSET = 0x2C
GAME_DIFFICULTY_OFFSET = 0x10
GAME_FLAGS_OFFSET = 0x181F
GAME_FRAMES_OFFSET = 0x1A30
GAME_STAGE_OFFSET = 0x1A34
WINE_CRASH_LOG_TOKENS = (
    "unhandled page fault",
    "unhandled exception",
    "starting debugger",
)
WINE_ERROR_LOG_TOKEN = "err:"


class MenuNavigationError(RuntimeError):
    """A pre-stage menu navigation failure that should not become a finding."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_case_result(result_path: Path) -> dict[str, object]:
    value = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"result json is not an object: {result_path}")
    return value


def _payload_from_case_result(
    case_result: dict[str, object],
    result_path: Path,
) -> tuple[str, bytes, Path, Path | None]:
    seed_name = case_result.get("seed_name")
    override_dir = case_result.get("override_dir")
    if isinstance(seed_name, str) and isinstance(override_dir, str):
        payload_path = Path(override_dir) / "data" / seed_name
        if not payload_path.is_file():
            raise FileNotFoundError(f"missing case payload: {payload_path}")
        return seed_name, payload_path.read_bytes(), payload_path, result_path
    entry_name = case_result.get("entry_name")
    if isinstance(entry_name, str) and isinstance(override_dir, str):
        payload_path = Path(override_dir) / "data" / entry_name
        if not payload_path.is_file():
            raise FileNotFoundError(f"missing case payload: {payload_path}")
        return entry_name, payload_path.read_bytes(), payload_path, result_path

    payload_path_value = case_result.get("final_payload")
    source_result_value = case_result.get("source_result")
    if not isinstance(payload_path_value, str):
        raise ValueError(
            "input json is missing semantic override_dir/seed_name, override_dir/entry_name, "
            "or minimized final_payload"
        )
    payload_path = Path(payload_path_value)
    if not payload_path.is_file():
        raise FileNotFoundError(f"missing minimized payload: {payload_path}")
    source_result_path = (
        Path(source_result_value).resolve()
        if isinstance(source_result_value, str)
        else None
    )
    return payload_path.name, payload_path.read_bytes(), payload_path, source_result_path


def _default_artifact_dir(seed_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "retail-confirmation" / f"{seed_name}-{stamp}"


def _stage_archives(game_dir: Path) -> list[Path]:
    candidates = [game_dir / PRIMARY_STAGE_ARCHIVE, *[game_dir / name for name in FALLBACK_STAGE_ARCHIVES]]
    archives = [path for path in candidates if path.is_file()]
    if not archives:
        raise FileNotFoundError(f"no retail ST archives found under {game_dir}")
    return archives


def _retail_executable(game_dir: Path) -> Path:
    for name in RETAIL_EXECUTABLE_CANDIDATES:
        candidate = game_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"missing retail executable under {game_dir}: {RETAIL_EXECUTABLE_CANDIDATES}"
    )


def _copy_game_tree(source_game_dir: Path, destination_game_dir: Path) -> None:
    if destination_game_dir.exists():
        raise FileExistsError(f"destination game directory already exists: {destination_game_dir}")
    ensure_directory(destination_game_dir.parent)
    shutil.copytree(source_game_dir, destination_game_dir)


def _command_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _startup_normalization_script() -> Path:
    return Path(__file__).with_name("normalize_th06_startup.py")


def _startup_normalization_command(*, sudo: Path, gdb: Path, process_id: int) -> list[str]:
    return [
        str(sudo),
        "-n",
        str(gdb),
        "-q",
        "-nx",
        "-batch",
        "-p",
        str(process_id),
        "-x",
        str(_startup_normalization_script()),
    ]


def _normalize_retail_startup(
    *,
    artifact_dir: Path,
    sudo: Path,
    gdb: Path,
    process_id: int,
    mode: str,
    timeout_seconds: float = 60.0,
) -> dict[str, object]:
    log_path = artifact_dir / "gdb-startup-normalization.log"
    if mode == "off":
        return {
            "mode": mode,
            "attempted": False,
            "normalized": False,
            "required": False,
            "log": str(log_path.resolve()),
        }
    if mode not in ("auto", "gdb"):
        raise ValueError("startup normalization mode must be auto, gdb, or off")
    command = _startup_normalization_command(
        sudo=sudo,
        gdb=gdb,
        process_id=process_id,
    )
    required = mode == "gdb"
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = completed.stdout + completed.stderr
        timed_out = False
        returncode = completed.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        output = f"{type(exc).__name__}: {exc}\n".encode("utf-8", errors="replace")
        timed_out = isinstance(exc, subprocess.TimeoutExpired)
        returncode = None
    log_path.write_bytes(output)
    normalized = STARTUP_NORMALIZATION_MARKER.encode() in output
    report = {
        "mode": mode,
        "attempted": True,
        "normalized": normalized,
        "required": required,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": time.time() - started,
        "marker": STARTUP_NORMALIZATION_MARKER,
        "log": str(log_path.resolve()),
    }
    if required and not normalized:
        raise RuntimeError(
            "TH06 startup normalization failed; see "
            f"{log_path} for GDB output"
        )
    return report


def _source_default_config() -> bytes:
    payload = bytearray(CONFIG_SIZE)
    for index, value in enumerate(CONTROLLER_MAPPING):
        payload[index * 2:index * 2 + 2] = int(value).to_bytes(2, "little", signed=True)
    payload[VERSION_OFFSET:VERSION_OFFSET + 4] = VERSION_102H.to_bytes(4, "little")
    payload[0x18] = 2
    payload[0x19] = 3
    payload[COLOR_MODE_16BIT_OFFSET] = 0xFF
    payload[0x1B] = 1
    payload[0x1C] = 1
    payload[0x1D] = 1
    payload[WINDOWED_OFFSET] = 0
    payload[0x1F] = 0
    payload[0x20:0x22] = (600).to_bytes(2, "little", signed=True)
    payload[0x22:0x24] = (600).to_bytes(2, "little", signed=True)
    payload[0x34:0x38] = (1).to_bytes(4, "little")
    return bytes(payload)


def _configure_windowed(payload: bytes, *, color_mode_16bit: int | None = 0) -> bytes:
    if len(payload) != CONFIG_SIZE:
        raise ValueError(f"TH06 config must be {CONFIG_SIZE} bytes")
    version = int.from_bytes(payload[VERSION_OFFSET:VERSION_OFFSET + 4], "little")
    if version != VERSION_102H:
        raise ValueError(f"TH06 config version is 0x{version:x}, expected 0x102")
    if payload[WINDOWED_OFFSET] not in (0, 1):
        raise ValueError("TH06 windowed byte is invalid")
    if payload[COLOR_MODE_16BIT_OFFSET] not in (0, 1, 0xFF):
        raise ValueError("TH06 color-mode byte is invalid")
    if color_mode_16bit not in (None, 0, 1, 0xFF):
        raise ValueError("TH06 requested color-mode byte is invalid")
    configured = bytearray(payload)
    if color_mode_16bit is not None:
        configured[COLOR_MODE_16BIT_OFFSET] = color_mode_16bit
    configured[WINDOWED_OFFSET] = 1
    return bytes(configured)


def _configure_game_directory(
    game_dir: Path,
    *,
    color_mode_16bit: int | None = 0,
) -> dict[str, object]:
    canonical = game_dir / CANONICAL_CONFIG_NAME
    candidates = sorted(game_dir.glob("*.cfg"))
    initialized = False
    if canonical.is_file():
        path = canonical
        before = path.read_bytes()
    elif len(candidates) == 1:
        path = candidates[0]
        before = path.read_bytes()
    elif not candidates:
        path = canonical
        before = _source_default_config()
        initialized = True
    else:
        raise ValueError(
            "canonical TH06 cfg is absent and fallback is ambiguous; "
            f"found {len(candidates)} cfg files under {game_dir}"
        )
    after = _configure_windowed(before, color_mode_16bit=color_mode_16bit)
    changed = initialized or after != before
    if changed:
        path.write_bytes(after)
    return {
        "path": str(path.resolve()),
        "initialized": initialized,
        "changed": changed,
        "sha256_before": hashlib.sha256(before).hexdigest(),
        "sha256_after": hashlib.sha256(after).hexdigest(),
        "windowed_before": int(before[WINDOWED_OFFSET]),
        "windowed_after": int(after[WINDOWED_OFFSET]),
        "color_mode_16bit_before": int(before[COLOR_MODE_16BIT_OFFSET]),
        "color_mode_16bit_after": int(after[COLOR_MODE_16BIT_OFFSET]),
        "color_mode_16bit_requested": color_mode_16bit,
    }


def _restore_full_unlock_score(game_dir: Path) -> dict[str, object] | None:
    destination = game_dir / "score.dat"
    candidates = [
        path
        for path in game_dir.rglob("score.dat")
        if path.is_file() and path != destination and _sha256(path) == FULL_UNLOCK_SCORE_SHA256
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one full-unlock score template under {game_dir}")
    source = candidates[0]
    shutil.copy2(source, destination)
    if _sha256(destination) != FULL_UNLOCK_SCORE_SHA256:
        raise ValueError("copied full-unlock score differs")
    return {
        "source": str(source.resolve()),
        "destination": str(destination.resolve()),
        "sha256": FULL_UNLOCK_SCORE_SHA256,
        "restored": True,
    }


def _patch_stage_archive(archive_path: Path, *, entry_name: str, payload: bytes) -> dict[str, object]:
    original = Pbg3Archive.from_bytes(archive_path.read_bytes())
    rebuilt = original.replace({entry_name: payload})
    archive_path.write_bytes(rebuilt)
    rebuilt_archive = Pbg3Archive.from_bytes(rebuilt)
    extracted = rebuilt_archive.extract(entry_name)
    if extracted != payload:
        raise ValueError(f"rebuilt archive does not reproduce replacement payload: {archive_path}")
    return {
        "archive": str(archive_path.resolve()),
        "sha256": _sha256(archive_path),
        "entry_name": entry_name,
        "entry_size": len(payload),
    }


def _choose_display(base: int = DISPLAY_BASE) -> str:
    x11_root = Path("/tmp/.X11-unix")
    for value in range(base, base + 100):
        if not (x11_root / f"X{value}").exists():
            return f":{value}"
    raise RuntimeError(f"could not find a free X display starting at {base}")


def _wine_environment(prefix: Path, display: str | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "WINEPREFIX": str(prefix.resolve()),
            "WINEARCH": "win32",
            "WINEDEBUG": "-all",
            "WINEDLLOVERRIDES": "mscoree,mshtml=",
            "LANG": "ja_JP.UTF-8",
            "LC_ALL": "ja_JP.UTF-8",
            "MESA_GLTHREAD": "false",
        }
    )
    if display is not None:
        environment["DISPLAY"] = display
    return environment


def _prepare_wine_prefix(
    prefix: Path,
    *,
    xvfb_run: Path,
    wineboot: Path,
    artifact_dir: Path,
    dry_run: bool,
) -> dict[str, object]:
    ensure_directory(prefix)
    log_path = artifact_dir / "wineboot.log"
    command = [str(xvfb_run), "-a", str(wineboot), "-u"]
    if dry_run:
        return {"command": command, "log": str(log_path.resolve()), "returncode": None, "dry_run": True}
    started = time.time()
    with log_path.open("wb") as log_handle:
        completed = subprocess.run(
            command,
            env=_wine_environment(prefix),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return {
        "command": command,
        "log": str(log_path.resolve()),
        "returncode": completed.returncode,
        "elapsed_seconds": time.time() - started,
        "dry_run": False,
    }


def _run_launch_only(
    *,
    game_dir: Path,
    prefix: Path,
    xvfb_run: Path,
    wine: Path,
    wineserver: Path,
    artifact_dir: Path,
    timeout_seconds: float,
    dry_run: bool,
) -> dict[str, object]:
    executable = _retail_executable(game_dir)
    log_path = artifact_dir / "wine.log"
    command = [str(xvfb_run), "-a", str(wine), str(executable.name)]
    if dry_run:
        return {
            "command": command,
            "cwd": str(game_dir.resolve()),
            "log": str(log_path.resolve()),
            "returncode": None,
            "timed_out": False,
            "dry_run": True,
        }

    started = time.time()
    timed_out = False
    returncode: int | None = None
    with log_path.open("wb") as log_handle:
        try:
            completed = subprocess.run(
                command,
                cwd=game_dir,
                env=_wine_environment(prefix),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    subprocess.run(
        [str(wineserver), "-k"],
        env=_wine_environment(prefix),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    wine_log = _summarize_wine_log(log_path)
    final_oracle = _classify_retail_outcome(
        window_oracle=None,
        wine_log=wine_log,
        observed_returncode=returncode,
        timed_out=timed_out,
    )
    return {
        "command": command,
        "cwd": str(game_dir.resolve()),
        "log": str(log_path.resolve()),
        "returncode": returncode,
        "observed_returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": time.time() - started,
        "dry_run": False,
        "termination_reason": final_oracle["classification"],
        "retail_signature_key": retail_signature_key(
            final_oracle["classification"],
            wine_log.get("primary_signature") if isinstance(wine_log.get("primary_signature"), str) else None,
        ),
        "oracle": final_oracle,
        "wine_log": wine_log,
    }


def _start_xvfb(
    *,
    artifact_dir: Path,
    xvfb: Path,
    display: str,
    screen_size: str = DEFAULT_SCREEN_SIZE,
) -> tuple[subprocess.Popen[bytes], dict[str, object]]:
    log_path = artifact_dir / "xvfb.log"
    log_handle = log_path.open("wb")
    try:
        process = subprocess.Popen(
            [str(xvfb), display, "-screen", "0", screen_size, "-nolisten", "tcp"],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    except BaseException:
        log_handle.close()
        raise
    time.sleep(0.5)
    if process.poll() is not None:
        log_handle.close()
        raise RuntimeError(f"Xvfb exited early with {process.returncode}")
    return process, {
        "command": [str(xvfb), display, "-screen", "0", screen_size, "-nolisten", "tcp"],
        "display": display,
        "log": str(log_path.resolve()),
        "_log_handle": log_handle,
    }


def _capture_size_from_xvfb_screen_size(screen_size: str) -> str:
    parts = screen_size.split("x")
    if len(parts) != 3:
        raise ValueError("Xvfb screen size must be WIDTHxHEIGHTxDEPTH")
    width, height, depth = parts
    for label, value in (("width", width), ("height", height), ("depth", depth)):
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"Xvfb screen {label} must be an integer") from exc
        if parsed <= 0:
            raise ValueError(f"Xvfb screen {label} must be positive")
    return f"{int(width)}x{int(height)}"


def _capture_screenshot(
    *,
    artifact_dir: Path,
    ffmpeg: Path,
    display: str,
    name: str,
    screen_size: str = "1024x768",
) -> Path:
    screenshot_path = artifact_dir / f"{name}.png"
    subprocess.run(
        [
            str(ffmpeg),
            "-loglevel",
            "error",
            "-y",
            "-f",
            "x11grab",
            "-video_size",
            screen_size,
            "-i",
            display,
            "-frames:v",
            "1",
            str(screenshot_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return screenshot_path


def _decode_rgb24(ffmpeg: Path, image_path: Path) -> bytes:
    result = subprocess.run(
        [
            str(ffmpeg),
            "-loglevel",
            "error",
            "-i",
            str(image_path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _pixel_profile(rgb24: bytes) -> dict[str, object]:
    if len(rgb24) % 3:
        raise ValueError("rgb24 payload length is not divisible by 3")
    total_pixels = len(rgb24) // 3
    counts = Counter(rgb24[index:index + 3] for index in range(0, len(rgb24), 3))
    most_common = counts.most_common(4)
    top_count = most_common[0][1] if most_common else 0
    top_two_count = sum(count for _, count in most_common[:2])
    return {
        "total_pixels": total_pixels,
        "unique_colors": len(counts),
        "top_color_ratio": (top_count / total_pixels) if total_pixels else 0.0,
        "top_two_color_ratio": (top_two_count / total_pixels) if total_pixels else 0.0,
        "top_colors": [
            {
                "rgb_hex": color.hex(),
                "count": count,
                "ratio": (count / total_pixels) if total_pixels else 0.0,
            }
            for color, count in most_common
        ],
    }


def _is_low_information_profile(profile: object) -> bool:
    if not isinstance(profile, dict):
        return False
    unique_colors = profile.get("unique_colors")
    top_two_ratio = profile.get("top_two_color_ratio")
    return (
        isinstance(unique_colors, int)
        and unique_colors <= LOW_INFORMATION_UNIQUE_COLOR_LIMIT
        and isinstance(top_two_ratio, (int, float))
        and float(top_two_ratio) >= LOW_INFORMATION_TOP_TWO_COLOR_RATIO
    )


def _progress_probe_is_low_information(progress_probe: object) -> bool:
    if not isinstance(progress_probe, dict):
        return False
    return (
        progress_probe.get("identical_pixels") is True
        and _is_low_information_profile(progress_probe.get("first_pixel_profile"))
        and _is_low_information_profile(progress_probe.get("second_pixel_profile"))
    )


def _probe_screenshot_progress(
    *,
    ffmpeg: Path,
    first_screenshot: Path,
    second_screenshot: Path,
    probe_seconds: float,
) -> dict[str, object]:
    first_rgb24 = _decode_rgb24(ffmpeg, first_screenshot)
    second_rgb24 = _decode_rgb24(ffmpeg, second_screenshot)
    if len(first_rgb24) != len(second_rgb24):
        raise ValueError("progress probe screenshots decoded to different sizes")
    first_sha256 = hashlib.sha256(first_rgb24).hexdigest()
    second_sha256 = hashlib.sha256(second_rgb24).hexdigest()
    first_profile = _pixel_profile(first_rgb24)
    second_profile = _pixel_profile(second_rgb24)
    total_pixels = len(first_rgb24) // 3
    changed_pixels = sum(
        first_rgb24[index:index + 3] != second_rgb24[index:index + 3]
        for index in range(0, len(first_rgb24), 3)
    )
    return {
        "probe_seconds": probe_seconds,
        "first_screenshot": str(first_screenshot.resolve()),
        "second_screenshot": str(second_screenshot.resolve()),
        "first_pixel_sha256": first_sha256,
        "second_pixel_sha256": second_sha256,
        "first_pixel_profile": first_profile,
        "second_pixel_profile": second_profile,
        "total_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "pixel_change_ratio": (changed_pixels / total_pixels) if total_pixels else 0.0,
        "identical_pixels": first_sha256 == second_sha256,
    }


def _compare_screenshots(
    *,
    ffmpeg: Path,
    baseline_screenshot: Path,
    mutant_screenshot: Path,
) -> dict[str, object]:
    baseline_rgb24 = _decode_rgb24(ffmpeg, baseline_screenshot)
    mutant_rgb24 = _decode_rgb24(ffmpeg, mutant_screenshot)
    if len(baseline_rgb24) != len(mutant_rgb24):
        raise ValueError("baseline and mutant screenshots decoded to different sizes")
    baseline_sha256 = hashlib.sha256(baseline_rgb24).hexdigest()
    mutant_sha256 = hashlib.sha256(mutant_rgb24).hexdigest()
    baseline_profile = _pixel_profile(baseline_rgb24)
    mutant_profile = _pixel_profile(mutant_rgb24)
    total_pixels = len(baseline_rgb24) // 3
    changed_pixels = sum(
        baseline_rgb24[index:index + 3] != mutant_rgb24[index:index + 3]
        for index in range(0, len(baseline_rgb24), 3)
    )
    return {
        "baseline_screenshot": str(baseline_screenshot.resolve()),
        "mutant_screenshot": str(mutant_screenshot.resolve()),
        "baseline_pixel_sha256": baseline_sha256,
        "mutant_pixel_sha256": mutant_sha256,
        "baseline_pixel_profile": baseline_profile,
        "mutant_pixel_profile": mutant_profile,
        "total_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "pixel_change_ratio": (changed_pixels / total_pixels) if total_pixels else 0.0,
        "identical_pixels": baseline_sha256 == mutant_sha256,
    }


def _capture_window_census(
    *,
    artifact_dir: Path,
    display: str,
    xdotool: Path,
    xprop: Path,
    xwininfo: Path,
) -> dict[str, object]:
    environment = {**os.environ, "DISPLAY": display}
    search = subprocess.run(
        [str(xdotool), "search", "--all", "--name", ".*"],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    window_ids = sorted({line.strip() for line in search.stdout.splitlines() if line.strip()})
    windows: list[dict[str, object]] = []
    for window_id in window_ids:
        name_result = subprocess.run(
            [str(xdotool), "getwindowname", window_id],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        name = name_result.stdout.strip()
        xprop_result = subprocess.run(
            [str(xprop), "-id", window_id, "WM_CLASS", "_NET_WM_PID"],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        wm_class = None
        pid = None
        for line in xprop_result.stdout.splitlines():
            if line.startswith("WM_CLASS("):
                _, _, value = line.partition("=")
                wm_class = value.strip()
            elif line.startswith("_NET_WM_PID("):
                _, _, value = line.partition("=")
                value = value.strip()
                pid = int(value) if value.isdigit() else None
        windows.append(
            {
                "window_id": window_id,
                "name": name,
                "wm_class": wm_class,
                "pid": pid,
            }
        )

    names_path = artifact_dir / "control-window-names.txt"
    names_path.write_text(
        "\n".join(window["name"] for window in windows) + ("\n" if windows else ""),
        encoding="utf-8",
    )
    xwininfo_result = subprocess.run(
        [str(xwininfo), "-root", "-tree"],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    xwininfo_path = artifact_dir / "control-xwininfo.txt"
    xwininfo_path.write_text(xwininfo_result.stdout, encoding="utf-8")
    census_path = artifact_dir / "control-window-census.json"
    census_payload = {
        "display": display,
        "windows": windows,
        "window_names_path": str(names_path.resolve()),
        "xwininfo_path": str(xwininfo_path.resolve()),
    }
    census_path.write_text(json.dumps(census_payload, indent=2) + "\n", encoding="utf-8")
    return {
        **census_payload,
        "census_path": str(census_path.resolve()),
    }


def _classify_window_census(census: dict[str, object]) -> dict[str, object]:
    windows = census.get("windows")
    if not isinstance(windows, list):
        return {"classification": "unknown", "interesting": False}
    titles = [
        window.get("name")
        for window in windows
        if isinstance(window, dict) and isinstance(window.get("name"), str)
    ]
    crash_titles = [
        title
        for title in titles
        if any(token in title for token in ("プログラム エラー", "Program Error", "Wine Debugger"))
    ]
    error_titles = [
        title
        for title in titles
        if title.strip().lower() in ("log", "error")
    ]
    game_titles = [title for title in titles if "東方紅魔郷" in title]
    if crash_titles:
        return {
            "classification": "crash-dialog",
            "interesting": True,
            "crash_titles": crash_titles,
            "error_titles": error_titles,
            "game_titles": game_titles,
        }
    if error_titles:
        return {
            "classification": "retail-error-dialog",
            "interesting": False,
            "crash_titles": [],
            "error_titles": error_titles,
            "game_titles": game_titles,
        }
    if game_titles:
        return {
            "classification": "game-window-live",
            "interesting": False,
            "crash_titles": [],
            "error_titles": [],
            "game_titles": game_titles,
        }
    return {
        "classification": "no-game-window",
        "interesting": False,
        "crash_titles": [],
        "error_titles": [],
        "game_titles": [],
    }


def _classify_control_observation(
    census: dict[str, object],
    *,
    progress_probe: dict[str, object] | None,
) -> dict[str, object]:
    oracle = _classify_window_census(census)
    if progress_probe is not None:
        oracle["progress_probe"] = progress_probe
    if (
        oracle.get("classification") == "game-window-live"
        and isinstance(progress_probe, dict)
        and progress_probe.get("identical_pixels") is True
    ):
        if _progress_probe_is_low_information(progress_probe):
            return {
                **oracle,
                "classification": "game-window-blank-static",
                "interesting": False,
                "blank_screen_thresholds": {
                    "unique_color_limit": LOW_INFORMATION_UNIQUE_COLOR_LIMIT,
                    "top_two_color_ratio": LOW_INFORMATION_TOP_TWO_COLOR_RATIO,
                },
            }
        return {
            **oracle,
            "classification": "game-window-static",
            "interesting": True,
        }
    return oracle


def _progress_verification_is_frame_stall(progress_verification: object) -> bool:
    if not isinstance(progress_verification, dict):
        return False
    if progress_verification.get("verified"):
        return False
    reasons = progress_verification.get("reasons")
    if not isinstance(reasons, list):
        return False
    reason_set = {reason for reason in reasons if isinstance(reason, str)}
    frame_reasons = {"frame-not-advanced", "frame-before-minimum"}
    stage_reasons = {
        "runtime-unreadable",
        "still-in-menu",
        "stage-mismatch",
        "difficulty-mismatch",
    }
    return bool(reason_set & frame_reasons) and not bool(reason_set & stage_reasons)


def _summarize_wine_log(log_path: Path, *, max_lines: int = 8) -> dict[str, object]:
    if not log_path.is_file():
        return {
            "path": str(log_path.resolve()),
            "classification": "missing-log",
            "interesting": False,
            "primary_signature": None,
            "normalized_primary_signature": None,
            "crash_lines": [],
            "error_lines": [],
        }
    crash_lines: list[str] = []
    error_lines: list[str] = []
    text = log_path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(token in lowered for token in WINE_CRASH_LOG_TOKENS):
            if line not in crash_lines and len(crash_lines) < max_lines:
                crash_lines.append(line)
            continue
        if WINE_ERROR_LOG_TOKEN in lowered and line not in error_lines and len(error_lines) < max_lines:
            error_lines.append(line)
    return {
        "path": str(log_path.resolve()),
        "classification": "wine-crash-log" if crash_lines else "no-crash-signature",
        "interesting": bool(crash_lines),
        "primary_signature": crash_lines[0] if crash_lines else None,
        "normalized_primary_signature": (
            normalize_wine_primary_signature(crash_lines[0]) if crash_lines else None
        ),
        "crash_lines": crash_lines,
        "error_lines": error_lines,
    }


def _classify_retail_outcome(
    *,
    window_oracle: dict[str, object] | None,
    wine_log: dict[str, object],
    observed_returncode: int | None,
    timed_out: bool,
) -> dict[str, object]:
    window_classification = (
        window_oracle.get("classification")
        if isinstance(window_oracle, dict) and isinstance(window_oracle.get("classification"), str)
        else None
    )
    sources: list[str] = []
    if window_classification is not None:
        sources.append("window-census")
    if wine_log.get("classification") == "wine-crash-log":
        sources.append("wine-log")
    if observed_returncode is not None:
        sources.append("process-exit")

    if window_classification == "crash-dialog":
        classification = "crash-dialog"
        interesting = True
    elif wine_log.get("classification") == "wine-crash-log":
        classification = "wine-crash-log"
        interesting = True
    elif observed_returncode not in (None, 0):
        classification = "abnormal-exit"
        interesting = True
    elif window_classification is not None and window_classification != "unknown":
        classification = window_classification
        interesting = bool(window_oracle.get("interesting")) if isinstance(window_oracle, dict) else False
    elif timed_out:
        classification = "retail-timeout"
        interesting = False
    elif observed_returncode == 0:
        classification = "clean-exit"
        interesting = False
    else:
        classification = "unknown"
        interesting = False

    return {
        "classification": classification,
        "interesting": interesting,
        "sources": sources,
        "window_oracle_classification": window_classification,
        "wine_log_classification": wine_log.get("classification"),
        "wine_log_primary_signature": wine_log.get("primary_signature"),
        "wine_log_normalized_primary_signature": wine_log.get("normalized_primary_signature"),
        "observed_returncode": observed_returncode,
        "timed_out": timed_out,
    }


def _control_oracle_classification(run_report: dict[str, object] | None) -> str | None:
    if not isinstance(run_report, dict):
        return None
    control = run_report.get("control")
    if not isinstance(control, dict):
        return None
    oracle = control.get("oracle")
    if not isinstance(oracle, dict):
        return None
    value = oracle.get("classification")
    return value if isinstance(value, str) else None


def _control_entered_stage_screenshot(run_report: dict[str, object] | None) -> Path | None:
    if not isinstance(run_report, dict):
        return None
    control = run_report.get("control")
    if not isinstance(control, dict):
        return None
    value = control.get("entered_stage_screenshot")
    if not isinstance(value, str):
        return None
    path = Path(value)
    return path if path.is_file() else None


def _control_progress_probe_screenshot(run_report: dict[str, object] | None) -> Path | None:
    if not isinstance(run_report, dict):
        return None
    control = run_report.get("control")
    if not isinstance(control, dict):
        return None
    progress_probe = control.get("progress_probe")
    if not isinstance(progress_probe, dict):
        return None
    value = progress_probe.get("second_screenshot")
    if not isinstance(value, str):
        return None
    path = Path(value)
    return path if path.is_file() else None


def _compare_against_clean_baseline(
    *,
    ffmpeg: Path,
    baseline_report: dict[str, object],
    mutant_report: dict[str, object],
) -> dict[str, object]:
    baseline_run = baseline_report.get("run")
    mutant_run = mutant_report.get("run")
    baseline_termination = (
        baseline_run.get("termination_reason")
        if isinstance(baseline_run, dict) and isinstance(baseline_run.get("termination_reason"), str)
        else None
    )
    mutant_termination = (
        mutant_run.get("termination_reason")
        if isinstance(mutant_run, dict) and isinstance(mutant_run.get("termination_reason"), str)
        else None
    )
    baseline_control = _control_oracle_classification(baseline_run if isinstance(baseline_run, dict) else None)
    mutant_control = _control_oracle_classification(mutant_run if isinstance(mutant_run, dict) else None)

    comparisons: dict[str, dict[str, object]] = {}
    baseline_entered = _control_entered_stage_screenshot(
        baseline_run if isinstance(baseline_run, dict) else None
    )
    mutant_entered = _control_entered_stage_screenshot(
        mutant_run if isinstance(mutant_run, dict) else None
    )
    if baseline_entered is not None and mutant_entered is not None:
        comparisons["entered_stage"] = _compare_screenshots(
            ffmpeg=ffmpeg,
            baseline_screenshot=baseline_entered,
            mutant_screenshot=mutant_entered,
        )
    baseline_progress = _control_progress_probe_screenshot(
        baseline_run if isinstance(baseline_run, dict) else None
    )
    mutant_progress = _control_progress_probe_screenshot(
        mutant_run if isinstance(mutant_run, dict) else None
    )
    if baseline_progress is not None and mutant_progress is not None:
        comparisons["progress_probe"] = _compare_screenshots(
            ffmpeg=ffmpeg,
            baseline_screenshot=baseline_progress,
            mutant_screenshot=mutant_progress,
        )

    ratios = [
        comparison.get("pixel_change_ratio")
        for comparison in comparisons.values()
        if isinstance(comparison.get("pixel_change_ratio"), (int, float))
    ]
    max_ratio = max(ratios) if ratios else None

    if baseline_control == "retail-control-error" or mutant_control == "retail-control-error":
        classification = "baseline-control-error"
        interesting = False
    elif baseline_termination != mutant_termination or baseline_control != mutant_control:
        classification = "baseline-oracle-drift"
        interesting = True
    elif not comparisons:
        classification = "baseline-unavailable"
        interesting = False
    elif all(bool(comparison.get("identical_pixels")) for comparison in comparisons.values()):
        classification = "baseline-equivalent"
        interesting = False
    elif max_ratio is not None and max_ratio >= BASELINE_VISUAL_DRIFT_RATIO:
        classification = "baseline-visual-drift"
        interesting = False
    elif max_ratio is not None and max_ratio <= BASELINE_EQUIVALENCE_RATIO:
        classification = "baseline-equivalent"
        interesting = False
    else:
        classification = "baseline-minor-drift"
        interesting = False

    return {
        "classification": classification,
        "interesting": interesting,
        "baseline_termination_reason": baseline_termination,
        "mutant_termination_reason": mutant_termination,
        "baseline_control_oracle_classification": baseline_control,
        "mutant_control_oracle_classification": mutant_control,
        "entered_stage_diff_ratio": (
            comparisons.get("entered_stage", {}).get("pixel_change_ratio")
            if isinstance(comparisons.get("entered_stage"), dict)
            else None
        ),
        "progress_probe_diff_ratio": (
            comparisons.get("progress_probe", {}).get("pixel_change_ratio")
            if isinstance(comparisons.get("progress_probe"), dict)
            else None
        ),
        "max_diff_ratio": max_ratio,
        "thresholds": {
            "equivalent_ratio": BASELINE_EQUIVALENCE_RATIO,
            "visual_drift_ratio": BASELINE_VISUAL_DRIFT_RATIO,
        },
        "comparisons": comparisons,
        "baseline_artifact_dir": baseline_report.get("artifact_dir"),
    }


def _augment_run_report_with_baseline(
    run_report: dict[str, object] | None,
    baseline_comparison: dict[str, object] | None,
) -> dict[str, object] | None:
    if not isinstance(run_report, dict) or not isinstance(baseline_comparison, dict):
        return run_report
    oracle = run_report.get("oracle")
    if not isinstance(oracle, dict):
        return run_report
    augmented_oracle = dict(oracle)
    augmented_oracle["baseline_comparison"] = baseline_comparison
    sources = augmented_oracle.get("sources")
    if isinstance(sources, list):
        augmented_oracle["sources"] = [*sources, "baseline-compare"]
    classification = baseline_comparison.get("classification")
    if classification == "baseline-equivalent":
        augmented_oracle["classification"] = "retail-baseline-equivalent"
        augmented_oracle["interesting"] = False
    elif classification == "baseline-minor-drift":
        augmented_oracle["classification"] = "retail-baseline-minor-drift"
        augmented_oracle["interesting"] = False
    elif classification == "baseline-control-error":
        augmented_oracle["classification"] = "retail-baseline-control-error"
        augmented_oracle["interesting"] = False
    elif not augmented_oracle.get("interesting") and classification == "baseline-oracle-drift":
        augmented_oracle["classification"] = "retail-baseline-oracle-drift"
        augmented_oracle["interesting"] = True
    wine_log = run_report.get("wine_log")
    primary_signature = (
        wine_log.get("primary_signature")
        if isinstance(wine_log, dict) and isinstance(wine_log.get("primary_signature"), str)
        else None
    )
    return {
        **run_report,
        "termination_reason": augmented_oracle["classification"],
        "retail_signature_key": retail_signature_key(
            augmented_oracle["classification"],
            primary_signature,
        ),
        "oracle": augmented_oracle,
    }


def _wait_for_window(
    *,
    xdotool: Path,
    display: str,
    name: str,
    timeout_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            [str(xdotool), "search", "--name", name],
            env={**os.environ, "DISPLAY": display},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        windows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if windows:
            return windows[-1]
        time.sleep(0.05)
    raise TimeoutError(f"retail window {name!r} was not found within {timeout_seconds} seconds")


def _tap_key(
    *,
    xdotool: Path,
    display: str,
    window_id: str,
    key: str,
    hold_seconds: float = TAP_HOLD_SECONDS,
    settle_seconds: float = TAP_SETTLE_SECONDS,
) -> dict[str, object]:
    environment = {**os.environ, "DISPLAY": display}
    subprocess.run(
        [str(xdotool), "windowfocus", window_id],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    subprocess.run(
        [str(xdotool), "keydown", key],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    time.sleep(hold_seconds)
    subprocess.run(
        [str(xdotool), "keyup", key],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    time.sleep(settle_seconds)
    return {"key": key, "hold_seconds": hold_seconds, "settle_seconds": settle_seconds}


def _read_process_memory(process_id: int, address: int, size: int) -> bytes:
    fd = os.open(f"/proc/{process_id}/mem", os.O_RDONLY)
    try:
        data = os.pread(fd, size, address)
    finally:
        os.close(fd)
    if len(data) != size:
        raise OSError(
            f"short read from process {process_id} at 0x{address:08x}: "
            f"{len(data)} of {size} bytes"
        )
    return data


def _i32_at(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset:offset + 4], "little", signed=True)


def _u32_at(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset:offset + 4], "little", signed=False)


def _menu_state_payload(state: tuple[int, int, int]) -> dict[str, object]:
    menu_state, cursor, timer = state
    return {
        "state": menu_state,
        "state_name": MENU_STATE_NAMES.get(menu_state, "unknown"),
        "cursor": cursor,
        "timer": timer,
    }


def _read_menu_state(process_id: int) -> tuple[int, int, int]:
    block = _read_process_memory(
        process_id,
        ADDR_MAIN_MENU_CURSOR,
        ADDR_MAIN_MENU_TIMER + 4 - ADDR_MAIN_MENU_CURSOR,
    )
    return (
        _i32_at(block, ADDR_MAIN_MENU_STATE - ADDR_MAIN_MENU_CURSOR),
        _i32_at(block, 0),
        _i32_at(block, ADDR_MAIN_MENU_TIMER - ADDR_MAIN_MENU_CURSOR),
    )


def _try_read_menu_state(process_id: int) -> dict[str, object]:
    try:
        return {"readable": True, **_menu_state_payload(_read_menu_state(process_id))}
    except OSError as exc:
        return {
            "readable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _read_retail_runtime_state(process_id: int) -> dict[str, object]:
    try:
        game = _read_process_memory(process_id, ADDR_GAME_MANAGER, GAME_STAGE_OFFSET + 4)
        supervisor = _read_process_memory(
            process_id,
            ADDR_SUPERVISOR + SUPERVISOR_STATES_OFFSET,
            8,
        )
    except OSError as exc:
        return {
            "readable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    game_menu, retry_menu, gameplay_active, completed, practice, demo_mode = (
        game[GAME_FLAGS_OFFSET:GAME_FLAGS_OFFSET + 6]
    )
    in_menu = bool(game_menu or retry_menu or not gameplay_active or demo_mode)
    return {
        "readable": True,
        "frame": _u32_at(game, GAME_FRAMES_OFFSET),
        "stage": _i32_at(game, GAME_STAGE_OFFSET),
        "difficulty": _i32_at(game, GAME_DIFFICULTY_OFFSET),
        "time_stopped": bool(game[GAME_TIME_STOPPED_OFFSET]),
        "in_menu": in_menu,
        "flags": {
            "game_menu": int(game_menu),
            "retry_menu": int(retry_menu),
            "gameplay_active": int(gameplay_active),
            "completed": int(completed),
            "practice": int(practice),
            "demo_mode": int(demo_mode),
        },
        "supervisor": {
            "wanted": _i32_at(supervisor, 0),
            "current": _i32_at(supervisor, 4),
        },
    }


def _verify_stage_entry(
    runtime: dict[str, object],
    *,
    expected_stage: int,
    expected_difficulty: int,
    minimum_frame: int = 1,
) -> dict[str, object]:
    reasons: list[str] = []
    if runtime.get("readable") is not True:
        reasons.append("runtime-unreadable")
    if runtime.get("in_menu") is not False:
        reasons.append("still-in-menu")
    if runtime.get("stage") != expected_stage:
        reasons.append("stage-mismatch")
    if runtime.get("difficulty") != expected_difficulty:
        reasons.append("difficulty-mismatch")
    frame = runtime.get("frame")
    if not isinstance(frame, int) or frame <= 0:
        reasons.append("frame-not-advanced")
    elif frame < minimum_frame:
        reasons.append("frame-before-minimum")
    return {
        "verified": not reasons,
        "expected_stage": expected_stage,
        "expected_difficulty": expected_difficulty,
        "minimum_frame": minimum_frame,
        "reasons": reasons,
        "runtime": runtime,
    }


def _wait_verified_stage_entry(
    *,
    process_id: int,
    expected_stage: int,
    expected_difficulty: int,
    minimum_frame: int,
    timeout_seconds: float,
) -> dict[str, object]:
    started = time.monotonic()
    deadline = started + timeout_seconds
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = _verify_stage_entry(
            _read_retail_runtime_state(process_id),
            expected_stage=expected_stage,
            expected_difficulty=expected_difficulty,
            minimum_frame=minimum_frame,
        )
        if last["verified"]:
            return {
                **last,
                "timed_out": False,
                "wait_elapsed_seconds": time.monotonic() - started,
            }
        time.sleep(0.02)
    if last is None:
        last = _verify_stage_entry(
            _read_retail_runtime_state(process_id),
            expected_stage=expected_stage,
            expected_difficulty=expected_difficulty,
            minimum_frame=minimum_frame,
        )
    return {
        **last,
        "timed_out": True,
        "wait_elapsed_seconds": time.monotonic() - started,
    }


def _recorded_tap_key(
    *,
    process_id: int,
    xdotool: Path,
    display: str,
    window_id: str,
    key: str,
) -> dict[str, object]:
    before = _try_read_menu_state(process_id)
    step = _tap_key(
        xdotool=xdotool,
        display=display,
        window_id=window_id,
        key=key,
        hold_seconds=MENU_TAP_HOLD_SECONDS,
        settle_seconds=MENU_TAP_SETTLE_SECONDS,
    )
    after = _try_read_menu_state(process_id)
    return {**step, "menu_before": before, "menu_after": after}


def _wait_menu_state(
    process_id: int,
    wanted: int,
    *,
    minimum_timer: int | None = None,
    timeout_seconds: float = MENU_READ_TIMEOUT_SECONDS,
) -> tuple[int, int, int]:
    deadline = time.monotonic() + timeout_seconds
    last: tuple[int, int, int] | None = None
    while time.monotonic() < deadline:
        try:
            last = _read_menu_state(process_id)
        except OSError as exc:
            raise MenuNavigationError(
                f"cannot read TH06 menu state: {type(exc).__name__}: {exc}"
            ) from exc
        if last[0] == wanted and (minimum_timer is None or last[2] >= minimum_timer):
            return last
        time.sleep(0.02)
    rendered = _menu_state_payload(last) if last is not None else None
    name = MENU_STATE_NAMES.get(wanted, str(wanted))
    if minimum_timer is None:
        raise MenuNavigationError(f"menu state {name} not reached; last={rendered}")
    raise MenuNavigationError(
        f"menu state {name} did not settle to timer>={minimum_timer}; last={rendered}"
    )


def _select_menu_cursor(
    *,
    process_id: int,
    xdotool: Path,
    display: str,
    window_id: str,
    steps: list[dict[str, object]],
    state: int,
    target: int,
    length: int,
) -> None:
    for _ in range(length * 4):
        _menu_state, cursor, _timer = _wait_menu_state(process_id, state)
        if cursor == target:
            return
        if not 0 <= cursor < length:
            raise MenuNavigationError(
                f"menu cursor out of range in state {state}: cursor={cursor}, length={length}"
            )
        downward = (target - cursor) % length
        upward = (cursor - target) % length
        steps.append(_recorded_tap_key(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            key="Down" if downward <= upward else "Up",
        ))
    raise MenuNavigationError(
        f"could not select cursor {target} in state {state}; last={_menu_state_payload(_read_menu_state(process_id))}"
    )


def _enter_main_menu(
    *,
    process_id: int,
    xdotool: Path,
    display: str,
    window_id: str,
    steps: list[dict[str, object]],
) -> None:
    deadline = time.monotonic() + MENU_READ_TIMEOUT_SECONDS
    last: tuple[int, int, int] | None = None
    while time.monotonic() < deadline:
        try:
            last = _read_menu_state(process_id)
        except OSError as exc:
            raise MenuNavigationError(
                f"cannot read TH06 menu state: {type(exc).__name__}: {exc}"
            ) from exc
        state, _cursor, timer = last
        if state == MENU_STATE_MAIN_MENU:
            _wait_menu_state(process_id, MENU_STATE_MAIN_MENU, minimum_timer=20)
            return
        if state == MENU_STATE_PRE_INPUT and timer >= 30:
            steps.append(_recorded_tap_key(
                process_id=process_id,
                xdotool=xdotool,
                display=display,
                window_id=window_id,
                key="z",
            ))
        time.sleep(0.02)
    rendered = _menu_state_payload(last) if last is not None else None
    raise MenuNavigationError(f"main menu not reached; last={rendered}")


def _drive_practice_stage(
    *,
    artifact_dir: Path,
    ffmpeg: Path,
    xdotool: Path,
    xprop: Path,
    xwininfo: Path,
    display: str,
    window_id: str,
    process_id: int,
    stage: int,
    difficulty: int,
    stage_entry_wait_seconds: float,
    stage_entry_min_frame: int,
    progress_probe_seconds: float,
    progress_probe_frames: int,
    screen_size: str,
) -> dict[str, object]:
    screenshots: list[str] = []
    steps: list[dict[str, object]] = []
    menu_observations: list[dict[str, object]] = []
    navigation_error = None

    def capture(name: str) -> Path:
        screenshot = _capture_screenshot(
            artifact_dir=artifact_dir,
            ffmpeg=ffmpeg,
            display=display,
            name=name,
            screen_size=screen_size,
        )
        screenshots.append(str(screenshot.resolve()))
        return screenshot

    def observe_menu(label: str) -> None:
        menu_observations.append({"label": label, **_try_read_menu_state(process_id)})

    if not 1 <= stage <= 6:
        raise ValueError("practice stage must be in 1..6")
    if difficulty not in range(4):
        raise ValueError("difficulty must be in 0..3")
    if stage_entry_min_frame <= 0:
        raise ValueError("stage entry minimum frame must be positive")
    if progress_probe_frames <= 0:
        raise ValueError("progress probe frames must be positive")

    capture("control-00-title")
    try:
        _enter_main_menu(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            steps=steps,
        )
        observe_menu("main-menu")
        capture("control-01-main-menu")

        _select_menu_cursor(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            steps=steps,
            state=MENU_STATE_MAIN_MENU,
            target=2,
            length=8,
        )
        steps.append(_recorded_tap_key(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            key="z",
        ))
        _wait_menu_state(process_id, MENU_STATE_DIFFICULTY_SELECT)
        observe_menu("difficulty-select")
        capture("control-02-difficulty")

        _select_menu_cursor(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            steps=steps,
            state=MENU_STATE_DIFFICULTY_SELECT,
            target=difficulty,
            length=4,
        )
        steps.append(_recorded_tap_key(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            key="z",
        ))
        _wait_menu_state(process_id, MENU_STATE_CHARACTER_SELECT, minimum_timer=30)
        observe_menu("character-select")
        capture("control-03-character")

        _select_menu_cursor(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            steps=steps,
            state=MENU_STATE_CHARACTER_SELECT,
            target=0,
            length=2,
        )
        steps.append(_recorded_tap_key(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            key="z",
        ))
        _wait_menu_state(process_id, MENU_STATE_SHOT_SELECT, minimum_timer=30)
        observe_menu("shot-select")
        capture("control-04-shot")

        _select_menu_cursor(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            steps=steps,
            state=MENU_STATE_SHOT_SELECT,
            target=0,
            length=2,
        )
        steps.append(_recorded_tap_key(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            key="z",
        ))
        _wait_menu_state(process_id, MENU_STATE_PRACTICE_STAGE_SELECT, minimum_timer=30)
        observe_menu("practice-stage-select")
        capture("control-05-stage-select")

        _select_menu_cursor(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            steps=steps,
            state=MENU_STATE_PRACTICE_STAGE_SELECT,
            target=stage - 1,
            length=6,
        )
        steps.append(_recorded_tap_key(
            process_id=process_id,
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            key="z",
        ))
    except MenuNavigationError as exc:
        navigation_error = str(exc)

    if navigation_error is None:
        stage_verification = _wait_verified_stage_entry(
            process_id=process_id,
            expected_stage=stage,
            expected_difficulty=difficulty,
            minimum_frame=stage_entry_min_frame,
            timeout_seconds=stage_entry_wait_seconds,
        )
    else:
        stage_verification = _verify_stage_entry(
            _read_retail_runtime_state(process_id),
            expected_stage=stage,
            expected_difficulty=difficulty,
            minimum_frame=stage_entry_min_frame,
        )
    final_screenshot = capture("control-06-after-stage-start")

    progress_probe = None
    progress_runtime = None
    progress_verification = None
    if navigation_error is None and stage_verification["verified"] and progress_probe_seconds > 0:
        runtime = stage_verification.get("runtime")
        frame = runtime.get("frame") if isinstance(runtime, dict) else None
        minimum_progress_frame = (
            int(frame) + progress_probe_frames
            if isinstance(frame, int)
            else stage_entry_min_frame + progress_probe_frames
        )
        progress_verification = _wait_verified_stage_entry(
            process_id=process_id,
            expected_stage=stage,
            expected_difficulty=difficulty,
            minimum_frame=minimum_progress_frame,
            timeout_seconds=progress_probe_seconds,
        )
        progress_screenshot = capture("control-07-progress-probe")
        progress_probe = _probe_screenshot_progress(
            ffmpeg=ffmpeg,
            first_screenshot=final_screenshot,
            second_screenshot=progress_screenshot,
            probe_seconds=(
                float(progress_verification.get("wait_elapsed_seconds"))
                if isinstance(progress_verification.get("wait_elapsed_seconds"), (int, float))
                else progress_probe_seconds
            ),
        )
        progress_runtime = progress_verification.get("runtime")
    census = _capture_window_census(
        artifact_dir=artifact_dir,
        display=display,
        xdotool=xdotool,
        xprop=xprop,
        xwininfo=xwininfo,
    )
    oracle = _classify_control_observation(census, progress_probe=progress_probe)
    if navigation_error is not None:
        oracle = {
            **oracle,
            "classification": "retail-control-error",
            "interesting": False,
            "navigation_error": navigation_error,
        }
    elif not stage_verification["verified"] and oracle.get("classification") not in (
        "crash-dialog",
        "retail-error-dialog",
        "no-game-window",
    ):
        oracle = {
            **oracle,
            "classification": "stage-entry-unverified",
            "interesting": False,
            "stage_entry_verification": stage_verification,
        }
    elif (
        isinstance(progress_verification, dict)
        and not progress_verification.get("verified")
        and any(
            reason
            in {
                "runtime-unreadable",
                "still-in-menu",
                "stage-mismatch",
                "difficulty-mismatch",
            }
            for reason in progress_verification.get("reasons", [])
        )
        and oracle.get("classification") not in (
            "crash-dialog",
            "retail-error-dialog",
            "no-game-window",
        )
    ):
        oracle = {
            **oracle,
            "classification": "stage-progress-unverified",
            "interesting": False,
            "progress_verification": progress_verification,
        }
    elif _progress_verification_is_frame_stall(progress_verification) and oracle.get("classification") not in (
        "crash-dialog",
        "retail-error-dialog",
        "no-game-window",
    ):
        oracle = {
            **oracle,
            "classification": "retail-frame-stall",
            "interesting": True,
            "progress_verification": progress_verification,
        }
    return {
        "mode": "practice-stage",
        "practice_stage": stage,
        "difficulty": difficulty,
        "window_id": window_id,
        "process_id": process_id,
        "stage_entry_wait_seconds": stage_entry_wait_seconds,
        "stage_entry_min_frame": stage_entry_min_frame,
        "progress_probe_seconds": progress_probe_seconds,
        "progress_probe_frames": progress_probe_frames,
        "screen_size": screen_size,
        "entered_stage_screenshot": str(final_screenshot.resolve()),
        "stage_entry_verification": stage_verification,
        "progress_verification": progress_verification,
        "progress_runtime": progress_runtime,
        "window_census": census,
        "progress_probe": progress_probe,
        "oracle": oracle,
        "steps": steps,
        "menu_observations": menu_observations,
        "screenshots": screenshots,
    }


def _run_retail_with_practice_control(
    *,
    game_dir: Path,
    prefix: Path,
    artifact_dir: Path,
    wine: Path,
    wineboot: Path,
    wineserver: Path,
    sudo: Path,
    gdb: Path,
    xvfb: Path,
    xdotool: Path,
    xprop: Path,
    xwininfo: Path,
    ffmpeg: Path,
    display: str,
    timeout_seconds: float,
    practice_stage: int,
    difficulty: int,
    startup_seconds: float,
    stage_entry_wait_seconds: float,
    stage_entry_min_frame: int,
    progress_probe_seconds: float,
    progress_probe_frames: int,
    xvfb_screen_size: str,
    startup_normalization: str,
    startup_normalization_delay_seconds: float,
    dry_run: bool,
) -> dict[str, object]:
    executable = _retail_executable(game_dir)
    game_log_path = artifact_dir / "wine.log"
    prefix_log_path = artifact_dir / "wineboot.log"
    environment = _wine_environment(prefix, display)
    command = [str(wine), str(executable.name)]
    if dry_run:
        return {
            "mode": "practice-stage",
            "command": command,
            "cwd": str(game_dir.resolve()),
            "display": display,
            "log": str(game_log_path.resolve()),
            "prefix_log": str(prefix_log_path.resolve()),
            "returncode": None,
            "timed_out": False,
            "dry_run": True,
            "control": {
                "practice_stage": practice_stage,
                "difficulty": difficulty,
                "startup_seconds": startup_seconds,
                "stage_entry_wait_seconds": stage_entry_wait_seconds,
                "stage_entry_min_frame": stage_entry_min_frame,
                "progress_probe_seconds": progress_probe_seconds,
                "progress_probe_frames": progress_probe_frames,
                "xvfb_screen_size": xvfb_screen_size,
                "startup_normalization": startup_normalization,
                "startup_normalization_delay_seconds": startup_normalization_delay_seconds,
            },
        }

    xvfb_process = None
    xvfb_report = None
    game_process = None
    timed_out = False
    control_report = None
    oracle_terminal = False
    observed_returncode = None
    cleanup_killed_process = False
    startup_normalization_report = None
    started = time.time()
    try:
        xvfb_process, xvfb_report = _start_xvfb(
            artifact_dir=artifact_dir,
            xvfb=xvfb,
            display=display,
            screen_size=xvfb_screen_size,
        )
        with prefix_log_path.open("wb") as prefix_log:
            prepared = subprocess.run(
                [str(wineboot), "-u"],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=prefix_log,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=180,
            )
        if prepared.returncode:
            raise RuntimeError(f"wineboot -u failed with {prepared.returncode}")
        game_log_handle = game_log_path.open("wb")
        try:
            game_process = subprocess.Popen(
                command,
                cwd=game_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=game_log_handle,
                stderr=subprocess.STDOUT,
            )
            if startup_normalization == "off":
                time.sleep(startup_seconds)
            else:
                time.sleep(startup_normalization_delay_seconds)
                startup_normalization_report = _normalize_retail_startup(
                    artifact_dir=artifact_dir,
                    sudo=sudo,
                    gdb=gdb,
                    process_id=game_process.pid,
                    mode=startup_normalization,
                )
                remaining_startup_seconds = max(
                    0.0,
                    startup_seconds - startup_normalization_delay_seconds,
                )
                if remaining_startup_seconds > 0:
                    time.sleep(remaining_startup_seconds)
            window_id = _wait_for_window(
                xdotool=xdotool,
                display=display,
                name=TITLE_WINDOW_NAME,
                timeout_seconds=10.0,
            )
            control_report = _drive_practice_stage(
                artifact_dir=artifact_dir,
                ffmpeg=ffmpeg,
                xdotool=xdotool,
                xprop=xprop,
                xwininfo=xwininfo,
                display=display,
                window_id=window_id,
                process_id=game_process.pid,
                stage=practice_stage,
                difficulty=difficulty,
                stage_entry_wait_seconds=stage_entry_wait_seconds,
                stage_entry_min_frame=stage_entry_min_frame,
                progress_probe_seconds=progress_probe_seconds,
                progress_probe_frames=progress_probe_frames,
                screen_size=_capture_size_from_xvfb_screen_size(xvfb_screen_size),
            )
            oracle = control_report.get("oracle") if isinstance(control_report, dict) else None
            classification = oracle.get("classification") if isinstance(oracle, dict) else None
            if classification == "crash-dialog":
                oracle_terminal = True
                timed_out = False
            else:
                remaining = max(0.0, timeout_seconds - (time.time() - started))
                if game_process.poll() is None and remaining > 0:
                    try:
                        game_process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                elif game_process.poll() is None:
                    timed_out = True
            observed_returncode = game_process.poll()
        finally:
            game_log_handle.close()
    finally:
        if game_process is not None and game_process.poll() is None:
            cleanup_killed_process = True
        if game_process is not None and game_process.poll() is None and not oracle_terminal:
            timed_out = True
        subprocess.run(
            [str(wineserver), "-k"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if game_process is not None and game_process.poll() is None:
            try:
                game_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                game_process.kill()
                game_process.wait(timeout=5)
        subprocess.run(
            [str(wineserver), "-w"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if xvfb_process is not None:
            xvfb_process.terminate()
            try:
                xvfb_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                xvfb_process.kill()
                xvfb_process.wait(timeout=5)
        if xvfb_report is not None:
            log_handle = xvfb_report.pop("_log_handle", None)
            if log_handle is not None:
                log_handle.close()

    wine_log = _summarize_wine_log(game_log_path)
    final_oracle = _classify_retail_outcome(
        window_oracle=(
            control_report.get("oracle")
            if isinstance(control_report, dict) and isinstance(control_report.get("oracle"), dict)
            else None
        ),
        wine_log=wine_log,
        observed_returncode=observed_returncode,
        timed_out=timed_out,
    )

    return {
        "mode": "practice-stage",
        "command": command,
        "cwd": str(game_dir.resolve()),
        "display": display,
        "xvfb": xvfb_report,
        "log": str(game_log_path.resolve()),
        "prefix_log": str(prefix_log_path.resolve()),
        "returncode": game_process.returncode if game_process is not None else None,
        "observed_returncode": observed_returncode,
        "cleanup_killed_process": cleanup_killed_process,
        "timed_out": timed_out,
        "elapsed_seconds": time.time() - started,
        "dry_run": False,
        "startup_normalization": startup_normalization_report,
        "termination_reason": final_oracle["classification"],
        "retail_signature_key": retail_signature_key(
            final_oracle["classification"],
            wine_log.get("primary_signature") if isinstance(wine_log.get("primary_signature"), str) else None,
        ),
        "oracle": final_oracle,
        "wine_log": wine_log,
        "control": control_report,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and launch one isolated retail confirmation case."
    )
    parser.add_argument(
        "--result",
        type=Path,
        required=True,
        help="semantic case result.json or minimizer summary.json",
    )
    parser.add_argument("--source-game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--wine", type=Path, default=Path(shutil.which("wine") or "wine"))
    parser.add_argument(
        "--wineboot",
        type=Path,
        default=Path(shutil.which("wineboot") or "wineboot"),
    )
    parser.add_argument(
        "--wineserver",
        type=Path,
        default=Path(shutil.which("wineserver") or "wineserver"),
    )
    parser.add_argument(
        "--sudo",
        type=Path,
        default=Path(shutil.which("sudo") or "sudo"),
    )
    parser.add_argument(
        "--gdb",
        type=Path,
        default=Path(shutil.which("gdb") or "gdb"),
    )
    parser.add_argument(
        "--xvfb-run",
        type=Path,
        default=Path(shutil.which("xvfb-run") or "xvfb-run"),
    )
    parser.add_argument(
        "--xvfb",
        type=Path,
        default=Path(shutil.which("Xvfb") or "Xvfb"),
    )
    parser.add_argument(
        "--xdotool",
        type=Path,
        default=Path(shutil.which("xdotool") or "xdotool"),
    )
    parser.add_argument(
        "--xprop",
        type=Path,
        default=Path(shutil.which("xprop") or "xprop"),
    )
    parser.add_argument(
        "--xwininfo",
        type=Path,
        default=Path(shutil.which("xwininfo") or "xwininfo"),
    )
    parser.add_argument(
        "--ffmpeg",
        type=Path,
        default=Path(shutil.which("ffmpeg") or "ffmpeg"),
    )
    parser.add_argument("--display", type=str)
    parser.add_argument(
        "--xvfb-screen-size",
        default=DEFAULT_SCREEN_SIZE,
        help="Xvfb screen geometry as WIDTHxHEIGHTxDEPTH; default is 1024x768x24",
    )
    parser.add_argument(
        "--color-mode-16bit",
        type=_parse_color_mode_16bit,
        default=0,
        metavar="{0,1,255,preserve}",
        help="TH06 cfg color-mode byte to write; use preserve to keep the source byte",
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--practice-stage", type=int, choices=range(1, 7))
    parser.add_argument("--difficulty", type=int, choices=range(4), default=3)
    parser.add_argument("--character", type=int, choices=range(2), default=0)
    parser.add_argument("--shot-type", type=int, choices=range(2), default=0)
    parser.add_argument("--startup-seconds", type=float, default=DEFAULT_STARTUP_SECONDS)
    parser.add_argument(
        "--startup-normalization",
        choices=("auto", "gdb", "off"),
        default="auto",
        help=(
            "normalize TH06's Wine-only first-frame catch-up with GDB; "
            "auto records failure and continues, gdb fails closed, off disables it"
        ),
    )
    parser.add_argument(
        "--startup-normalization-delay-seconds",
        type=float,
        default=DEFAULT_STARTUP_NORMALIZATION_DELAY_SECONDS,
        help="seconds to wait after process launch before the GDB startup normalization attach",
    )
    parser.add_argument(
        "--stage-entry-wait-seconds",
        type=float,
        default=DEFAULT_STAGE_ENTRY_WAIT_SECONDS,
        help="maximum wall-clock seconds to wait for the requested stage frame",
    )
    parser.add_argument(
        "--stage-entry-min-frame",
        type=int,
        default=DEFAULT_STAGE_ENTRY_MIN_FRAME,
        help="capture the entered-stage screenshot after this TH06 game frame",
    )
    parser.add_argument(
        "--progress-probe-seconds",
        type=float,
        default=DEFAULT_PROGRESS_PROBE_SECONDS,
        help="maximum wall-clock seconds to wait for the progress probe frame",
    )
    parser.add_argument(
        "--progress-probe-frames",
        type=int,
        default=DEFAULT_PROGRESS_PROBE_FRAMES,
        help="capture the progress probe after this many additional TH06 game frames",
    )
    parser.add_argument(
        "--compare-clean-baseline",
        action="store_true",
        help="run an unmodified retail control under the same practice setup and compare screenshots",
    )
    parser.add_argument(
        "--expect-classification",
        help="require the final retail oracle classification, for example crash-dialog or game-window-static",
    )
    parser.add_argument(
        "--expect-signature-key",
        help="require the final retail_signature_key written by the oracle",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run the same retail confirmation in fresh isolated attempts",
    )
    parser.add_argument(
        "--require",
        type=int,
        help="minimum matching attempts required when an expectation is set; defaults to all repeats",
    )
    return parser.parse_args()


def _parse_color_mode_16bit(value: str) -> int | None:
    if value == "preserve":
        return None
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--color-mode-16bit must be 0, 1, 255, or preserve"
        ) from exc
    if parsed not in (0, 1, 0xFF):
        raise argparse.ArgumentTypeError(
            "--color-mode-16bit must be 0, 1, 255, or preserve"
        )
    return parsed


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _expectation_requested(args: argparse.Namespace) -> bool:
    return bool(args.expect_classification or args.expect_signature_key)


def _required_matches(args: argparse.Namespace) -> int:
    if not _expectation_requested(args):
        return 0
    return args.require if args.require is not None else args.repeat


def _validate_repeat_args(args: argparse.Namespace) -> None:
    if args.repeat < 1:
        raise ValueError("--repeat must be at least 1")
    if args.require is not None:
        if args.require < 1:
            raise ValueError("--require must be at least 1")
        if args.require > args.repeat:
            raise ValueError("--require cannot exceed --repeat")
        if not _expectation_requested(args):
            raise ValueError("--require needs --expect-classification or --expect-signature-key")


def _report_run(report: dict[str, object]) -> dict[str, object] | None:
    run = report.get("run")
    return run if isinstance(run, dict) else None


def _report_oracle(report: dict[str, object]) -> dict[str, object] | None:
    run = _report_run(report)
    if run is None:
        return None
    oracle = run.get("oracle")
    return oracle if isinstance(oracle, dict) else None


def _report_classification(report: dict[str, object]) -> str | None:
    oracle = _report_oracle(report)
    if oracle is not None and isinstance(oracle.get("classification"), str):
        return str(oracle["classification"])
    run = _report_run(report)
    if run is not None and isinstance(run.get("termination_reason"), str):
        return str(run["termination_reason"])
    return None


def _report_signature_key(report: dict[str, object]) -> str | None:
    run = _report_run(report)
    if run is None:
        return None
    value = run.get("retail_signature_key")
    return value if isinstance(value, str) else None


def _expected_oracle_config(args: argparse.Namespace) -> dict[str, object] | None:
    if not _expectation_requested(args):
        return None
    return {
        "classification": args.expect_classification,
        "retail_signature_key": args.expect_signature_key,
    }


def _evaluate_retail_expectation(
    report: dict[str, object],
    *,
    expect_classification: str | None,
    expect_signature_key: str | None,
) -> dict[str, object]:
    observed_classification = _report_classification(report)
    observed_signature_key = _report_signature_key(report)
    checks: list[dict[str, object]] = []
    if expect_classification is not None:
        checks.append(
            {
                "field": "classification",
                "expected": expect_classification,
                "observed": observed_classification,
                "passed": observed_classification == expect_classification,
            }
        )
    if expect_signature_key is not None:
        checks.append(
            {
                "field": "retail_signature_key",
                "expected": expect_signature_key,
                "observed": observed_signature_key,
                "passed": observed_signature_key == expect_signature_key,
            }
        )
    return {
        "enabled": bool(checks),
        "passed": all(bool(check["passed"]) for check in checks) if checks else True,
        "checks": checks,
        "observed_classification": observed_classification,
        "observed_retail_signature_key": observed_signature_key,
    }


def _attempt_passed(attempt: dict[str, object]) -> bool:
    expectation = attempt.get("expectation")
    return isinstance(expectation, dict) and bool(expectation.get("passed"))


def _repeat_artifact_dir(args: argparse.Namespace) -> Path:
    if args.artifact_dir is not None:
        return args.artifact_dir.resolve()
    result_path = args.result.resolve()
    case_result = _load_case_result(result_path)
    seed_name, _, _, _ = _payload_from_case_result(case_result, result_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "retail-confirmation" / f"{seed_name}-{stamp}-repeat"


def _run_confirmation_once(
    args: argparse.Namespace,
    *,
    artifact_dir_override: Path | None = None,
    print_report: bool = True,
) -> dict[str, object]:
    result_path = args.result.resolve()
    if not result_path.is_file():
        raise FileNotFoundError(f"missing result json: {result_path}")
    source_game_dir = args.source_game_dir.resolve()
    if not source_game_dir.is_dir():
        raise FileNotFoundError(f"missing source game directory: {source_game_dir}")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    if (
        args.startup_seconds <= 0
        or args.startup_normalization_delay_seconds <= 0
        or args.stage_entry_wait_seconds <= 0
        or args.stage_entry_min_frame <= 0
        or args.progress_probe_seconds < 0
        or args.progress_probe_frames <= 0
    ):
        raise ValueError(
            "startup/startup-normalization/stage-entry waits and frame counts "
            "must be positive; progress-probe seconds must be non-negative"
        )
    _capture_size_from_xvfb_screen_size(args.xvfb_screen_size)
    if args.practice_stage is not None and (args.character != 0 or args.shot_type != 0):
        raise ValueError("retail practice automation currently supports Reimu A only")
    if args.compare_clean_baseline:
        if args.practice_stage is None:
            raise ValueError("--compare-clean-baseline requires --practice-stage")
        if args.prepare_only or args.dry_run:
            raise ValueError("--compare-clean-baseline requires a live non-dry run")

    case_result = _load_case_result(result_path)
    seed_name, payload, payload_path, source_result = _payload_from_case_result(
        case_result, result_path
    )
    artifact_dir = (artifact_dir_override or args.artifact_dir or _default_artifact_dir(seed_name)).resolve()
    ensure_directory(artifact_dir)
    game_dir = artifact_dir / "game"
    prefix = artifact_dir / "prefix"
    xvfb_run = _command_path(args.xvfb_run)
    wine = _command_path(args.wine)
    wineboot = _command_path(args.wineboot)
    wineserver = _command_path(args.wineserver)
    sudo = _command_path(args.sudo)
    gdb = _command_path(args.gdb)
    xvfb = _command_path(args.xvfb)
    xdotool = _command_path(args.xdotool)
    xprop = _command_path(args.xprop)
    xwininfo = _command_path(args.xwininfo)
    ffmpeg = _command_path(args.ffmpeg)
    display = args.display or _choose_display()
    baseline_report = None
    baseline_comparison = None

    if args.compare_clean_baseline:
        baseline_artifact_dir = artifact_dir / "baseline"
        ensure_directory(baseline_artifact_dir)
        baseline_game_dir = baseline_artifact_dir / "game"
        baseline_prefix = baseline_artifact_dir / "prefix"
        baseline_display = _choose_display()
        if not baseline_game_dir.exists():
            _copy_game_tree(source_game_dir, baseline_game_dir)
        baseline_config_report = _configure_game_directory(
            baseline_game_dir,
            color_mode_16bit=args.color_mode_16bit,
        )
        baseline_unlock_score_report = _restore_full_unlock_score(baseline_game_dir)
        baseline_run_report = _run_retail_with_practice_control(
            game_dir=baseline_game_dir,
            prefix=baseline_prefix,
            artifact_dir=baseline_artifact_dir,
            wine=wine,
            wineboot=wineboot,
            wineserver=wineserver,
            sudo=sudo,
            gdb=gdb,
            xvfb=xvfb,
            xdotool=xdotool,
            xprop=xprop,
            xwininfo=xwininfo,
            ffmpeg=ffmpeg,
            display=baseline_display,
            timeout_seconds=args.timeout_seconds,
            practice_stage=args.practice_stage,
            difficulty=args.difficulty,
            startup_seconds=args.startup_seconds,
            stage_entry_wait_seconds=args.stage_entry_wait_seconds,
            stage_entry_min_frame=args.stage_entry_min_frame,
            progress_probe_seconds=args.progress_probe_seconds,
            progress_probe_frames=args.progress_probe_frames,
            xvfb_screen_size=args.xvfb_screen_size,
            startup_normalization=args.startup_normalization,
            startup_normalization_delay_seconds=args.startup_normalization_delay_seconds,
            dry_run=False,
        )
        baseline_report = {
            "source_result": str(result_path),
            "semantic_source_result": str(source_result) if source_result is not None else None,
            "source_game_dir": str(source_game_dir),
            "artifact_dir": str(baseline_artifact_dir),
            "game_dir": str(baseline_game_dir),
            "wine_prefix": str(baseline_prefix),
            "display": baseline_display,
            "xvfb_screen_size": args.xvfb_screen_size,
            "seed_name": seed_name,
            "payload_path": None,
            "payload_size": None,
            "payload_sha256": None,
            "config": baseline_config_report,
            "unlock_score": baseline_unlock_score_report,
            "patched_archives": [],
            "wineboot": None,
            "run": baseline_run_report,
            "limitations": [
                "This is a clean retail control run under the same practice automation and timing.",
                "Practice automation currently covers only Reimu A via X11 keyboard injection.",
                "Route play and dialogue skipping are not implemented yet.",
            ],
        }
        _write_report(baseline_artifact_dir / "report.json", baseline_report)

    if not game_dir.exists():
        _copy_game_tree(source_game_dir, game_dir)
    config_report = _configure_game_directory(
        game_dir,
        color_mode_16bit=args.color_mode_16bit,
    )
    unlock_score_report = _restore_full_unlock_score(game_dir)
    patched_archives = [
        _patch_stage_archive(path, entry_name=seed_name, payload=payload)
        for path in _stage_archives(game_dir)
    ]

    wineboot_report = None
    run_report = None
    if args.practice_stage is not None:
        if not args.prepare_only:
            run_report = _run_retail_with_practice_control(
                game_dir=game_dir,
                prefix=prefix,
                artifact_dir=artifact_dir,
                wine=wine,
                wineboot=wineboot,
                wineserver=wineserver,
                sudo=sudo,
                gdb=gdb,
                xvfb=xvfb,
                xdotool=xdotool,
                xprop=xprop,
                xwininfo=xwininfo,
                ffmpeg=ffmpeg,
                display=display,
                timeout_seconds=args.timeout_seconds,
                practice_stage=args.practice_stage,
                difficulty=args.difficulty,
                startup_seconds=args.startup_seconds,
                stage_entry_wait_seconds=args.stage_entry_wait_seconds,
                stage_entry_min_frame=args.stage_entry_min_frame,
                progress_probe_seconds=args.progress_probe_seconds,
                progress_probe_frames=args.progress_probe_frames,
                xvfb_screen_size=args.xvfb_screen_size,
                startup_normalization=args.startup_normalization,
                startup_normalization_delay_seconds=args.startup_normalization_delay_seconds,
                dry_run=args.dry_run,
            )
        else:
            wineboot_report = {
                "mode": "practice-stage",
                "note": "prepare-only skips live Xvfb/Wine launch for stage control",
                "dry_run": args.dry_run,
            }
    else:
        wineboot_report = _prepare_wine_prefix(
            prefix,
            xvfb_run=xvfb_run,
            wineboot=wineboot,
            artifact_dir=artifact_dir,
            dry_run=args.dry_run,
        )
        if not args.prepare_only:
            run_report = _run_launch_only(
                game_dir=game_dir,
                prefix=prefix,
                xvfb_run=xvfb_run,
                wine=wine,
                wineserver=wineserver,
                artifact_dir=artifact_dir,
                timeout_seconds=args.timeout_seconds,
                dry_run=args.dry_run,
            )

    if baseline_report is not None and isinstance(run_report, dict):
        baseline_comparison = _compare_against_clean_baseline(
            ffmpeg=ffmpeg,
            baseline_report=baseline_report,
            mutant_report={"run": run_report},
        )
        run_report = _augment_run_report_with_baseline(run_report, baseline_comparison)

    report = {
        "source_result": str(result_path),
        "semantic_source_result": str(source_result) if source_result is not None else None,
        "source_game_dir": str(source_game_dir),
        "artifact_dir": str(artifact_dir),
        "game_dir": str(game_dir),
        "wine_prefix": str(prefix),
        "display": display,
        "xvfb_screen_size": args.xvfb_screen_size,
        "seed_name": seed_name,
        "payload_path": str(payload_path),
        "payload_size": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "config": config_report,
        "unlock_score": unlock_score_report,
        "patched_archives": patched_archives,
        "wineboot": wineboot_report,
        "run": run_report,
        "baseline": (
            {
                "artifact_dir": baseline_report.get("artifact_dir"),
                "report": str((Path(str(baseline_report.get("artifact_dir"))) / "report.json").resolve()),
                "comparison": baseline_comparison,
            }
            if isinstance(baseline_report, dict)
            else None
        ),
        "limitations": [
            "Launch-only mode still stops at process startup and does not prove stage ECL reached.",
            "Practice automation currently covers only Reimu A via X11 keyboard injection.",
            "Route play and dialogue skipping are not implemented yet.",
        ],
    }
    expected_oracle = _expected_oracle_config(args)
    if expected_oracle is not None:
        report["expected_oracle"] = expected_oracle
        report["expectation"] = _evaluate_retail_expectation(
            report,
            expect_classification=args.expect_classification,
            expect_signature_key=args.expect_signature_key,
        )
    _write_report(artifact_dir / "report.json", report)
    if print_report:
        print(json.dumps(report, indent=2))
    return report


def main() -> int:
    args = parse_args()
    _validate_repeat_args(args)
    if args.repeat == 1:
        report = _run_confirmation_once(args)
        expectation = report.get("expectation")
        if isinstance(expectation, dict) and expectation.get("enabled") and not expectation.get("passed"):
            return 1
        return 0

    artifact_dir = _repeat_artifact_dir(args)
    ensure_directory(artifact_dir)
    attempts: list[dict[str, object]] = []
    for run_index in range(1, args.repeat + 1):
        run_artifact_dir = artifact_dir / f"run-{run_index:03d}"
        report = _run_confirmation_once(
            args,
            artifact_dir_override=run_artifact_dir,
            print_report=False,
        )
        expectation = report.get("expectation")
        attempts.append(
            {
                "attempt": run_index,
                "artifact_dir": str(run_artifact_dir.resolve()),
                "report": str((run_artifact_dir / "report.json").resolve()),
                "classification": _report_classification(report),
                "retail_signature_key": _report_signature_key(report),
                "expectation": expectation if isinstance(expectation, dict) else None,
            }
        )

    expectation_enabled = _expectation_requested(args)
    passed_attempts = sum(int(_attempt_passed(attempt)) for attempt in attempts)
    required = _required_matches(args)
    summary = {
        "schema": "danmakufuzz-retail-confirmation-repeat-v1",
        "artifact_dir": str(artifact_dir.resolve()),
        "source_result": str(args.result.resolve()),
        "repeat": args.repeat,
        "require": required if expectation_enabled else None,
        "expected_oracle": _expected_oracle_config(args),
        "passed_attempts": passed_attempts if expectation_enabled else None,
        "expectation_passed": (passed_attempts >= required) if expectation_enabled else None,
        "attempts": attempts,
    }
    _write_report(artifact_dir / "report.json", summary)
    print(json.dumps(summary, indent=2))
    if expectation_enabled and passed_attempts < required:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
