from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ..headless.actions import action_token_to_input_mask, parse_actions_file, serialize_mask_actions
from ..headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    DEFAULT_TRACE_COMPACT_COUNTS,
    default_headless_binary,
    run_baseline,
)
from ..interestingness.rules import load_trace_records
from ..parser.replay import (
    ReplayHeader,
    build_replay_with_stage_slots,
    encode_stage_replay_data,
    input_masks_to_replay_bookmarks,
    parse_stage_replay_data,
    replay_populated_stages,
    replay_stage_action_masks,
)
from ..repo import ARTIFACTS_DIR, ensure_directory
from .input_campaign import _filter_findings, _repeat_desync_findings, _run_once
from .replay_input_mutants import (
    ReplayInputMutant,
    generate_replay_input_mutants,
    select_diverse_replay_input_mutants,
)


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-replay" / stamp


def _infer_replay_stage(seed_payload: bytes) -> int:
    populated = replay_populated_stages(seed_payload)
    if not populated:
        raise ValueError("replay payload has no stage replay data")
    if len(populated) > 1:
        raise ValueError(
            "replay payload has multiple populated stages; pass --stage explicitly or use replay_corpus_campaign"
        )
    return int(populated[0])


def _synthesize_replay_seed(
    *,
    actions_path: Path,
    stage: int,
    difficulty: int,
    character: int,
    shot_type: int,
    auto_shoot: bool,
) -> tuple[bytes, list[int]]:
    stream = parse_actions_file(actions_path)
    input_masks = [
        action_token_to_input_mask(action, auto_shoot=auto_shoot)
        for action in stream.actions
    ]
    stage_payload = encode_stage_replay_data(
        input_bookmarks=input_masks_to_replay_bookmarks(input_masks),
        random_seed=7,
        power=0,
        lives_remaining=2,
        bombs_remaining=3,
        rank=0,
    )
    stage_slots: list[bytes | None] = [None] * 7
    stage_slots[stage - 1] = stage_payload
    payload = build_replay_with_stage_slots(
        shottype_chara=(character * 2) + shot_type,
        difficulty=difficulty,
        stage_payloads_by_slot=stage_slots,
    )
    return payload, input_masks


