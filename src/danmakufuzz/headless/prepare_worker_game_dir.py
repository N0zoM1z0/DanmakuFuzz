from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess

from ..headless.baseline import DEFAULT_GAME_DIR
from ..repo import ARTIFACTS_DIR, ensure_directory


def _default_destination_root() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "headless-workers" / stamp


def _copytree_best_effort(source: Path, destination: Path) -> str:
    ensure_directory(destination.parent)
    try:
        subprocess.run(
            ["cp", "-a", "--reflink=auto", str(source), str(destination)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "cp-reflink-auto"
    except (FileNotFoundError, subprocess.CalledProcessError):
        shutil.copytree(source, destination)
        return "shutil-copytree"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare an isolated TH06 game directory for one headless worker."
    )
    parser.add_argument("--source-game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--destination", type=Path)
    parser.add_argument(
        "--destination-root",
        type=Path,
        default=_default_destination_root(),
        help="parent directory for the worker copy when --destination is omitted",
    )
    parser.add_argument("--worker-name", type=str, default="worker-00")
    parser.add_argument("--reuse", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_game_dir = args.source_game_dir.resolve()
    if not source_game_dir.is_dir():
        raise FileNotFoundError(f"missing source game directory: {source_game_dir}")

    destination = (
        args.destination.resolve()
        if args.destination is not None
        else (args.destination_root.resolve() / args.worker_name)
    )
    manifest_path = destination / ".danmakufuzz-worker.json"
    if destination.exists():
        if not args.reuse:
            raise FileExistsError(f"destination already exists: {destination}")
        manifest = {}
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "destination": str(destination),
                    "reused": True,
                    "manifest": manifest,
                },
                indent=2,
            )
        )
        return 0

    copy_method = _copytree_best_effort(source_game_dir, destination)
    file_count = sum(1 for path in destination.rglob("*") if path.is_file())
    manifest = {
        "source_game_dir": str(source_game_dir),
        "destination": str(destination),
        "worker_name": args.worker_name,
        "copy_method": copy_method,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "file_count": file_count,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
