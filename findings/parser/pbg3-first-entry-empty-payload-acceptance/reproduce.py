from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive, sha256_bytes
from danmakufuzz.parser.pbg3_campaign import DEFAULT_ARCHIVE, evaluate_pbg3_payload
from danmakufuzz.parser.pbg3_mutants import generate_pbg3_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "first-entry-empty-payload"
EXPECTED_PAYLOAD_SHA256 = "83a849bf284c6870ce0472c99247b3ae14db6e7dd72ea11cf93f05c8579516ec"
EXPECTED_BASELINE_ARCHIVE_SHA256 = "0f834a35aef2d73b05cffecc830c017dacbcc6f11b9a0611a9da2f3970a112e7"
EXPECTED_ENTRY_COUNT = 131
EXPECTED_FIRST_FILENAME = "stg1bg.anm"
EXPECTED_SECOND_FILENAME = "stg1bg.png"
EXPECTED_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the PBG3 first-entry-empty-payload acceptance finding."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-pbg3-first-entry-empty-payload-acceptance",
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
    if evaluation.get("classification") != "accepted":
        raise RuntimeError(f"target mutant classification drifted: {evaluation}")
    if not bool(evaluation.get("interesting")):
        raise RuntimeError(f"target mutant no longer marked interesting: {evaluation}")
    if bool(evaluation.get("equivalent_to_baseline")):
        raise RuntimeError(f"target mutant unexpectedly became equivalent: {evaluation}")

    missing_entries = evaluation.get("missing_entries")
    extra_entries = evaluation.get("extra_entries")
    changed_entries = evaluation.get("changed_entries")
    changed_entry_sizes = evaluation.get("changed_entry_sizes")
    if not isinstance(missing_entries, dict) or int(missing_entries.get("count", -1)) != 0:
        raise RuntimeError(f"missing_entries drifted: {evaluation}")
    if not isinstance(extra_entries, dict) or int(extra_entries.get("count", -1)) != 0:
        raise RuntimeError(f"extra_entries drifted: {evaluation}")
    if not isinstance(changed_entries, dict) or int(changed_entries.get("count", -1)) != 1:
        raise RuntimeError(f"changed_entries drifted: {evaluation}")
    if changed_entries.get("sample") != [EXPECTED_FIRST_FILENAME]:
        raise RuntimeError(f"changed entry sample drifted: {evaluation}")
    if not isinstance(changed_entry_sizes, dict) or int(changed_entry_sizes.get(EXPECTED_FIRST_FILENAME, -1)) != 0:
        raise RuntimeError(f"changed_entry_sizes drifted: {evaluation}")

    parsed_archive = Pbg3Archive.from_bytes(mutant.payload)
    if len(parsed_archive.entries) != EXPECTED_ENTRY_COUNT:
        raise RuntimeError(
            f"parsed entry count drifted: expected {EXPECTED_ENTRY_COUNT}, got {len(parsed_archive.entries)}"
        )
    first_entry = parsed_archive.entries[0]
    second_entry = parsed_archive.entries[1]
    if first_entry.filename != EXPECTED_FIRST_FILENAME:
        raise RuntimeError(
            f"mutant first entry drifted: expected {EXPECTED_FIRST_FILENAME}, got {first_entry.filename}"
        )
    if second_entry.filename != EXPECTED_SECOND_FILENAME:
        raise RuntimeError(
            f"mutant second entry drifted: expected {EXPECTED_SECOND_FILENAME}, got {second_entry.filename}"
        )

    first_payload = parsed_archive.extract_entry(first_entry)
    if len(first_payload) != 0:
        raise RuntimeError(f"mutant first payload size drifted: expected 0, got {len(first_payload)}")
    first_payload_sha256 = sha256_bytes(first_payload)
    if first_payload_sha256 != EXPECTED_EMPTY_SHA256:
        raise RuntimeError(
            f"mutant first payload sha256 drifted: expected {EXPECTED_EMPTY_SHA256}, got {first_payload_sha256}"
        )

    second_payload_sha256 = sha256_bytes(parsed_archive.extract_entry(second_entry))
    if second_payload_sha256 != baseline_hashes[EXPECTED_SECOND_FILENAME]:
        raise RuntimeError(
            f"mutant second payload drifted: expected {baseline_hashes[EXPECTED_SECOND_FILENAME]}, "
            f"got {second_payload_sha256}"
        )

    parsed_hashes = {
        entry.filename: sha256_bytes(parsed_archive.extract_entry(entry))
        for entry in parsed_archive.entries
    }
    changed = [name for name, digest in parsed_hashes.items() if baseline_hashes.get(name) != digest]
    if changed != [EXPECTED_FIRST_FILENAME]:
        raise RuntimeError(f"changed payload set drifted: expected [{EXPECTED_FIRST_FILENAME}], got {changed}")

    summary = {
        "finding": "parser/pbg3-first-entry-empty-payload-acceptance",
        "seed_archive": str(archive_path),
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": mutant.sha256,
        "baseline": {
            "archive_sha256": EXPECTED_BASELINE_ARCHIVE_SHA256,
            "entry_count": len(baseline_archive.entries),
            "first_entry": {
                "filename": first_entry.filename,
                "baseline_sha256": baseline_hashes[EXPECTED_FIRST_FILENAME],
            },
        },
        "evaluation": evaluation,
        "parsed_archive": {
            "entry_count": len(parsed_archive.entries),
            "first_entry": {
                "filename": first_entry.filename,
                "size": len(first_payload),
                "sha256": first_payload_sha256,
            },
            "second_entry": {
                "filename": second_entry.filename,
                "sha256_matches_baseline": second_payload_sha256 == baseline_hashes[EXPECTED_SECOND_FILENAME],
            },
            "changed_entries": changed,
        },
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