def _runtime_config_from_replay(
    seed_payload: bytes,
    *,
    stage: int | None,
    difficulty: int | None,
    character: int | None,
    shot_type: int | None,
) -> tuple[int, int, int, int]:
    decoded_header = ReplayHeader.from_buffer_copy(seed_payload[: ctypes_sizeof_replay_header()])
    resolved_stage = stage if stage is not None else _infer_replay_stage(seed_payload)
    resolved_difficulty = difficulty if difficulty is not None else int(decoded_header.difficulty)
    shottype_chara = int(decoded_header.shottypeChara)
    resolved_character = character if character is not None else (shottype_chara // 2)
    resolved_shot_type = shot_type if shot_type is not None else (shottype_chara % 2)
    return resolved_stage, resolved_difficulty, resolved_character, resolved_shot_type


def ctypes_sizeof_replay_header() -> int:
    import ctypes

    return ctypes.sizeof(ReplayHeader)


def _materialize_seed_replay(
    *,
    input_path: Path | None,
    actions_path: Path,
    stage: int | None,
    difficulty: int | None,
    character: int | None,
    shot_type: int | None,
    auto_shoot: bool,
) -> tuple[bytes, dict[str, object], list[int]]:
    if input_path is not None:
        seed_payload = input_path.read_bytes()
        resolved_stage, resolved_difficulty, resolved_character, resolved_shot_type = _runtime_config_from_replay(
            seed_payload,
            stage=stage,
            difficulty=difficulty,
            character=character,
            shot_type=shot_type,
        )
        input_masks = replay_stage_action_masks(seed_payload, resolved_stage)
        return seed_payload, {
            "source": str(input_path.resolve()),
            "stage": resolved_stage,
            "difficulty": resolved_difficulty,
            "character": resolved_character,
            "shot_type": resolved_shot_type,
            "auto_shoot": False,
        }, input_masks

    if stage is None:
        raise ValueError("--stage is required when synthesizing a replay seed from actions")
    if difficulty is None or character is None or shot_type is None:
        raise ValueError(
            "--difficulty/--character/--shot-type are required when synthesizing a replay seed from actions"
        )
    seed_payload, input_masks = _synthesize_replay_seed(
        actions_path=actions_path,
        stage=stage,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        auto_shoot=auto_shoot,
    )
    return seed_payload, {
        "source": f"synthetic-from-actions:{actions_path.resolve()}",
        "stage": stage,
        "difficulty": difficulty,
        "character": character,
        "shot_type": shot_type,
        "auto_shoot": False,
    }, input_masks


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: ReplayInputMutant,
    *,
    case_index: int,
    artifact_dir: Path,
    binary: Path,
    game_dir: Path,
    stage: int,
    seed: int,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    continue_after_hit: bool,
    timeout_seconds: float,
    trace_compact_counts: bool,
    baseline_records: list[dict[str, object]] | None,
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)

    replay_path = case_dir / "input.rpy"
    replay_path.write_bytes(mutant.payload)
    input_masks = replay_stage_action_masks(mutant.payload, mutant.stage, max_frames=max_ticks)
    actions_path = case_dir / "actions.txt"
    actions_path.write_text(serialize_mask_actions(input_masks), encoding="utf-8")

    run_a = _run_once(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        action_file=actions_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=False,
        continue_after_hit=continue_after_hit,
        timeout_seconds=timeout_seconds,
        trace_compact_counts=trace_compact_counts,
        trace_path=case_dir / "trace-a.jsonl",
        log_path=case_dir / "run-a.log",
        baseline_records=baseline_records,
    )
    run_b = _run_once(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        action_file=actions_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=False,
        continue_after_hit=continue_after_hit,
        timeout_seconds=timeout_seconds,
        trace_compact_counts=trace_compact_counts,
        trace_path=case_dir / "trace-b.jsonl",
        log_path=case_dir / "run-b.log",
        baseline_records=baseline_records,
    )

    findings = list(run_a["findings"])
    findings.extend(_repeat_desync_findings(run_a, run_b))
    filtered_findings = _filter_findings(findings)
    result = {
        "case_name": case_name,
        "mutant_name": mutant.name,
        "source": mutant.source,
        "stage": mutant.stage,
        "input_replay": str(replay_path.resolve()),
        "actions_path": str(actions_path.resolve()),
        "actions_count": len(input_masks),
        "payload_sha256": mutant.sha256,
        "mutation_metadata": mutant.metadata,
        "run_a": {key: value for key, value in run_a.items() if key != "findings"},
        "run_b": {key: value for key, value in run_b.items() if key != "findings"},
        "findings": [{"kind": finding.kind, "detail": finding.detail} for finding in filtered_findings],
        "interesting": bool(filtered_findings),
    }
    _write_case_result(case_dir, result)
    return result


