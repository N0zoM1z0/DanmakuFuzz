from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ..repo import ARTIFACTS_DIR, ensure_directory
from .game_cfg import DEFAULT_CFG_PATH, load_game_cfg
from .game_cfg_mutants import GameCfgMutant, generate_game_cfg_mutants


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-game-cfg" / stamp


def evaluate_game_cfg_payload(payload: bytes, baseline_summary: dict[str, object]) -> dict[str, object]:
    parsed = load_game_cfg(payload)
    baseline_effective = baseline_summary.get("effective_summary")
    effective = parsed.get("effective_summary")
    changed_fields: list[str] = []
    if parsed.get("classification") != baseline_summary.get("classification"):
        changed_fields.append("classification")
    if parsed.get("fallback_reasons") != baseline_summary.get("fallback_reasons"):
        changed_fields.append("fallback_reasons")
    for field in (
        "version",
        "life_count",
        "bomb_count",
        "color_mode_16bit",
        "music_mode",
        "play_sounds",
        "default_difficulty",
        "windowed",
        "frameskip_config",
        "pad_x_axis",
        "pad_y_axis",
        "opts",
        "enabled_option_names",
        "controller_mapping",
    ):
        if (
            isinstance(effective, dict)
            and isinstance(baseline_effective, dict)
            and effective.get(field) != baseline_effective.get(field)
        ):
            changed_fields.append(field)
    equivalent = (
        not changed_fields
    )
    return {
        **parsed,
        "interesting": not equivalent,
        "equivalent_to_baseline": equivalent,
        "changed_fields": changed_fields,
    }


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: GameCfgMutant,
    *,
    case_index: int,
    artifact_dir: Path,
    baseline_summary: dict[str, object],
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    input_path = case_dir / "input.cfg"
    input_path.write_bytes(mutant.payload)
    evaluation = evaluate_game_cfg_payload(mutant.payload, baseline_summary)
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
    parser = argparse.ArgumentParser(description="Run a lightweight Touhou game cfg mutation campaign.")
    parser.add_argument("--input", type=Path, default=DEFAULT_CFG_PATH)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing cfg seed: {input_path}")

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    payload = input_path.read_bytes()
    seed_path = artifact_dir / input_path.name
    seed_path.write_bytes(payload)

    baseline = {"input": str(input_path), **load_game_cfg(payload)}
    (artifact_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    mutants = generate_game_cfg_mutants(payload)
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
        "schema": "danmakufuzz-game-cfg-campaign-v1",
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
