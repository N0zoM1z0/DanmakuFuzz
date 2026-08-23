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

from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR, default_headless_binary
from danmakufuzz.repo import ARTIFACTS_DIR, CONFIG_DIR, ensure_directory


EXPECTED_CASES = 9
DEFAULT_ACTIONS = CONFIG_DIR / "headless_baseline_actions_1800.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the quick replay action-stream metamorphic equivalence observation."
    )
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTIONS)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-replay-action-stream-metamorphic-equivalence",
    )
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
        "danmakufuzz.semantic.replay_metamorphic",
        "--stage",
        "6",
        "--difficulty",
        "3",
        "--character",
        "0",
        "--shot-type",
        "0",
        "--seed",
        "7",
        "--actions",
        str(args.actions.resolve()),
        "--game-dir",
        str(args.game_dir.resolve()),
        "--headless-bin",
        str(args.headless_bin.resolve()),
        "--max-ticks",
        "1200",
        "--timeout-seconds",
        "8",
        "--continue-after-hit",
        "--trace-compact-counts",
        "--artifact-dir",
        str(artifact_dir),
    ]
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)
    campaign = json.loads((artifact_dir / "campaign.json").read_text(encoding="utf-8"))
    if campaign.get("cases_generated") != EXPECTED_CASES:
        raise RuntimeError(f"case count drifted: {campaign}")
    if campaign.get("relation_counts") != {"holds": EXPECTED_CASES}:
        raise RuntimeError(f"relation drifted: {campaign}")
    if campaign.get("classification_counts") != {"equivalent": EXPECTED_CASES}:
        raise RuntimeError(f"classification drifted: {campaign}")
    if campaign.get("violation_counts") != {}:
        raise RuntimeError(f"unexpected violations: {campaign}")
    print(json.dumps(campaign, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
