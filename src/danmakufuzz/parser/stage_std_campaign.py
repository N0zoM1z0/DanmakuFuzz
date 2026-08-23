from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .common import load_input_bytes
from .stage_std import parse_stage_std
from .stage_std_mutants import StageStdMutant, generate_stage_std_mutants


DEFAULT_ARCHIVE = REFERENCE_DIR / "retail" / "game" / "th06" / "紅魔郷ST.DAT"
DEFAULT_ENTRY = "stage1.std"


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-stage-std" / stamp


def _baseline_summary(seed_payload: bytes, source: str, *, max_script_instructions: int) -> dict[str, object]:
    return {
        "input": source,
        **parse_stage_std(seed_payload, max_script_instructions=max_script_instructions),
    }


def _tracked_object_digest(summary: dict[str, object]) -> dict[str, object]:
    objects = summary.get("objects")
    if not isinstance(objects, list):
        return {"count": 0, "quad_counts": []}
    quad_counts: list[int | None] = []
    object_ids: list[int | None] = []
    z_levels: list[int | None] = []
    for entry in objects:
        if not isinstance(entry, dict):
            quad_counts.append(None)
            object_ids.append(None)
            z_levels.append(None)
            continue
        quad_counts.append(entry.get("quad_count") if isinstance(entry.get("quad_count"), int) else None)
        object_ids.append(entry.get("id") if isinstance(entry.get("id"), int) else None)
        z_levels.append(entry.get("z_level") if isinstance(entry.get("z_level"), int) else None)
    return {
        "count": len(objects),
        "quad_counts": quad_counts,
        "object_ids": object_ids,
        "z_levels": z_levels,
    }


def evaluate_stage_std_payload(payload: bytes, baseline_summary: dict[str, object], *, max_script_instructions: int) -> dict[str, object]:
    try:
        parsed = parse_stage_std(payload, max_script_instructions=max_script_instructions)
    except ValueError as exc:
        return {
            "classification": "parse-error",
            "interesting": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    tracked_fields = (
        "nb_objects",
        "nb_faces",
        "faces_offset",
        "script_offset",
        "quad_count_walked",
        "script_instructions",
        "script_stop_reason",
        "stage_name",
        "song_paths",
    )
    changed_fields = [
        field
        for field in tracked_fields
        if parsed.get(field) != baseline_summary.get(field)
    ]
    parsed_object_digest = _tracked_object_digest(parsed)
    baseline_object_digest = _tracked_object_digest(baseline_summary)
    if parsed_object_digest != baseline_object_digest:
        changed_fields.append("objects")
    equivalent = not changed_fields
    return {
        "classification": "accepted",
        "interesting": not equivalent,
        **parsed,
        "equivalent_to_baseline": equivalent,
        "changed_fields": changed_fields,
        "object_digest": parsed_object_digest,
    }


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: StageStdMutant,
    *,
    case_index: int,
    artifact_dir: Path,
    baseline_summary: dict[str, object],
    max_script_instructions: int,
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    input_path = case_dir / "input.std"
    input_path.write_bytes(mutant.payload)
    evaluation = evaluate_stage_std_payload(
        mutant.payload,
        baseline_summary,
        max_script_instructions=max_script_instructions,
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
    parser = argparse.ArgumentParser(
        description="Run a lightweight TH06 stage .std mutation campaign over one retail stage seed."
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", type=str, default=DEFAULT_ENTRY)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--max-script-instructions", type=int, default=100000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.input is not None:
        input_path = args.input.resolve()
        payload, source = load_input_bytes(input_path=input_path, archive_path=None, entry_name=None)
        seed_name = input_path.name
    else:
        archive_path = args.archive.resolve()
        payload, source = load_input_bytes(
            input_path=None,
            archive_path=archive_path,
            entry_name=args.entry,
        )
        seed_name = args.entry

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    seed_path = artifact_dir / seed_name
    seed_path.write_bytes(payload)

    baseline = _baseline_summary(payload, source, max_script_instructions=args.max_script_instructions)
    (artifact_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    mutants = generate_stage_std_mutants(payload)
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
                max_script_instructions=args.max_script_instructions,
            )
            classification_counts[str(result["classification"])] += 1
            interesting_cases += int(bool(result["interesting"]))
            summary_handle.write(json.dumps(result) + "\n")
            print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-stage-std-campaign-v1",
        "input": source,
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
