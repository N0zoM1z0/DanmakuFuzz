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

from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR
from danmakufuzz.parser.anm import DEFAULT_ARCHIVE
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


EXPECTED_CASES = 12
EXPECTED_TRACE_SHA256 = "76807eba84ec4d20745dfe91fd5dd02d44f33ee4a253612f2d44df44dc440c19"
DEFAULT_ACTIONS = REPO_ROOT / "config" / "headless_baseline_actions_1800.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 ANM metamorphic runtime equivalence observation."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTIONS)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "runtime-anm-stage6-metamorphic-runtime-equivalence",
    )
    parser.add_argument("--stage", type=int, default=6)
    parser.add_argument("--max-ticks", type=int, default=1200)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
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
        "danmakufuzz.parser.anm_metamorphic_runtime",
        "--archive",
        str(args.archive.resolve()),
        "--game-dir",
        str(args.game_dir.resolve()),
        "--actions",
        str(args.actions.resolve()),
        "--artifact-dir",
        str(artifact_dir),
        "--stage",
        str(args.stage),
        "--max-ticks",
        str(args.max_ticks),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--continue-after-hit",
        "--trace-compact-counts",
    ]
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)

    campaign_path = artifact_dir / "campaign.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign.get("violation_counts") != {}:
        raise RuntimeError(f"metamorphic violations observed: {campaign}")
    if args.stage == 6 and int(campaign.get("cases_generated", 0)) != EXPECTED_CASES:
        raise RuntimeError(f"case count drifted: {campaign}")
    baseline = campaign.get("baseline")
    if not isinstance(baseline, dict) or baseline.get("trace_sha256") != EXPECTED_TRACE_SHA256:
        raise RuntimeError(f"baseline trace drifted: {campaign}")
    if campaign.get("classification_counts") != {"equivalent": campaign.get("cases_generated")}:
        raise RuntimeError(f"classification drifted: {campaign}")
    print(json.dumps(campaign, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
