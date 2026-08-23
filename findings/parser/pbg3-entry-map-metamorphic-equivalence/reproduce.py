from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from danmakufuzz.parser.pbg3_metamorphic import DEFAULT_GAME_DIR
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


EXPECTED_FULL_CASES = 66
EXPECTED_CASES_PER_ARCHIVE = 11


def _default_quick_archive(game_dir: Path) -> Path:
    matches = sorted(path for path in game_dir.glob("*CM.DAT") if path.is_file())
    if matches:
        return matches[0]
    matches = sorted(path for path in game_dir.glob("*.DAT") if path.is_file())
    if matches:
        return matches[0]
    raise FileNotFoundError(f"no PBG3 archives found under {game_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the PBG3 entry-map metamorphic equivalence observation."
    )
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-pbg3-entry-map-metamorphic-equivalence",
    )
    parser.add_argument("--full", action="store_true", help="run all unique DAT archives instead of the quick archive")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--emit-cases", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    command = [
        sys.executable,
        "-m",
        "danmakufuzz.parser.pbg3_metamorphic",
        "--game-dir",
        str(args.game_dir.resolve()),
        "--artifact-dir",
        str(artifact_dir),
    ]
    if not args.full:
        archives = args.archive or [_default_quick_archive(args.game_dir.resolve())]
        for archive in archives:
            command.extend(["--archive", str(archive.resolve())])
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    if args.emit_cases:
        command.append("--emit-cases")
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)

    campaign_path = artifact_dir / "campaign.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign.get("violation_counts") != {}:
        raise RuntimeError(f"metamorphic violations observed: {campaign}")
    if args.limit is None and args.full and int(campaign.get("cases_generated", 0)) != EXPECTED_FULL_CASES:
        raise RuntimeError(f"full case count drifted: {campaign}")
    if args.limit is None and not args.full and not args.archive and int(campaign.get("cases_generated", 0)) != EXPECTED_CASES_PER_ARCHIVE:
        raise RuntimeError(f"case count drifted: {campaign}")
    if campaign.get("classification_counts") != {"accepted": campaign.get("cases_generated")}:
        raise RuntimeError(f"classification drifted: {campaign}")
    print(json.dumps(campaign, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
