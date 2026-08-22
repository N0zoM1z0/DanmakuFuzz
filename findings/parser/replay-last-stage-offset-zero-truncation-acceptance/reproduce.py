from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.parser.replay import synthetic_replay_seed, validate_replay
from danmakufuzz.parser.replay_campaign import evaluate_replay_payload
from danmakufuzz.parser.replay_mutants import generate_replay_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "last-stage-offset-zero"
EXPECTED_BASELINE_STAGE_OFFSETS = [80, 84, 89, 0, 0, 0, 0]
EXPECTED_MUTATED_STAGE_OFFSETS = [80, 84, 0, 0, 0, 0, 0]
EXPECTED_DECODED_SIZE = 95


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the TH06 replay last-stage-offset-zero truncation-acceptance finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-replay-last-stage-offset-zero-truncation-acceptance",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    seed_payload = synthetic_replay_seed()
    baseline = {
        "input": "synthetic:th06-minimal-replay",
        **validate_replay(seed_payload),
    }
    if baseline["stage_offsets"] != EXPECTED_BASELINE_STAGE_OFFSETS:
        raise RuntimeError(
            f"baseline stage offsets drifted: expected {EXPECTED_BASELINE_STAGE_OFFSETS}, got {baseline['stage_offsets']}"
        )

    mutants = generate_replay_mutants(seed_payload)
    mutant = next((candidate for candidate in mutants if candidate.name == TARGET_MUTANT_NAME), None)
    if mutant is None:
        raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME}")

    payload_path = artifact_dir / "input.rpy"
    payload_path.write_bytes(mutant.payload)

    evaluation = evaluate_replay_payload(mutant.payload, baseline)
    if evaluation.get("classification") != "accepted":
        raise RuntimeError(f"target mutant no longer accepted: {evaluation}")
    if bool(evaluation.get("equivalent_to_baseline")):
        raise RuntimeError(f"target mutant unexpectedly became baseline-equivalent: {evaluation}")

    changed_fields = evaluation.get("changed_fields")
    if changed_fields != ["stage_offsets"]:
        raise RuntimeError(f"changed fields drifted: expected ['stage_offsets'], got {changed_fields}")

    parsed = validate_replay(mutant.payload)
    if parsed["stage_offsets"] != EXPECTED_MUTATED_STAGE_OFFSETS:
        raise RuntimeError(
            f"mutated stage offsets drifted: expected {EXPECTED_MUTATED_STAGE_OFFSETS}, got {parsed['stage_offsets']}"
        )
    if parsed["decoded_size"] != EXPECTED_DECODED_SIZE:
        raise RuntimeError(
            f"decoded size drifted: expected {EXPECTED_DECODED_SIZE}, got {parsed['decoded_size']}"
        )

    summary = {
        "finding": "parser/replay-last-stage-offset-zero-truncation-acceptance",
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": mutant.sha256,
        "baseline": baseline,
        "evaluation": evaluation,
        "parsed": parsed,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
