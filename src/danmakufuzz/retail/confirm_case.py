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


RETAIL_EXECUTABLE_CANDIDATES = (
    "東方紅魔郷.exe",
    "th06.exe",
)
PRIMARY_STAGE_ARCHIVE = "紅魔郷ST.DAT"
FALLBACK_STAGE_ARCHIVES = ("峠杺嫿ST.DAT",)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_case_result(result_path: Path) -> dict[str, object]:
    value = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"result.json is not an object: {result_path}")
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
    seed_name = payload_path.name
    source_result_path = Path(source_result_value).resolve() if isinstance(source_result_value, str) else None
    return seed_name, payload_path.read_bytes(), payload_path, source_result_path


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
    command = [str(xvfb_run), "-a", str(wineboot), "-i"]
    if dry_run:
        return {"command": command, "log": str(log_path.resolve()), "returncode": None, "dry_run": True}
    started = time.time()
    with log_path.open("wb") as log_handle:
        completed = subprocess.run(
            command,
            env={
                **os.environ,
                "WINEPREFIX": str(prefix.resolve()),
                "WINEDEBUG": "-all",
            },
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


def _run_retail(
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
                env={
                    **os.environ,
                    "WINEPREFIX": str(prefix.resolve()),
                    "WINEDEBUG": "-all",
                },
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
        env={
            **os.environ,
            "WINEPREFIX": str(prefix.resolve()),
            "WINEDEBUG": "-all",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(game_dir.resolve()),
        "log": str(log_path.resolve()),
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": time.time() - started,
        "dry_run": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and launch one isolated retail confirmation case.")
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
    parser.add_argument("--xvfb-run", type=Path, default=Path(shutil.which("xvfb-run") or "xvfb-run"))
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_path = args.result.resolve()
    if not result_path.is_file():
        raise FileNotFoundError(f"missing result.json: {result_path}")
    source_game_dir = args.source_game_dir.resolve()
    if not source_game_dir.is_dir():
        raise FileNotFoundError(f"missing source game directory: {source_game_dir}")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")

    case_result = _load_case_result(result_path)
    seed_name, payload, payload_path, source_result = _payload_from_case_result(case_result, result_path)
    artifact_dir = (args.artifact_dir or _default_artifact_dir(seed_name)).resolve()
    ensure_directory(artifact_dir)
    game_dir = artifact_dir / "game"
    prefix = artifact_dir / "prefix"
    xvfb_run = _command_path(args.xvfb_run)
    wine = _command_path(args.wine)
    wineboot = _command_path(args.wineboot)
    wineserver = _command_path(args.wineserver)

    if not game_dir.exists():
        _copy_game_tree(source_game_dir, game_dir)
    patched_archives = [
        _patch_stage_archive(path, entry_name=seed_name, payload=payload)
        for path in _stage_archives(game_dir)
    ]

    wineboot = _prepare_wine_prefix(
        prefix,
        xvfb_run=xvfb_run,
        wineboot=wineboot,
        artifact_dir=artifact_dir,
        dry_run=args.dry_run,
    )
    run_report = None
    if not args.prepare_only:
        run_report = _run_retail(
            game_dir=game_dir,
            prefix=prefix,
            xvfb_run=xvfb_run,
            wine=wine,
            wineserver=wineserver,
            artifact_dir=artifact_dir,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )

    report = {
        "source_result": str(result_path),
        "semantic_source_result": str(source_result) if source_result is not None else None,
        "source_game_dir": str(source_game_dir),
        "artifact_dir": str(artifact_dir),
        "game_dir": str(game_dir),
        "wine_prefix": str(prefix),
        "seed_name": seed_name,
        "payload_path": str(payload_path),
        "payload_size": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "patched_archives": patched_archives,
        "wineboot": wineboot,
        "run": run_report,
        "limitations": [
            "This runner prepares isolated retail state and can launch the original executable.",
            "It does not yet automate menu navigation into Practice/route play.",
            "Stage/ECL confirmation beyond startup still needs a separate retail control path.",
        ],
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
