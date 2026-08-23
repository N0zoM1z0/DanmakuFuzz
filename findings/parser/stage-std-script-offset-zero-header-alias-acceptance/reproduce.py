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


TARGET_MUTANT_NAME = "script-offset-zero"
EXPECTED_BASELINE_SCRIPT_OFFSET = 12696
EXPECTED_BASELINE_SCRIPT_INSTRUCTIONS = 1
EXPECTED_BASELINE_SCRIPT_STOP_REASON = "size-overrun@0x31a4:17505"
EXPECTED_MUTANT_SCRIPT_OFFSET = 0
EXPECTED_MUTANT_SCRIPT_INSTRUCTIONS = 0
EXPECTED_MUTANT_SCRIPT_STOP_REASON = "size-too-small@0x0:0"
EXPECTED_OBJECT_COUNT = 13
EXPECTED_QUAD_COUNT = 343


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the stage .std script-offset-zero header-alias acceptance finding."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", type=str, default=DEFAULT_ENTRY)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-stage-std-script-offset-zero-header-alias-acceptance",
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

    seed_payload = archive_path.read_bytes()
    from danmakufuzz.corpus.pbg3 import Pbg3Archive

    archive = Pbg3Archive.from_bytes(seed_payload)
    stage_payload = archive.extract(args.entry)
    baseline = parse_stage_std(stage_payload, max_script_instructions=args.max_script_instructions)
    if baseline["script_offset"] != EXPECTED_BASELINE_SCRIPT_OFFSET:
        raise RuntimeError(
            f"baseline script_offset drifted: expected {EXPECTED_BASELINE_SCRIPT_OFFSET}, got {baseline['script_offset']}"
        )
    if baseline["script_instructions"] != EXPECTED_BASELINE_SCRIPT_INSTRUCTIONS:
        raise RuntimeError(
            "baseline script_instructions drifted: "
            f"expected {EXPECTED_BASELINE_SCRIPT_INSTRUCTIONS}, got {baseline['script_instructions']}"
        )
    if baseline["script_stop_reason"] != EXPECTED_BASELINE_SCRIPT_STOP_REASON:
        raise RuntimeError(
            "baseline script_stop_reason drifted: "
            f"expected {EXPECTED_BASELINE_SCRIPT_STOP_REASON}, got {baseline['script_stop_reason']}"
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
    if parsed["script_offset"] != EXPECTED_MUTANT_SCRIPT_OFFSET:
        raise RuntimeError(
            f"mutant script_offset drifted: expected {EXPECTED_MUTANT_SCRIPT_OFFSET}, got {parsed['script_offset']}"
        )
    if parsed["script_instructions"] != EXPECTED_MUTANT_SCRIPT_INSTRUCTIONS:
        raise RuntimeError(
            "mutant script_instructions drifted: "
            f"expected {EXPECTED_MUTANT_SCRIPT_INSTRUCTIONS}, got {parsed['script_instructions']}"
        )
    if parsed["script_stop_reason"] != EXPECTED_MUTANT_SCRIPT_STOP_REASON:
        raise RuntimeError(
            "mutant script_stop_reason drifted: "
            f"expected {EXPECTED_MUTANT_SCRIPT_STOP_REASON}, got {parsed['script_stop_reason']}"
        )

    objects = parsed.get("objects")
    if not isinstance(objects, list):
        raise RuntimeError(f"parsed objects shape drifted: {parsed}")
    if len(objects) != EXPECTED_OBJECT_COUNT:
        raise RuntimeError(f"object count drifted: expected {EXPECTED_OBJECT_COUNT}, got {len(objects)}")
    quad_count = int(parsed["quad_count_walked"])
    if quad_count != EXPECTED_QUAD_COUNT:
        raise RuntimeError(f"quad_count_walked drifted: expected {EXPECTED_QUAD_COUNT}, got {quad_count}")

    changed_fields = evaluation.get("changed_fields")
    if changed_fields != ["script_offset", "script_instructions", "script_stop_reason"]:
        raise RuntimeError(f"changed_fields drifted: {changed_fields}")

    summary = {
        "finding": "parser/stage-std-script-offset-zero-header-alias-acceptance",
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
