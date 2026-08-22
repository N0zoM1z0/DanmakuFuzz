from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive, Pbg3Error, sha256_bytes
from danmakufuzz.parser.pbg3_campaign import DEFAULT_ARCHIVE, evaluate_pbg3_payload
from danmakufuzz.parser.pbg3_mutants import generate_pbg3_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANTS = (
    {
        "name": "first-entry-size-zero",
        "source": "table",
        "payload_sha256": "777f23c1b87d9573ff6c0342eff29c9604520bd55ba04814b984dc5d241b597a",
        "expected_uncompressed_size": 0,
    },
    {
        "name": "first-entry-bitflip",
        "source": "data",
        "payload_sha256": "831c7804f94c06c2abd7ea33e79df9b65a7517e395a4b12388a23adcb8969242",
        "expected_uncompressed_size": 2100,
    },
    {
        "name": "first-entry-bitflip-resummed",
        "source": "data",
        "payload_sha256": "e6e771c27b887f41a80aeea7dff24f5ab4cf33fbb463968b89ffed237bd9a775",
        "expected_uncompressed_size": 2100,
    },
)
EXPECTED_ENTRY_COUNT = 131
EXPECTED_FIRST_FILENAME = "stg1bg.anm"
EXPECTED_SHARED_ERROR_TYPE = "Pbg3Error"
EXPECTED_SHARED_ERROR_MESSAGE = "PBG3 entry expands past its declared size: stg1bg.anm"
EXPECTED_BASELINE_ARCHIVE_SHA256 = "0f834a35aef2d73b05cffecc830c017dacbcc6f11b9a0611a9da2f3970a112e7"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the PBG3 first-entry expand-past-size cross-family basin."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-pbg3-first-entry-expand-past-size-cross-family-basin",
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
    if len(baseline_archive.entries) != EXPECTED_ENTRY_COUNT:
        raise RuntimeError(
            f"baseline entry count drifted: expected {EXPECTED_ENTRY_COUNT}, got {len(baseline_archive.entries)}"
        )
    if sha256_bytes(seed_payload) != EXPECTED_BASELINE_ARCHIVE_SHA256:
        raise RuntimeError(
            f"baseline archive sha256 drifted: expected {EXPECTED_BASELINE_ARCHIVE_SHA256}, "
            f"got {sha256_bytes(seed_payload)}"
        )
    first_baseline_entry = baseline_archive.entries[0]
    if first_baseline_entry.filename != EXPECTED_FIRST_FILENAME:
        raise RuntimeError(
            f"baseline first entry drifted: expected {EXPECTED_FIRST_FILENAME}, got {first_baseline_entry.filename}"
        )
    baseline_hashes = {
        entry.filename: sha256_bytes(baseline_archive.extract_entry(entry))
        for entry in baseline_archive.entries
    }

    mutants_by_name = {
        mutant.name: mutant
        for mutant in generate_pbg3_mutants(seed_payload)
    }

    cases: list[dict[str, object]] = []
    for target in TARGET_MUTANTS:
        mutant = mutants_by_name.get(str(target["name"]))
        if mutant is None:
            raise RuntimeError(f"missing target mutant {target['name']}")
        if mutant.sha256 != str(target["payload_sha256"]):
            raise RuntimeError(
                f"{target['name']} payload sha256 drifted: expected {target['payload_sha256']}, got {mutant.sha256}"
            )

        case_dir = artifact_dir / str(target["name"])
        ensure_directory(case_dir)
        payload_path = case_dir / "input.pbg3"
        payload_path.write_bytes(mutant.payload)

        evaluation = evaluate_pbg3_payload(mutant.payload, baseline_hashes)
        if evaluation.get("classification") != "extract-error":
            raise RuntimeError(f"{target['name']} classification drifted: {evaluation}")
        if not bool(evaluation.get("interesting")):
            raise RuntimeError(f"{target['name']} no longer marked interesting: {evaluation}")
        if evaluation.get("error_type") != EXPECTED_SHARED_ERROR_TYPE:
            raise RuntimeError(
                f"{target['name']} error type drifted: expected {EXPECTED_SHARED_ERROR_TYPE}, "
                f"got {evaluation.get('error_type')}"
            )
        if evaluation.get("error_message") != EXPECTED_SHARED_ERROR_MESSAGE:
            raise RuntimeError(
                f"{target['name']} error message drifted: expected {EXPECTED_SHARED_ERROR_MESSAGE}, "
                f"got {evaluation.get('error_message')}"
            )

        extracted_before_failure = evaluation.get("extracted_before_failure")
        if not isinstance(extracted_before_failure, dict) or int(extracted_before_failure.get("count", -1)) != 0:
            raise RuntimeError(f"{target['name']} extracted_before_failure drifted: {evaluation}")

        parsed_archive = Pbg3Archive.from_bytes(mutant.payload)
        if len(parsed_archive.entries) != EXPECTED_ENTRY_COUNT:
            raise RuntimeError(
                f"{target['name']} parsed entry count drifted: expected {EXPECTED_ENTRY_COUNT}, "
                f"got {len(parsed_archive.entries)}"
            )
        first_entry = parsed_archive.entries[0]
        if first_entry.filename != EXPECTED_FIRST_FILENAME:
            raise RuntimeError(
                f"{target['name']} first entry drifted: expected {EXPECTED_FIRST_FILENAME}, got {first_entry.filename}"
            )
        expected_uncompressed_size = int(target["expected_uncompressed_size"])
        if first_entry.uncompressed_size != expected_uncompressed_size:
            raise RuntimeError(
                f"{target['name']} first entry size drifted: expected {expected_uncompressed_size}, "
                f"got {first_entry.uncompressed_size}"
            )
        try:
            parsed_archive.extract_entry(first_entry)
        except Pbg3Error as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
        else:
            raise RuntimeError(f"{target['name']} unexpectedly extracted cleanly")
        if error_type != EXPECTED_SHARED_ERROR_TYPE or error_message != EXPECTED_SHARED_ERROR_MESSAGE:
            raise RuntimeError(
                f"{target['name']} direct extraction drifted: expected "
                f"({EXPECTED_SHARED_ERROR_TYPE}, {EXPECTED_SHARED_ERROR_MESSAGE}), got ({error_type}, {error_message})"
            )

        cases.append(
            {
                "name": target["name"],
                "source": target["source"],
                "payload_path": str(payload_path.resolve()),
                "payload_sha256": mutant.sha256,
                "first_entry": {
                    "filename": first_entry.filename,
                    "uncompressed_size": first_entry.uncompressed_size,
                },
                "evaluation": evaluation,
                "direct_extract_error": {
                    "error_type": error_type,
                    "error_message": error_message,
                },
            }
        )

    summary = {
        "finding": "parser/pbg3-first-entry-expand-past-size-cross-family-basin",
        "seed_archive": str(archive_path),
        "baseline": {
            "archive_sha256": EXPECTED_BASELINE_ARCHIVE_SHA256,
            "entry_count": len(baseline_archive.entries),
            "first_entry": {
                "filename": first_baseline_entry.filename,
                "uncompressed_size": first_baseline_entry.uncompressed_size,
            },
        },
        "shared_error": {
            "error_type": EXPECTED_SHARED_ERROR_TYPE,
            "error_message": EXPECTED_SHARED_ERROR_MESSAGE,
        },
        "cases": cases,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
