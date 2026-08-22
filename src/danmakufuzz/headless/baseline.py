from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from .actions import parse_actions_file
from ..repo import ARTIFACTS_DIR, CONFIG_DIR, REFERENCE_DIR, THIRD_PARTY_DIR, ensure_directory


DEFAULT_ACTION_FILE = CONFIG_DIR / "headless_baseline_actions.txt"
DEFAULT_GAME_DIR = REFERENCE_DIR / "retail" / "game" / "th06"


def default_headless_binary() -> Path:
    return THIRD_PARTY_DIR / "th06-headless" / "th06"


def build_command(
    *,
    binary: Path,
    game_dir: Path,
    stage: int,
    seed: int,
    actions: Path,
    trace: Path,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
) -> list[str]:
    command = [
        str(binary),
        "--headless",
        "--seed", str(seed),
        "--max-ticks", str(max_ticks),
        "--practice-stage", str(stage),
        "--difficulty", str(difficulty),
        "--character", str(character),
        "--shot-type", str(shot_type),
        "--actions", str(actions),
        "--trace", str(trace),
    ]
    if auto_shoot:
        command.append("--auto-shoot")
    if continue_after_hit:
        command.append("--continue-after-hit")
    return command


def run_baseline(
    *,
    binary: Path,
    game_dir: Path,
    stage: int,
    seed: int,
    action_file: Path,
    artifact_dir: Path,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    dry_run: bool,
) -> dict[str, object]:
    if not binary.is_file():
        raise FileNotFoundError(f"missing headless binary: {binary}")
    if not game_dir.is_dir():
        raise FileNotFoundError(f"missing game directory: {game_dir}")
    actions = parse_actions_file(action_file)
    ensure_directory(artifact_dir)
    trace_path = artifact_dir / "trace.jsonl"
    metadata_path = artifact_dir / "baseline.json"
    command = build_command(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        actions=action_file,
        trace=trace_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
    )
    metadata = {
        "binary": str(binary.resolve()),
        "cwd": str(game_dir.resolve()),
        "stage": stage,
        "seed": seed,
        "difficulty": difficulty,
        "character": character,
        "shot_type": shot_type,
        "max_ticks": max_ticks,
        "action_file": str(action_file.resolve()),
        "action_count": actions.length,
        "trace": str(trace_path.resolve()),
        "command": command,
        "dry_run": dry_run,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if dry_run:
        return metadata
    subprocess.run(command, cwd=game_dir, check=True)
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a deterministic TH06 headless baseline trace.")
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--stage", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--max-ticks", type=int, default=600)
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir or (
        ARTIFACTS_DIR / "headless" / f"baseline-stage{args.stage}-seed{args.seed}"
    )
    metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        stage=args.stage,
        seed=args.seed,
        action_file=args.actions.resolve(),
        artifact_dir=artifact_dir.resolve(),
        difficulty=args.difficulty,
        character=args.character,
        shot_type=args.shot_type,
        max_ticks=args.max_ticks,
        auto_shoot=args.auto_shoot,
        continue_after_hit=args.continue_after_hit,
        dry_run=args.dry_run,
    )
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
