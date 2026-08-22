from __future__ import annotations

import argparse
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
DEFAULT_STARTUP_SECONDS = 5.0
DEFAULT_STAGE_ENTRY_WAIT_SECONDS = 3.0
DEFAULT_PROGRESS_PROBE_SECONDS = 2.0
DEFAULT_SCREEN_SIZE = "1024x768x24"
BASELINE_EQUIVALENCE_RATIO = 0.001
BASELINE_VISUAL_DRIFT_RATIO = 0.05
WINE_CRASH_LOG_TOKENS = (
    "unhandled page fault",
    "unhandled exception",
    "starting debugger",
)
WINE_ERROR_LOG_TOKEN = "err:"


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

    payload_path_value = case_result.get("final_payload")
    source_result_value = case_result.get("source_result")
    if not isinstance(payload_path_value, str):
        raise ValueError(
            "input json is missing semantic override_dir/seed_name or minimized final_payload"
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


def _configure_windowed(payload: bytes) -> bytes:
    if len(payload) != CONFIG_SIZE:
        raise ValueError(f"TH06 config must be {CONFIG_SIZE} bytes")
    version = int.from_bytes(payload[VERSION_OFFSET:VERSION_OFFSET + 4], "little")
    if version != VERSION_102H:
        raise ValueError(f"TH06 config version is 0x{version:x}, expected 0x102")
    if payload[WINDOWED_OFFSET] not in (0, 1):
        raise ValueError("TH06 windowed byte is invalid")
    if payload[COLOR_MODE_16BIT_OFFSET] not in (0, 1, 0xFF):
        raise ValueError("TH06 color-mode byte is invalid")
    configured = bytearray(payload)
    configured[COLOR_MODE_16BIT_OFFSET] = 0
    configured[WINDOWED_OFFSET] = 1
    return bytes(configured)


def _configure_game_directory(game_dir: Path) -> dict[str, object]:
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
    after = _configure_windowed(before)
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
    game_titles = [title for title in titles if "東方紅魔郷" in title]
    if crash_titles:
        return {
            "classification": "crash-dialog",
            "interesting": True,
            "crash_titles": crash_titles,
            "game_titles": game_titles,
        }
    if game_titles:
        return {
            "classification": "game-window-live",
            "interesting": False,
            "crash_titles": [],
            "game_titles": game_titles,
        }
    return {
        "classification": "no-game-window",
        "interesting": False,
        "crash_titles": [],
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
        return {
            **oracle,
            "classification": "game-window-static",
            "interesting": True,
        }
    return oracle


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

    if baseline_termination != mutant_termination or baseline_control != mutant_control:
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
    if not augmented_oracle.get("interesting") and classification == "baseline-oracle-drift":
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


def _difficulty_moves(target: int) -> list[str]:
    if target not in range(4):
        raise ValueError("difficulty must be in 0..3")
    start = 1
    downward = (target - start) % 4
    upward = (start - target) % 4
    if downward <= upward:
        return ["Down"] * downward
    return ["Up"] * upward


def _practice_navigation_steps(stage: int, difficulty: int) -> list[str]:
    if not 1 <= stage <= 6:
        raise ValueError("practice stage must be in 1..6")
    return [
        "z",
        "Down",
        "Down",
        "z",
        *_difficulty_moves(difficulty),
        "z",
        "z",
        "z",
        *(["Down"] * (stage - 1)),
        "z",
    ]


def _drive_practice_stage(
    *,
    artifact_dir: Path,
    ffmpeg: Path,
    xdotool: Path,
    xprop: Path,
    xwininfo: Path,
    display: str,
    window_id: str,
    stage: int,
    difficulty: int,
    stage_entry_wait_seconds: float,
    progress_probe_seconds: float,
) -> dict[str, object]:
    screenshots: list[str] = []
    steps: list[dict[str, object]] = []
    screenshots.append(str(_capture_screenshot(
        artifact_dir=artifact_dir,
        ffmpeg=ffmpeg,
        display=display,
        name="control-00-title",
    ).resolve()))
    for index, key in enumerate(_practice_navigation_steps(stage, difficulty), start=1):
        steps.append(_tap_key(
            xdotool=xdotool,
            display=display,
            window_id=window_id,
            key=key,
        ))
        if index == 1:
            name = "control-01-main-menu"
        elif index == 4:
            name = "control-02-difficulty"
        elif index == 7:
            name = "control-03-character"
        elif index == 8:
            name = "control-04-shot"
        elif index == 9:
            name = "control-05-stage-select"
        else:
            name = None
        if name is not None:
            screenshots.append(str(_capture_screenshot(
                artifact_dir=artifact_dir,
                ffmpeg=ffmpeg,
                display=display,
                name=name,
            ).resolve()))
    time.sleep(stage_entry_wait_seconds)
    final_screenshot = _capture_screenshot(
        artifact_dir=artifact_dir,
        ffmpeg=ffmpeg,
        display=display,
        name="control-06-after-stage-start",
    )
    screenshots.append(str(final_screenshot.resolve()))
    progress_probe = None
    if progress_probe_seconds > 0:
        time.sleep(progress_probe_seconds)
        progress_screenshot = _capture_screenshot(
            artifact_dir=artifact_dir,
            ffmpeg=ffmpeg,
            display=display,
            name="control-07-progress-probe",
        )
        screenshots.append(str(progress_screenshot.resolve()))
        progress_probe = _probe_screenshot_progress(
            ffmpeg=ffmpeg,
            first_screenshot=final_screenshot,
            second_screenshot=progress_screenshot,
            probe_seconds=progress_probe_seconds,
        )
    census = _capture_window_census(
        artifact_dir=artifact_dir,
        display=display,
        xdotool=xdotool,
        xprop=xprop,
        xwininfo=xwininfo,
    )
    oracle = _classify_control_observation(census, progress_probe=progress_probe)
    return {
        "mode": "practice-stage",
        "practice_stage": stage,
        "difficulty": difficulty,
        "window_id": window_id,
        "stage_entry_wait_seconds": stage_entry_wait_seconds,
        "progress_probe_seconds": progress_probe_seconds,
        "entered_stage_screenshot": str(final_screenshot.resolve()),
        "window_census": census,
        "progress_probe": progress_probe,
        "oracle": oracle,
        "steps": steps,
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
    progress_probe_seconds: float,
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
                "progress_probe_seconds": progress_probe_seconds,
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
    started = time.time()
    try:
        xvfb_process, xvfb_report = _start_xvfb(
            artifact_dir=artifact_dir,
            xvfb=xvfb,
            display=display,
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
            time.sleep(startup_seconds)
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
                stage=practice_stage,
                difficulty=difficulty,
                stage_entry_wait_seconds=stage_entry_wait_seconds,
                progress_probe_seconds=progress_probe_seconds,
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
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--practice-stage", type=int, choices=range(1, 7))
    parser.add_argument("--difficulty", type=int, choices=range(4), default=3)
    parser.add_argument("--character", type=int, choices=range(2), default=0)
    parser.add_argument("--shot-type", type=int, choices=range(2), default=0)
    parser.add_argument("--startup-seconds", type=float, default=DEFAULT_STARTUP_SECONDS)
    parser.add_argument(
        "--stage-entry-wait-seconds",
        type=float,
        default=DEFAULT_STAGE_ENTRY_WAIT_SECONDS,
    )
    parser.add_argument(
        "--progress-probe-seconds",
        type=float,
        default=DEFAULT_PROGRESS_PROBE_SECONDS,
    )
    parser.add_argument(
        "--compare-clean-baseline",
        action="store_true",
        help="run an unmodified retail control under the same practice setup and compare screenshots",
    )
    return parser.parse_args()


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
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
        or args.stage_entry_wait_seconds <= 0
        or args.progress_probe_seconds < 0
    ):
        raise ValueError("startup/stage-entry waits must be positive and progress-probe must be non-negative")
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
    artifact_dir = (args.artifact_dir or _default_artifact_dir(seed_name)).resolve()
    ensure_directory(artifact_dir)
    game_dir = artifact_dir / "game"
    prefix = artifact_dir / "prefix"
    xvfb_run = _command_path(args.xvfb_run)
    wine = _command_path(args.wine)
    wineboot = _command_path(args.wineboot)
    wineserver = _command_path(args.wineserver)
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
        baseline_config_report = _configure_game_directory(baseline_game_dir)
        baseline_unlock_score_report = _restore_full_unlock_score(baseline_game_dir)
        baseline_run_report = _run_retail_with_practice_control(
            game_dir=baseline_game_dir,
            prefix=baseline_prefix,
            artifact_dir=baseline_artifact_dir,
            wine=wine,
            wineboot=wineboot,
            wineserver=wineserver,
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
            progress_probe_seconds=args.progress_probe_seconds,
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
                "Route play, dialogue skipping, and memory-based retail state sensing are not implemented yet.",
            ],
        }
        _write_report(baseline_artifact_dir / "report.json", baseline_report)

    if not game_dir.exists():
        _copy_game_tree(source_game_dir, game_dir)
    config_report = _configure_game_directory(game_dir)
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
                progress_probe_seconds=args.progress_probe_seconds,
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
            "Route play, dialogue skipping, and memory-based retail state sensing are not implemented yet.",
        ],
    }
    _write_report(artifact_dir / "report.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
