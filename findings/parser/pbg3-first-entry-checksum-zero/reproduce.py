from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive, sha256_bytes
from danmakufuzz.parser.pbg3_campaign import DEFAULT_ARCHIVE, evaluate_pbg3_payload
from danmakufuzz.parser.pbg3_mutants import generate_pbg3_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_MUTANT_NAME = "first-entry-checksum-zero"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce the PBG3 first-entry-checksum-zero finding.")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-pbg3-first-entry-checksum-zero",
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
    archive = Pbg3Archive.from_bytes(seed_payload)
    baseline_hashes = {
        entry.filename: sha256_bytes(archive.extract_entry(entry))
        for entry in archive.entries
    }
    mutants = generate_pbg3_mutants(seed_payload)
    mutant = next((candidate for candidate in mutants if candidate.name == TARGET_MUTANT_NAME), None)
    if mutant is None:
        raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME}")

    payload_path = artifact_dir / "input.pbg3"
    payload_path.write_bytes(mutant.payload)
    evaluation = evaluate_pbg3_payload(mutant.payload, baseline_hashes)
    summary = {
        "finding": "parser/pbg3-first-entry-checksum-zero",
        "seed_archive": str(archive_path),
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": mutant.sha256,
        "evaluation": evaluation,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
