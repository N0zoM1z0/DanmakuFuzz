from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive, Pbg3Error, sha256_bytes
from danmakufuzz.parser.pbg3_campaign import DEFAULT_ARCHIVE, evaluate_pbg3_payload
from danmakufuzz.parser.pbg3_mutants import generate_pbg3_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "first-entry-offset-zero"
EXPECTED_PAYLOAD_SHA256 = "c38d15cc1a0d64fd48d3296f7fdfded13d87b6a6d4f019bcada7ea7b2d401cb0"
EXPECTED_BASELINE_ARCHIVE_SHA256 = "0f834a35aef2d73b05cffecc830c017dacbcc6f11b9a0611a9da2f3970a112e7"
EXPECTED_ENTRY_COUNT = 131
EXPECTED_FIRST_FILENAME = "stg1bg.anm"
EXPECTED_BASELINE_FIRST_DATA_OFFSET = 13
EXPECTED_MUTANT_FIRST_DATA_OFFSET = 0
EXPECTED_BASELINE_FIRST_CHECKSUM = 0x127C1
EXPECTED_FIRST_UNCOMPRESSED_SIZE = 2100
EXPECTED_ERROR_TYPE = "Pbg3Error"
EXPECTED_ERROR_MESSAGE = "PBG3 checksum mismatch for stg1bg.anm: 0x1cc != 0x127c1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the PBG3 first-entry-offset-zero alias checksum fault."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-pbg3-first-entry-offset-zero-alias-checksum-fault",
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
    if sha256_bytes(seed_payload) != EXPECTED_BASELINE_ARCHIVE_SHA256:
        raise RuntimeError(
            f"baseline archive sha256 drifted: expected {EXPECTED_BASELINE_ARCHIVE_SHA256}, "
            f"got {sha256_bytes(seed_payload)}"
        )
    baseline_archive = Pbg3Archive.from_bytes(seed_payload)
    if len(baseline_archive.entries) != EXPECTED_ENTRY_COUNT:
        raise RuntimeError(
            f"baseline entry count drifted: expected {EXPECTED_ENTRY_COUNT}, got {len(baseline_archive.entries)}"
        )
    first_baseline_entry = baseline_archive.entries[0]
    if first_baseline_entry.filename != EXPECTED_FIRST_FILENAME:
        raise RuntimeError(
            f"baseline first entry drifted: expected {EXPECTED_FIRST_FILENAME}, got {first_baseline_entry.filename}"
        )
    if first_baseline_entry.data_offset != EXPECTED_BASELINE_FIRST_DATA_OFFSET:
        raise RuntimeError(
            f"baseline first data offset drifted: expected {EXPECTED_BASELINE_FIRST_DATA_OFFSET}, "
            f"got {first_baseline_entry.data_offset}"
        )
    if first_baseline_entry.checksum != EXPECTED_BASELINE_FIRST_CHECKSUM:
        raise RuntimeError(
            f"baseline first checksum drifted: expected {EXPECTED_BASELINE_FIRST_CHECKSUM:#x}, "
            f"got {first_baseline_entry.checksum:#x}"
        )
    if first_baseline_entry.uncompressed_size != EXPECTED_FIRST_UNCOMPRESSED_SIZE:
        raise RuntimeError(
            f"baseline first entry size drifted: expected {EXPECTED_FIRST_UNCOMPRESSED_SIZE}, "
            f"got {first_baseline_entry.uncompressed_size}"
        )
    baseline_hashes = {
        entry.filename: sha256_bytes(baseline_archive.extract_entry(entry))
        for entry in baseline_archive.entries
    }

    mutant = next(
        (candidate for candidate in generate_pbg3_mutants(seed_payload) if candidate.name == TARGET_MUTANT_NAME),
        None,
    )
    if mutant is None:
        raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME}")
    if mutant.sha256 != EXPECTED_PAYLOAD_SHA256:
        raise RuntimeError(
            f"payload sha256 drifted: expected {EXPECTED_PAYLOAD_SHA256}, got {mutant.sha256}"
        )

    payload_path = artifact_dir / "input.pbg3"
    payload_path.write_bytes(mutant.payload)

    evaluation = evaluate_pbg3_payload(mutant.payload, baseline_hashes)
    if evaluation.get("classification") != "extract-error":
        raise RuntimeError(f"target mutant classification drifted: {evaluation}")
    if not bool(evaluation.get("interesting")):
        raise RuntimeError(f"target mutant no longer marked interesting: {evaluation}")
    if evaluation.get("error_type") != EXPECTED_ERROR_TYPE:
        raise RuntimeError(
            f"error type drifted: expected {EXPECTED_ERROR_TYPE}, got {evaluation.get('error_type')}"
        )
    if evaluation.get("error_message") != EXPECTED_ERROR_MESSAGE:
        raise RuntimeError(
            f"error message drifted: expected {EXPECTED_ERROR_MESSAGE}, got {evaluation.get('error_message')}"
        )

    extracted_before_failure = evaluation.get("extracted_before_failure")
    if not isinstance(extracted_before_failure, dict) or int(extracted_before_failure.get("count", -1)) != 0:
        raise RuntimeError(f"extracted_before_failure drifted: {evaluation}")

    parsed_archive = Pbg3Archive.from_bytes(mutant.payload)
    if len(parsed_archive.entries) != EXPECTED_ENTRY_COUNT:
        raise RuntimeError(
            f"parsed entry count drifted: expected {EXPECTED_ENTRY_COUNT}, got {len(parsed_archive.entries)}"
        )
    first_entry = parsed_archive.entries[0]
    if first_entry.filename != EXPECTED_FIRST_FILENAME:
        raise RuntimeError(
            f"mutant first entry drifted: expected {EXPECTED_FIRST_FILENAME}, got {first_entry.filename}"
        )
    if first_entry.data_offset != EXPECTED_MUTANT_FIRST_DATA_OFFSET:
        raise RuntimeError(
            f"mutant first data offset drifted: expected {EXPECTED_MUTANT_FIRST_DATA_OFFSET}, "
            f"got {first_entry.data_offset}"
        )
    if first_entry.checksum != EXPECTED_BASELINE_FIRST_CHECKSUM:
        raise RuntimeError(
            f"mutant first checksum drifted: expected unchanged {EXPECTED_BASELINE_FIRST_CHECKSUM:#x}, "
            f"got {first_entry.checksum:#x}"
        )
    if first_entry.uncompressed_size != EXPECTED_FIRST_UNCOMPRESSED_SIZE:
        raise RuntimeError(
            f"mutant first entry size drifted: expected {EXPECTED_FIRST_UNCOMPRESSED_SIZE}, "
            f"got {first_entry.uncompressed_size}"
        )

    try:
        parsed_archive.extract_entry(first_entry)
    except Pbg3Error as exc:
        direct_error_type = type(exc).__name__
        direct_error_message = str(exc)
    else:
        raise RuntimeError("mutant unexpectedly extracted cleanly")
    if direct_error_type != EXPECTED_ERROR_TYPE or direct_error_message != EXPECTED_ERROR_MESSAGE:
        raise RuntimeError(
            f"direct extraction drifted: expected ({EXPECTED_ERROR_TYPE}, {EXPECTED_ERROR_MESSAGE}), "
            f"got ({direct_error_type}, {direct_error_message})"
        )

    summary = {
        "finding": "parser/pbg3-first-entry-offset-zero-alias-checksum-fault",
        "seed_archive": str(archive_path),
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": mutant.sha256,
        "baseline": {
            "archive_sha256": EXPECTED_BASELINE_ARCHIVE_SHA256,
            "entry_count": len(baseline_archive.entries),
            "first_entry": {
                "filename": first_baseline_entry.filename,
                "data_offset": first_baseline_entry.data_offset,
                "checksum": first_baseline_entry.checksum,
                "uncompressed_size": first_baseline_entry.uncompressed_size,
            },
        },
        "mutant": {
            "name": TARGET_MUTANT_NAME,
            "first_entry": {
                "filename": first_entry.filename,
                "data_offset": first_entry.data_offset,
                "checksum": first_entry.checksum,
                "uncompressed_size": first_entry.uncompressed_size,
            },
        },
        "evaluation": evaluation,
        "direct_extract_error": {
            "error_type": direct_error_type,
            "error_message": direct_error_message,
        },
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
