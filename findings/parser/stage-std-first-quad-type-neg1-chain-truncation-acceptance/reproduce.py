from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.parser.stage_std import parse_stage_std
from danmakufuzz.parser.stage_std_campaign import (
    DEFAULT_ARCHIVE,
    DEFAULT_ENTRY,
    evaluate_stage_std_payload,
)
from danmakufuzz.parser.stage_std_mutants import generate_stage_std_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "first-quad-type-neg1"
EXPECTED_BASELINE_OBJECT0_QUADS = 56
EXPECTED_BASELINE_QUAD_COUNT = 343
EXPECTED_MUTANT_OBJECT0_QUADS = 0
EXPECTED_MUTANT_QUAD_COUNT = 287
EXPECTED_OBJECT_COUNT = 13
EXPECTED_SCRIPT_INSTRUCTIONS = 1
EXPECTED_SCRIPT_STOP_REASON = "size-overrun@0x31a4:17505"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the stage .std first-quad-type-neg1 chain-truncation acceptance finding."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", type=str, default=DEFAULT_ENTRY)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-stage-std-first-quad-type-neg1-chain-truncation-acceptance",
    )
    parser.add_argument("--max-script-instructions", type=int, default=100000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing retail archive seed: {archive_path}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    from danmakufuzz.corpus.pbg3 import Pbg3Archive

    seed_payload = archive_path.read_bytes()
    archive = Pbg3Archive.from_bytes(seed_payload)
    stage_payload = archive.extract(args.entry)
    baseline = parse_stage_std(stage_payload, max_script_instructions=args.max_script_instructions)
    baseline_objects = baseline.get("objects")
    if not isinstance(baseline_objects, list) or len(baseline_objects) != EXPECTED_OBJECT_COUNT:
        raise RuntimeError(f"baseline object shape drifted: {baseline_objects!r}")
    if int(baseline["quad_count_walked"]) != EXPECTED_BASELINE_QUAD_COUNT:
        raise RuntimeError(
            f"baseline quad_count_walked drifted: expected {EXPECTED_BASELINE_QUAD_COUNT}, got {baseline['quad_count_walked']}"
        )
    if int(baseline_objects[0]["quad_count"]) != EXPECTED_BASELINE_OBJECT0_QUADS:
        raise RuntimeError(
            f"baseline object0 quad_count drifted: expected {EXPECTED_BASELINE_OBJECT0_QUADS}, got {baseline_objects[0]['quad_count']}"
        )
    if int(baseline["script_instructions"]) != EXPECTED_SCRIPT_INSTRUCTIONS:
        raise RuntimeError(
            f"baseline script_instructions drifted: expected {EXPECTED_SCRIPT_INSTRUCTIONS}, got {baseline['script_instructions']}"
        )
    if baseline["script_stop_reason"] != EXPECTED_SCRIPT_STOP_REASON:
        raise RuntimeError(
            f"baseline script_stop_reason drifted: expected {EXPECTED_SCRIPT_STOP_REASON}, got {baseline['script_stop_reason']}"
        )

    mutants = generate_stage_std_mutants(stage_payload)
    mutant = next((candidate for candidate in mutants if candidate.name == TARGET_MUTANT_NAME), None)
    if mutant is None:
        raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME}")

    payload_path = artifact_dir / "input.std"
    payload_path.write_bytes(mutant.payload)

    evaluation = evaluate_stage_std_payload(
        mutant.payload,
        baseline,
        max_script_instructions=args.max_script_instructions,
    )
    if evaluation.get("classification") != "accepted":
        raise RuntimeError(f"target mutant no longer accepted: {evaluation}")
    if not bool(evaluation.get("interesting")):
        raise RuntimeError(f"target mutant unexpectedly stopped being interesting: {evaluation}")
    if bool(evaluation.get("equivalent_to_baseline")):
        raise RuntimeError(f"target mutant unexpectedly became equivalent: {evaluation}")

    parsed = parse_stage_std(mutant.payload, max_script_instructions=args.max_script_instructions)
    parsed_objects = parsed.get("objects")
    if not isinstance(parsed_objects, list) or len(parsed_objects) != EXPECTED_OBJECT_COUNT:
        raise RuntimeError(f"mutant object shape drifted: {parsed_objects!r}")
    if int(parsed["quad_count_walked"]) != EXPECTED_MUTANT_QUAD_COUNT:
        raise RuntimeError(
            f"mutant quad_count_walked drifted: expected {EXPECTED_MUTANT_QUAD_COUNT}, got {parsed['quad_count_walked']}"
        )
    if int(parsed_objects[0]["quad_count"]) != EXPECTED_MUTANT_OBJECT0_QUADS:
        raise RuntimeError(
            f"mutant object0 quad_count drifted: expected {EXPECTED_MUTANT_OBJECT0_QUADS}, got {parsed_objects[0]['quad_count']}"
        )
    if int(parsed["script_instructions"]) != EXPECTED_SCRIPT_INSTRUCTIONS:
        raise RuntimeError(
            f"mutant script_instructions drifted: expected {EXPECTED_SCRIPT_INSTRUCTIONS}, got {parsed['script_instructions']}"
        )
    if parsed["script_stop_reason"] != EXPECTED_SCRIPT_STOP_REASON:
        raise RuntimeError(
            f"mutant script_stop_reason drifted: expected {EXPECTED_SCRIPT_STOP_REASON}, got {parsed['script_stop_reason']}"
        )

    changed_fields = evaluation.get("changed_fields")
    if changed_fields != ["quad_count_walked", "objects"]:
        raise RuntimeError(f"changed_fields drifted: {changed_fields}")

    summary = {
        "finding": "parser/stage-std-first-quad-type-neg1-chain-truncation-acceptance",
        "seed_archive": str(archive_path),
        "entry": args.entry,
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
