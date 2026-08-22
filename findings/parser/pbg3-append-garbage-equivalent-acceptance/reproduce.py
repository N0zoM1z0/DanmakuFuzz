from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive, sha256_bytes
from danmakufuzz.parser.pbg3_campaign import DEFAULT_ARCHIVE, evaluate_pbg3_payload
from danmakufuzz.parser.pbg3_mutants import generate_pbg3_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "append-garbage-256"
EXPECTED_BASELINE_ENTRY_COUNT = 131
EXPECTED_GARBAGE_BYTES = 256
EXPECTED_PAYLOAD_SHA256 = "e47628ac66bb8d157387bdcd07f2143d9688d74e9b389ebee030a5f526f35e2c"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the PBG3 append-garbage equivalent-acceptance finding."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-pbg3-append-garbage-equivalent-acceptance",
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
    if len(baseline_archive.entries) != EXPECTED_BASELINE_ENTRY_COUNT:
        raise RuntimeError(
            f"baseline entry count drifted: expected {EXPECTED_BASELINE_ENTRY_COUNT}, "
            f"got {len(baseline_archive.entries)}"
        )
    baseline_hashes = {
        entry.filename: sha256_bytes(baseline_archive.extract_entry(entry))
        for entry in baseline_archive.entries
    }

    mutants = generate_pbg3_mutants(seed_payload)
    mutant = next((candidate for candidate in mutants if candidate.name == TARGET_MUTANT_NAME), None)
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
        raise RuntimeError(f"target mutant no longer accepted: {evaluation}")
    if not bool(evaluation.get("interesting")):
        raise RuntimeError(f"target mutant no longer marked interesting: {evaluation}")
    if not bool(evaluation.get("equivalent_to_baseline")):
        raise RuntimeError(f"target mutant no longer equivalent to baseline: {evaluation}")

    parsed_archive = Pbg3Archive.from_bytes(mutant.payload)
    if len(parsed_archive.entries) != EXPECTED_BASELINE_ENTRY_COUNT:
        raise RuntimeError(
            f"parsed entry count drifted: expected {EXPECTED_BASELINE_ENTRY_COUNT}, "
            f"got {len(parsed_archive.entries)}"
        )

    parsed_hashes = {
        entry.filename: sha256_bytes(parsed_archive.extract_entry(entry))
        for entry in parsed_archive.entries
    }
    if parsed_hashes != baseline_hashes:
        raise RuntimeError("parsed payload hashes drifted from the retail baseline")

    trailing_garbage = mutant.payload[len(seed_payload):]
    if len(trailing_garbage) != EXPECTED_GARBAGE_BYTES:
        raise RuntimeError(
            f"trailing garbage length drifted: expected {EXPECTED_GARBAGE_BYTES}, got {len(trailing_garbage)}"
        )
    if trailing_garbage != b"\xAA" * EXPECTED_GARBAGE_BYTES:
        raise RuntimeError("trailing garbage bytes drifted from the expected 0xAA pattern")

    summary = {
        "finding": "parser/pbg3-append-garbage-equivalent-acceptance",
        "seed_archive": str(archive_path),
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": mutant.sha256,
        "baseline": {
            "size": len(seed_payload),
            "entry_count": len(baseline_archive.entries),
            "archive_sha256": sha256_bytes(seed_payload),
        },
        "payload": {
            "size": len(mutant.payload),
            "extra_bytes": len(trailing_garbage),
            "extra_pattern_hex": trailing_garbage[:8].hex(),
        },
        "evaluation": evaluation,
        "parsed_archive": {
            "entry_count": len(parsed_archive.entries),
            "filenames_match_baseline": [entry.filename for entry in parsed_archive.entries]
            == [entry.filename for entry in baseline_archive.entries],
        },
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
