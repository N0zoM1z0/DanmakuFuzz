from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ..repo import ARTIFACTS_DIR, ensure_directory
from .score_dat import DEFAULT_SCORE_PATH, summarize_score_dat
from .score_dat_mutants import ScoreDatMutant, generate_score_dat_mutants


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-score-dat" / stamp


def evaluate_score_dat_payload(payload: bytes, baseline_summary: dict[str, object], *, max_records: int) -> dict[str, object]:
    parsed = summarize_score_dat(payload, max_records=max_records)
    tracked_fields = (
        "classification",
        "fallback_reasons",
        "data_offset",
        "file_len",
        "first_th6k_offset",
        "record_count",
        "record_histogram",
        "valid_hscr_records",
        "invalid_hscr_records",
        "valid_catk_records",
        "invalid_catk_records",
        "valid_clrd_records",
        "invalid_clrd_records",
        "valid_pscr_records",
        "invalid_pscr_records",
        "walk_stop_reason",
    )
    changed_fields = [
        field
        for field in tracked_fields
        if parsed.get(field) != baseline_summary.get(field)
    ]
    equivalent = not changed_fields
    return {
        **parsed,
        "interesting": not equivalent,
        "equivalent_to_baseline": equivalent,
        "changed_fields": changed_fields,
    }


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: ScoreDatMutant,
    *,
    case_index: int,
    artifact_dir: Path,
    baseline_summary: dict[str, object],
    max_records: int,
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    input_path = case_dir / "score.dat"
    input_path.write_bytes(mutant.payload)
    evaluation = evaluate_score_dat_payload(
        mutant.payload,
        baseline_summary,
        max_records=max_records,
    )
    result = {
        "case_name": case_name,
        "mutant_name": mutant.name,
        "source": mutant.source,
        "input_path": str(input_path.resolve()),
        "payload_size": len(mutant.payload),
        "payload_sha256": mutant.sha256,
        **evaluation,
    }
    _write_case_result(case_dir, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a lightweight Touhou score.dat mutation campaign.")
    parser.add_argument("--input", type=Path, default=DEFAULT_SCORE_PATH)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--max-records", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing score.dat seed: {input_path}")

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    payload = input_path.read_bytes()
    seed_path = artifact_dir / input_path.name
    seed_path.write_bytes(payload)

    baseline = {"input": str(input_path), **summarize_score_dat(payload, max_records=args.max_records)}
    (artifact_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    mutants = generate_score_dat_mutants(payload)
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
                baseline_summary=baseline,
                max_records=args.max_records,
            )
            classification_counts[str(result["classification"])] += 1
            interesting_cases += int(bool(result["interesting"]))
            summary_handle.write(json.dumps(result) + "\n")
            print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-score-dat-campaign-v1",
        "input": str(input_path),
        "seed_path": str(seed_path.resolve()),
        "baseline": baseline,
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
