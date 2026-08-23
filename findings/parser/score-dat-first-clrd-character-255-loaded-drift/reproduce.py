from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.parser.score_dat import DEFAULT_SCORE_PATH, summarize_score_dat
from danmakufuzz.parser.score_dat_campaign import evaluate_score_dat_payload
from danmakufuzz.parser.score_dat_mutants import generate_score_dat_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "first-clrd-character-255"
EXPECTED_PAYLOAD_SHA256 = "15086860bdb29246bd7469c7c3883efe327741a0b7843a44c27f541cc32f3f30"
EXPECTED_BASELINE_RECORD_COUNT = 74
EXPECTED_BASELINE_VALID_CLRD = 4
EXPECTED_MUTANT_VALID_CLRD = 3
EXPECTED_MUTANT_INVALID_CLRD = 1
EXPECTED_CHANGED_FIELDS = ["valid_clrd_records", "invalid_clrd_records"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the score.dat first-clrd-character-255 loaded-drift finding."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_SCORE_PATH)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-score-dat-first-clrd-character-255-loaded-drift",
    )
    parser.add_argument("--max-records", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing score.dat seed: {input_path}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    seed_payload = input_path.read_bytes()
    baseline = summarize_score_dat(seed_payload, max_records=args.max_records)
    if baseline["classification"] != "loaded":
        raise RuntimeError(f"baseline stopped being loaded: {baseline}")
    if int(baseline["record_count"]) != EXPECTED_BASELINE_RECORD_COUNT:
        raise RuntimeError(
            f"baseline record_count drifted: expected {EXPECTED_BASELINE_RECORD_COUNT}, got {baseline['record_count']}"
        )
    if int(baseline["valid_clrd_records"]) != EXPECTED_BASELINE_VALID_CLRD:
        raise RuntimeError(
            f"baseline valid_clrd_records drifted: expected {EXPECTED_BASELINE_VALID_CLRD}, got {baseline['valid_clrd_records']}"
        )

    mutant = next(
        (candidate for candidate in generate_score_dat_mutants(seed_payload) if candidate.name == TARGET_MUTANT_NAME),
        None,
    )
    if mutant is None:
        raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME}")
    if mutant.sha256 != EXPECTED_PAYLOAD_SHA256:
        raise RuntimeError(
            f"mutant payload sha drifted: expected {EXPECTED_PAYLOAD_SHA256}, got {mutant.sha256}"
        )

    payload_path = artifact_dir / "score.dat"
    payload_path.write_bytes(mutant.payload)

    evaluation = evaluate_score_dat_payload(
        mutant.payload,
        {"input": str(input_path), **baseline},
        max_records=args.max_records,
    )
    if evaluation["classification"] != "loaded":
        raise RuntimeError(f"mutant stopped being loaded: {evaluation}")
    if not bool(evaluation["interesting"]):
        raise RuntimeError(f"mutant stopped being interesting: {evaluation}")
    if bool(evaluation["equivalent_to_baseline"]):
        raise RuntimeError(f"mutant unexpectedly became equivalent: {evaluation}")
    if evaluation["changed_fields"] != EXPECTED_CHANGED_FIELDS:
        raise RuntimeError(f"changed_fields drifted: {evaluation['changed_fields']}")
    if int(evaluation["valid_clrd_records"]) != EXPECTED_MUTANT_VALID_CLRD:
        raise RuntimeError(
            "mutant valid_clrd_records drifted: "
            f"expected {EXPECTED_MUTANT_VALID_CLRD}, got {evaluation['valid_clrd_records']}"
        )
    if int(evaluation["invalid_clrd_records"]) != EXPECTED_MUTANT_INVALID_CLRD:
        raise RuntimeError(
            "mutant invalid_clrd_records drifted: "
            f"expected {EXPECTED_MUTANT_INVALID_CLRD}, got {evaluation['invalid_clrd_records']}"
        )

    parsed = summarize_score_dat(mutant.payload, max_records=args.max_records)
    if int(parsed["checksum"]) != int(parsed["expected_checksum"]):
        raise RuntimeError(
            f"mutant checksum no longer preserved: {parsed['checksum']} != {parsed['expected_checksum']}"
        )

    summary = {
        "finding": "parser/score-dat-first-clrd-character-255-loaded-drift",
        "input": str(input_path),
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
