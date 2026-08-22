from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive, sha256_bytes
from danmakufuzz.parser.pbg3_campaign import DEFAULT_ARCHIVE, evaluate_pbg3_payload
from danmakufuzz.parser.pbg3_mutants import generate_pbg3_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "entry-count-one"
EXPECTED_ENTRY_COUNT = 1
EXPECTED_MISSING_ENTRY_COUNT = 130
EXPECTED_FIRST_FILENAME = "stg1bg.anm"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the PBG3 entry-count-one truncation-acceptance finding."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-pbg3-entry-count-one-truncation-acceptance",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing retail archive seed: {archive_path}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    seed_payload = archive_path.read_bytes()
    baseline_archive = Pbg3Archive.from_bytes(seed_payload)
    baseline_hashes = {
        entry.filename: sha256_bytes(baseline_archive.extract_entry(entry))
        for entry in baseline_archive.entries
    }
    if len(baseline_archive.entries) != 131:
        raise RuntimeError(f"baseline entry count drifted: expected 131, got {len(baseline_archive.entries)}")

    mutants = generate_pbg3_mutants(seed_payload)
    mutant = next((candidate for candidate in mutants if candidate.name == TARGET_MUTANT_NAME), None)
    if mutant is None:
        raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME}")

    payload_path = artifact_dir / "input.pbg3"
    payload_path.write_bytes(mutant.payload)

    evaluation = evaluate_pbg3_payload(mutant.payload, baseline_hashes)
    if evaluation.get("classification") != "accepted":
        raise RuntimeError(f"target mutant no longer accepted: {evaluation}")
    if bool(evaluation.get("equivalent_to_baseline")):
        raise RuntimeError(f"target mutant unexpectedly became equivalent: {evaluation}")

    parsed_archive = Pbg3Archive.from_bytes(mutant.payload)
    if len(parsed_archive.entries) != EXPECTED_ENTRY_COUNT:
        raise RuntimeError(
            f"parsed entry count drifted: expected {EXPECTED_ENTRY_COUNT}, got {len(parsed_archive.entries)}"
        )
    first_entry = parsed_archive.entries[0]
    if first_entry.filename != EXPECTED_FIRST_FILENAME:
        raise RuntimeError(
            f"first parsed filename drifted: expected {EXPECTED_FIRST_FILENAME}, got {first_entry.filename}"
        )
    first_payload = parsed_archive.extract_entry(first_entry)
    first_payload_sha256 = sha256_bytes(first_payload)
    baseline_first_sha256 = baseline_hashes[EXPECTED_FIRST_FILENAME]
    if first_payload_sha256 != baseline_first_sha256:
        raise RuntimeError(
            f"first entry payload drifted: expected {baseline_first_sha256}, got {first_payload_sha256}"
        )

    missing_entries_raw = evaluation.get("missing_entries")
    if not isinstance(missing_entries_raw, dict):
        raise RuntimeError(f"missing_entries shape drifted: {evaluation}")
    missing_count = int(missing_entries_raw.get("count", -1))
    if missing_count != EXPECTED_MISSING_ENTRY_COUNT:
        raise RuntimeError(
            f"missing entry count drifted: expected {EXPECTED_MISSING_ENTRY_COUNT}, got {missing_count}"
        )

    parsed_filenames_raw = evaluation.get("parsed_filenames")
    if not isinstance(parsed_filenames_raw, dict):
        raise RuntimeError(f"parsed_filenames shape drifted: {evaluation}")

    summary = {
        "finding": "parser/pbg3-entry-count-one-truncation-acceptance",
        "seed_archive": str(archive_path),
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": mutant.sha256,
        "baseline": {
            "entry_count": len(baseline_archive.entries),
            "first_filename": baseline_archive.entries[0].filename,
            "first_payload_sha256": baseline_first_sha256,
        },
        "evaluation": evaluation,
        "parsed_archive": {
            "entry_count": len(parsed_archive.entries),
            "filenames": [entry.filename for entry in parsed_archive.entries],
            "first_payload_sha256": first_payload_sha256,
        },
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
