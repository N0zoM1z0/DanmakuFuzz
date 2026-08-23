from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .anm import DEFAULT_ARCHIVE, DEFAULT_ENTRY, parse_anm
from .anm_mutants import AnmMutant, generate_anm_mutants
from .common import load_input_bytes


def _slug_seed_name(seed_name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", seed_name).strip("-._")
    return slug or "seed"


def _default_artifact_dir(seed_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-anm" / f"{stamp}-{_slug_seed_name(seed_name)}"


def _script_digest(summary: dict[str, object]) -> dict[str, object]:
    scripts = summary.get("scripts")
    if not isinstance(scripts, list):
        return {"count": 0, "instruction_counts": [], "stop_reasons": []}
    return {
        "count": len(scripts),
        "instruction_counts": [
            script.get("instruction_count") if isinstance(script, dict) else None
            for script in scripts
        ],
        "stop_reasons": [
            script.get("stop_reason") if isinstance(script, dict) else None
            for script in scripts
        ],
    }


def evaluate_anm_payload(payload: bytes, baseline_summary: dict[str, object], *, max_script_instructions: int) -> dict[str, object]:
    try:
        parsed = parse_anm(payload, max_script_instructions=max_script_instructions)
    except ValueError as exc:
        return {
            "classification": "parse-error",
            "interesting": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    tracked_fields = (
        "num_sprites",
        "num_scripts",
        "texture_index",
        "width",
        "height",
        "format",
        "color_key",
        "name",
        "alpha_name",
        "sprite_offsets",
        "sprite_offsets_increasing",
        "script_entries",
        "script_offsets_increasing",
        "total_instructions",
        "max_script_instructions",
        "max_time",
        "invalid_jump_targets",
        "opcode_histogram",
    )
    changed_fields = [
        field
        for field in tracked_fields
        if parsed.get(field) != baseline_summary.get(field)
    ]
    parsed_digest = _script_digest(parsed)
    baseline_digest = _script_digest(baseline_summary)
    if parsed_digest != baseline_digest:
        changed_fields.append("scripts")
    equivalent = not changed_fields
    return {
        "classification": "accepted",
        "interesting": not equivalent,
        **parsed,
        "equivalent_to_baseline": equivalent,
        "changed_fields": changed_fields,
        "script_digest": parsed_digest,
    }


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: AnmMutant,
    *,
    case_index: int,
    artifact_dir: Path,
    baseline_summary: dict[str, object],
    max_script_instructions: int,
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    input_path = case_dir / "input.anm"
    input_path.write_bytes(mutant.payload)
    evaluation = evaluate_anm_payload(
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
    parser = argparse.ArgumentParser(description="Run a lightweight Touhou ANM mutation campaign.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", type=str, default=DEFAULT_ENTRY)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--max-script-instructions", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, source = load_input_bytes(input_path=args.input, archive_path=args.archive, entry_name=args.entry)
    seed_name = Path(args.input).name if args.input is not None else args.entry

    artifact_dir = (args.artifact_dir or _default_artifact_dir(seed_name)).resolve()
    ensure_directory(artifact_dir)
    seed_path = artifact_dir / seed_name
    seed_path.write_bytes(payload)

    baseline = {
        "input": source,
        **parse_anm(payload, max_script_instructions=args.max_script_instructions),
    }
    (artifact_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    mutants = generate_anm_mutants(payload)
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
        "schema": "danmakufuzz-anm-campaign-v1",
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
