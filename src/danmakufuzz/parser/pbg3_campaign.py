from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ..corpus.pbg3 import Pbg3Archive, Pbg3Error, sha256_bytes
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .pbg3_mutants import Pbg3Mutant, generate_pbg3_mutants


DEFAULT_ARCHIVE = REFERENCE_DIR / "retail" / "game" / "th06" / "紅魔郷ST.DAT"


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-pbg3" / stamp


def _baseline_summary(seed_payload: bytes, archive_path: Path) -> dict[str, object]:
    archive = Pbg3Archive.from_bytes(seed_payload)
    entry_hashes = {
        entry.filename: sha256_bytes(archive.extract_entry(entry))
        for entry in archive.entries
    }
    return {
        "archive": str(archive_path.resolve()),
        "entry_count": len(archive.entries),
        "table_offset": archive.table_offset,
        "entry_hashes": entry_hashes,
    }


def _sample_strings(values: list[str], *, limit: int = 16) -> dict[str, object]:
    return {
        "count": len(values),
        "sample": values[:limit],
        "truncated": len(values) > limit,
    }


def evaluate_pbg3_payload(payload: bytes, baseline_hashes: dict[str, str]) -> dict[str, object]:
    try:
        archive = Pbg3Archive.from_bytes(payload)
    except (Pbg3Error, ValueError) as exc:
        return {
            "classification": "parse-error",
            "interesting": False,
            "evidence_level": "FORMAT_REJECTED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    extracted_hashes: dict[str, str] = {}
    extracted_sizes: dict[str, int] = {}
    try:
        for entry in archive.entries:
            extracted = archive.extract_entry(entry)
            extracted_hashes[entry.filename] = sha256_bytes(extracted)
            extracted_sizes[entry.filename] = len(extracted)
    except (Pbg3Error, ValueError) as exc:
        return {
            "classification": "extract-error",
            "interesting": True,
            "evidence_level": "MODEL_PARSER_ONLY",
            "observation_kind": "accepted-metadata-extraction-error",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "entry_count": len(archive.entries),
            "parsed_filenames": _sample_strings([entry.filename for entry in archive.entries]),
            "extracted_before_failure": _sample_strings(sorted(extracted_hashes)),
        }

    baseline_names = set(baseline_hashes)
    extracted_names = set(extracted_hashes)
    missing_entries = sorted(baseline_names - extracted_names)
    extra_entries = sorted(extracted_names - baseline_names)
    changed_entries = sorted(
        filename
        for filename, digest in extracted_hashes.items()
        if baseline_hashes.get(filename) != digest
    )
    equivalent = not missing_entries and not extra_entries and not changed_entries
    return {
        "classification": "accepted",
        "interesting": not equivalent,
        "evidence_level": "FORMAT_CHARACTERIZATION" if equivalent else "MODEL_PARSER_ONLY",
        "observation_kind": "format-equivalent-acceptance" if equivalent else "accepted-with-drift",
        "entry_count": len(archive.entries),
        "parsed_filenames": _sample_strings([entry.filename for entry in archive.entries]),
        "missing_entries": _sample_strings(missing_entries),
        "extra_entries": _sample_strings(extra_entries),
        "changed_entries": _sample_strings(changed_entries),
        "equivalent_to_baseline": equivalent,
        "changed_entry_sizes": {
            filename: extracted_sizes[filename]
            for filename in changed_entries[:16]
        },
    }


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: Pbg3Mutant,
    *,
    case_index: int,
    artifact_dir: Path,
    baseline_hashes: dict[str, str],
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    input_path = case_dir / "input.pbg3"
    input_path.write_bytes(mutant.payload)
    evaluation = evaluate_pbg3_payload(mutant.payload, baseline_hashes)
    result = {
        "case_name": case_name,
        "mutant_name": mutant.name,
        "source": mutant.source,
        "archive_path": str(input_path.resolve()),
        "payload_size": len(mutant.payload),
        "payload_sha256": mutant.sha256,
        **evaluation,
    }
    _write_case_result(case_dir, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a lightweight PBG3 parser mutation campaign over one retail archive seed.")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing archive seed: {archive_path}")
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    seed_payload = archive_path.read_bytes()
    baseline = _baseline_summary(seed_payload, archive_path)
    (artifact_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    mutants = generate_pbg3_mutants(seed_payload)
    if args.name_filter:
        mutants = [
            mutant
            for mutant in mutants
            if any(name_filter in mutant.name for name_filter in args.name_filter)
        ]
    if args.limit is not None:
        mutants = mutants[: args.limit]

    summary_path = artifact_dir / "summary.jsonl"
    classification_counts: Counter[str] = Counter()
    interesting_cases = 0
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, mutant in enumerate(mutants, start=1):
            result = _run_mutant(
                mutant,
                case_index=case_index,
                artifact_dir=artifact_dir,
                baseline_hashes=baseline["entry_hashes"],  # type: ignore[arg-type]
            )
            classification_counts[str(result["classification"])] += 1
            interesting_cases += int(bool(result["interesting"]))
            summary_handle.write(json.dumps(result) + "\n")
            print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-pbg3-campaign-v1",
        "archive": str(archive_path),
        "baseline": {
            "entry_count": baseline["entry_count"],
            "table_offset": baseline["table_offset"],
        },
        "mutants_generated": len(mutants),
        "interesting_cases": interesting_cases,
        "classification_counts": dict(sorted(classification_counts.items())),
        "summary": str(summary_path.resolve()),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
