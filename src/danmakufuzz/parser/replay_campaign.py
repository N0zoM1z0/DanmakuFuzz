from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ..repo import ARTIFACTS_DIR, ensure_directory
from .replay import synthetic_replay_seed, validate_replay
from .replay_mutants import ReplayMutant, generate_replay_mutants


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-replay" / stamp


def _baseline_summary(seed_payload: bytes, input_label: str) -> dict[str, object]:
    summary = validate_replay(seed_payload)
    return {
        "input": input_label,
        **summary,
    }


def evaluate_replay_payload(payload: bytes, baseline_summary: dict[str, object]) -> dict[str, object]:
    try:
        parsed = validate_replay(payload)
    except ValueError as exc:
        return {
            "classification": "parse-error",
            "interesting": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    tracked_fields = (
        "version",
        "difficulty",
        "shottype_chara",
        "score",
        "name",
        "date",
        "stage_offsets",
        "decoded_size",
    )
    changed_fields = [
        field
        for field in tracked_fields
        if parsed.get(field) != baseline_summary.get(field)
    ]
    return {
        "classification": "accepted",
        "interesting": bool(changed_fields),
        **parsed,
        "equivalent_to_baseline": not changed_fields,
        "changed_fields": changed_fields,
    }


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: ReplayMutant,
    *,
    case_index: int,
    artifact_dir: Path,
    baseline_summary: dict[str, object],
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    input_path = case_dir / "input.rpy"
    input_path.write_bytes(mutant.payload)
    evaluation = evaluate_replay_payload(mutant.payload, baseline_summary)
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
    parser = argparse.ArgumentParser(
        description="Run a lightweight TH06 replay mutation campaign over one replay seed."
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.input is not None:
        input_path = args.input.resolve()
        if not input_path.is_file():
            raise FileNotFoundError(f"missing replay seed: {input_path}")
        seed_payload = input_path.read_bytes()
        input_label = str(input_path)
    else:
        seed_payload = synthetic_replay_seed()
        input_label = "synthetic:th06-minimal-replay"

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    seed_path = artifact_dir / "seed.rpy"
    seed_path.write_bytes(seed_payload)

    baseline = _baseline_summary(seed_payload, input_label)
    (artifact_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    mutants = generate_replay_mutants(seed_payload)
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
            )
            classification_counts[str(result["classification"])] += 1
            interesting_cases += int(bool(result["interesting"]))
            summary_handle.write(json.dumps(result) + "\n")
            print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-replay-campaign-v1",
        "input": input_label,
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
