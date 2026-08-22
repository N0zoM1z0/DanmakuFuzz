from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from danmakufuzz.findings.payload_patch import sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import LONG_ACTION_FILE, run_case, select_mutants


TARGET_MUTANT_NAME = "shoot-interval-one"
TARGET_MUTANT_PATH = (0, 11)
TARGET_PAYLOAD_SHA256 = "3703edfe3f1bd4ac6999964253a74b3e7c300dc7146f8b6334351450dca363e1"
TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata2.ecl"


def _target_mutant():
    seed_payload = TARGET_SEED.read_bytes()
    mutants = select_mutants(
        seed_payload,
        include_structural=False,
        name_filters=["shoot-interval-"],
    )
    for mutant in mutants:
        if mutant.name == TARGET_MUTANT_NAME and mutant.path == TARGET_MUTANT_PATH:
            mutant_sha256 = sha256_bytes(mutant.payload)
            if mutant_sha256 != TARGET_PAYLOAD_SHA256:
                raise RuntimeError(
                    f"target mutant sha256 drifted: expected {TARGET_PAYLOAD_SHA256}, got {mutant_sha256}"
                )
            return mutant
    raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME} at {TARGET_MUTANT_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 2 shoot-interval-one bullet-flood finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage2-shoot-interval-one-bullet-flood",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--retail", action="store_true")
    parser.add_argument("--retail-timeout-seconds", type=float, default=35.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not TARGET_SEED.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {TARGET_SEED}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=2,
        seed=7,
        action_file=LONG_ACTION_FILE,
        artifact_dir=baseline_dir,
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=1800,
        auto_shoot=True,
        continue_after_hit=True,
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    mutant = _target_mutant()
    result = run_case(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        stage=2,
        seed=7,
        action_file=LONG_ACTION_FILE,
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=1800,
        auto_shoot=True,
        continue_after_hit=True,
        timeout_seconds=15.0,
        campaign_dir=artifact_dir,
        seed_name=TARGET_SEED.name,
        mutant=mutant,
        case_index=1,
        baseline_trace=baseline_trace,
    )
    result_path = artifact_dir / result["case_name"] / "result.json"
    payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
    summary: dict[str, object] = {
        "finding": "semantic/stage2-shoot-interval-one-bullet-flood",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_mutant": {
            "name": TARGET_MUTANT_NAME,
            "path": {
                "sub_index": TARGET_MUTANT_PATH[0],
                "instruction_index": TARGET_MUTANT_PATH[1],
            },
            "payload_sha256": TARGET_PAYLOAD_SHA256,
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "command": baseline_metadata["command"],
        },
        "headless": {
            "result": str(result_path.resolve()),
            "payload_path": str(payload_path.resolve()),
            "trace": result["trace"],
            "log": result["log"],
            "findings": result["findings"],
            "command": result["command"],
        },
    }

    if args.retail:
        retail_dir = artifact_dir / "retail"
        command = [
            sys.executable,
            "-m",
            "danmakufuzz.retail.confirm_case",
            "--result",
            str(result_path.resolve()),
            "--artifact-dir",
            str(retail_dir.resolve()),
            "--practice-stage",
            "2",
            "--difficulty",
            "3",
            "--timeout-seconds",
            str(args.retail_timeout_seconds),
        ]
        subprocess.run(command, check=True)
        report_path = retail_dir / "report.json"
        summary["retail"] = {
            "artifact_dir": str(retail_dir.resolve()),
            "report": str(report_path.resolve()),
            "command": command,
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