def run_replay_desync_campaign(
    *,
    artifact_dir: Path,
    input_path: Path | None,
    actions_path: Path,
    game_dir: Path,
    headless_bin: Path,
    stage: int | None,
    seed: int,
    difficulty: int | None,
    character: int | None,
    shot_type: int | None,
    max_ticks: int | None,
    timeout_seconds: float,
    auto_shoot: bool,
    continue_after_hit: bool,
    trace_compact_counts: bool,
    random_seed: int,
    samples_per_site: int,
    limit: int | None,
    name_filters: list[str] | None = None,
    emit_stdout: bool = True,
) -> dict[str, object]:
    ensure_directory(artifact_dir)

    seed_payload, seed_runtime, baseline_input_masks = _materialize_seed_replay(
        input_path=input_path,
        actions_path=actions_path,
        stage=stage,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        auto_shoot=auto_shoot,
    )
    resolved_stage = int(seed_runtime["stage"])
    resolved_difficulty = int(seed_runtime["difficulty"])
    resolved_character = int(seed_runtime["character"])
    resolved_shot_type = int(seed_runtime["shot_type"])
    resolved_max_ticks = max_ticks if max_ticks is not None else len(baseline_input_masks)

    seed_replay_path = artifact_dir / "seed.rpy"
    seed_replay_path.write_bytes(seed_payload)
    baseline_actions_path = artifact_dir / "baseline-actions.txt"
    baseline_actions_path.write_text(
        serialize_mask_actions(baseline_input_masks[:resolved_max_ticks]),
        encoding="utf-8",
    )

    baseline_dir = artifact_dir / "_baseline"
    baseline_metadata = run_baseline(
        binary=headless_bin,
        game_dir=game_dir,
        resource_override_dir=None,
        stage=resolved_stage,
        seed=seed,
        action_file=baseline_actions_path,
        artifact_dir=baseline_dir,
        difficulty=resolved_difficulty,
        character=resolved_character,
        shot_type=resolved_shot_type,
        max_ticks=resolved_max_ticks,
        auto_shoot=False,
        continue_after_hit=continue_after_hit,
        trace_compact_counts=trace_compact_counts,
        log_path=baseline_dir / "run.log",
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_records = load_trace_records(baseline_trace) if baseline_trace.is_file() else None

    mutants = generate_replay_input_mutants(
        seed_payload,
        stage=resolved_stage,
        max_frames=resolved_max_ticks,
        random_seed=random_seed,
        samples_per_site=samples_per_site,
    )
    if name_filters:
        mutants = [
            mutant
            for mutant in mutants
            if any(name_filter in mutant.name for name_filter in name_filters)
        ]
    mutants = select_diverse_replay_input_mutants(mutants, limit=limit)

    summary_path = artifact_dir / "summary.jsonl"
    classification_counts: Counter[str] = Counter()
    interesting_cases = 0
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, mutant in enumerate(mutants, start=1):
            result = _run_mutant(
                mutant,
                case_index=case_index,
                artifact_dir=artifact_dir,
                binary=headless_bin,
                game_dir=game_dir,
                stage=resolved_stage,
                seed=seed,
                difficulty=resolved_difficulty,
                character=resolved_character,
                shot_type=resolved_shot_type,
                max_ticks=resolved_max_ticks,
                continue_after_hit=continue_after_hit,
                timeout_seconds=timeout_seconds,
                trace_compact_counts=trace_compact_counts,
                baseline_records=baseline_records,
            )
            if result["interesting"]:
                classification_counts["interesting"] += 1
                interesting_cases += 1
            else:
                classification_counts["boring"] += 1
            summary_handle.write(json.dumps(result) + "\n")
            if emit_stdout:
                print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-semantic-replay-campaign-v1",
        "seed_replay": str(seed_replay_path.resolve()),
        "seed_runtime": seed_runtime,
        "baseline_actions": str(baseline_actions_path.resolve()),
        "baseline": baseline_metadata,
        "stage": resolved_stage,
        "seed": seed,
        "random_seed": random_seed,
        "samples_per_site": samples_per_site,
        "mutants_generated": len(mutants),
        "interesting_cases": interesting_cases,
        "classification_counts": dict(sorted(classification_counts.items())),
        "summary": str(summary_path.resolve()),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if emit_stdout:
        print(json.dumps(report, indent=2))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a replay-derived semantic/desync campaign by turning TH06 replay stage data into raw headless input masks."
    )
    parser.add_argument("--input", type=Path, help="optional TH06 replay seed; if omitted, synthesize one from --actions")
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--stage", type=int)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--difficulty", type=int)
    parser.add_argument("--character", type=int)
    parser.add_argument("--shot-type", type=int)
    parser.add_argument("--max-ticks", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--trace-compact-counts", dest="trace_compact_counts", action="store_true")
    parser.add_argument("--full-entity-trace", dest="trace_compact_counts", action="store_false")
    parser.set_defaults(trace_compact_counts=DEFAULT_TRACE_COMPACT_COUNTS)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--samples-per-site", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve() if args.input is not None else None
    report = run_replay_desync_campaign(
        artifact_dir=(args.artifact_dir or _default_artifact_dir()).resolve(),
        input_path=input_path,
        actions_path=args.actions.resolve(),
        game_dir=args.game_dir.resolve(),
        headless_bin=args.headless_bin.resolve(),
        stage=args.stage,
        seed=args.seed,
        difficulty=args.difficulty,
        character=args.character,
        shot_type=args.shot_type,
        max_ticks=args.max_ticks,
        timeout_seconds=args.timeout_seconds,
        auto_shoot=args.auto_shoot,
        continue_after_hit=args.continue_after_hit,
        trace_compact_counts=args.trace_compact_counts,
        random_seed=args.random_seed,
        samples_per_site=args.samples_per_site,
        limit=args.limit,
        name_filters=list(args.name_filter or []),
        emit_stdout=True,
    )
    _ = report
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
