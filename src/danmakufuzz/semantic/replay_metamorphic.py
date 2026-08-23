from __future__ import annotations

import argparse
import ctypes
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
from typing import Callable

from ..headless.actions import serialize_mask_actions
from ..headless.baseline import (
    DEFAULT_GAME_DIR,
    DEFAULT_TRACE_COMPACT_COUNTS,
    default_headless_binary,
    run_baseline,
)
from ..interestingness.rules import load_trace_records
from ..parser.replay import (
    REPLAY_STAGE_SENTINEL_FRAME,
    ReplayDataInput,
    ReplayHeader,
    ReplayInputBookmark,
    StageReplayDataPrefix,
    deobfuscate_replay,
    encode_stage_replay_data,
    extract_stage_payloads,
    input_masks_to_replay_bookmarks,
    obfuscate_replay,
    parse_stage_replay_data,
    replay_stage_action_masks,
    replace_replay_stage_payloads,
    with_replay_checksum,
)
from ..repo import ARTIFACTS_DIR, CONFIG_DIR, ensure_directory
from .input_campaign import _run_once, _trace_sha256
from .replay_desync_campaign import (
    _materialize_seed_replay,
    _first_state_divergence,
    _tail_state_delta,
    _trace_state_signature,
)


DEFAULT_ACTION_FILE = CONFIG_DIR / "headless_baseline_actions_1800.txt"
if not DEFAULT_ACTION_FILE.is_file():
    from ..headless.baseline import DEFAULT_ACTION_FILE as FALLBACK_ACTION_FILE

    DEFAULT_ACTION_FILE = FALLBACK_ACTION_FILE


@dataclass(frozen=True)
class ReplayMetamorphicCase:
    name: str
    payload: bytes
    relation: str
    description: str
    sha256: str


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-replay-metamorphic" / stamp


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _case(name: str, payload: bytes, *, description: str) -> ReplayMetamorphicCase:
    return ReplayMetamorphicCase(
        name=name,
        payload=payload,
        relation="replay-action-stream-equivalence",
        description=description,
        sha256=_sha256(payload),
    )


def _stage_payload_from_bookmarks(stage_payload: bytes, bookmarks: list[ReplayInputBookmark]) -> bytes:
    prefix = StageReplayDataPrefix.from_buffer_copy(stage_payload)
    return encode_stage_replay_data(
        input_bookmarks=bookmarks,
        score=int(prefix.score),
        random_seed=int(prefix.randomSeed),
        point_items_collected=int(prefix.pointItemsCollected),
        power=int(prefix.power),
        lives_remaining=int(prefix.livesRemaining),
        bombs_remaining=int(prefix.bombsRemaining),
        rank=int(prefix.rank),
        power_item_count_for_score=int(prefix.powerItemCountForScore),
    )


def _replace_stage(seed_payload: bytes, *, stage: int, stage_payload: bytes) -> bytes:
    return replace_replay_stage_payloads(seed_payload, {stage: stage_payload})


def _raw_replay_input(frame: int, input_mask: int, *, padding: int = 0) -> bytes:
    raw = ReplayDataInput()
    raw.frameNum = int(frame)
    raw.inputKey = int(input_mask) & 0xFFFF
    raw.padding = int(padding) & 0xFFFF
    return bytes(raw)


def _mutate_decoded_header(seed_payload: bytes, mutator: Callable[[bytearray], None]) -> bytes:
    decoded = bytearray(deobfuscate_replay(seed_payload))
    mutator(decoded)
    return obfuscate_replay(with_replay_checksum(bytes(decoded)))


def _ascii_field(value: str, *, size: int) -> bytes:
    return value.encode("ascii", errors="replace")[:size].ljust(size, b"\x00")


def _candidate_bookmark_indexes(bookmarks: list[ReplayInputBookmark], *, limit: int) -> list[int]:
    candidates = [
        index
        for index in range(1, len(bookmarks) - 1)
        if bookmarks[index].frame != REPLAY_STAGE_SENTINEL_FRAME
    ]
    if len(candidates) <= limit:
        return candidates
    anchors = {
        candidates[0],
        candidates[len(candidates) // 2],
        candidates[-1],
    }
    return sorted(anchors)[:limit]


def _candidate_split_frames(input_masks: list[int], *, limit: int) -> list[tuple[int, int]]:
    splits: list[tuple[int, int]] = []
    run_start = 0
    for index in range(1, len(input_masks) + 1):
        if index < len(input_masks) and input_masks[index] == input_masks[run_start]:
            continue
        run_end = index
        if run_end - run_start >= 4:
            frame = run_start + ((run_end - run_start) // 2)
            if frame > 0:
                splits.append((frame, int(input_masks[run_start]) & 0xFFFF))
        run_start = index
        if len(splits) >= limit:
            break
    return splits


def generate_replay_metamorphic_cases(
    seed_payload: bytes,
    *,
    stage: int,
    max_frames: int | None = None,
    site_budget: int = 3,
) -> list[ReplayMetamorphicCase]:
    stage_payloads = extract_stage_payloads(seed_payload)
    stage_payload = stage_payloads[stage - 1]
    if stage_payload is None:
        raise ValueError(f"replay payload has no stage {stage} data")
    stage_data = parse_stage_replay_data(seed_payload)[stage - 1]
    if stage_data is None:
        raise ValueError(f"replay payload has no stage {stage} data")
    baseline_masks = replay_stage_action_masks(seed_payload, stage, max_frames=max_frames)
    bookmarks = list(stage_data.input_bookmarks)

    cases: list[ReplayMetamorphicCase] = []
    baseline_sha = _sha256(seed_payload)
    seen = {baseline_sha}

    def add(name: str, payload: bytes, *, description: str) -> None:
        sha = _sha256(payload)
        if sha in seen:
            return
        seen.add(sha)
        cases.append(_case(name, payload, description=description))

    canonical_payload = _stage_payload_from_bookmarks(
        stage_payload,
        list(input_masks_to_replay_bookmarks(baseline_masks)),
    )
    add(
        "canonical-reencode-action-stream",
        _replace_stage(seed_payload, stage=stage, stage_payload=canonical_payload),
        description="Re-encode the bounded expanded action mask stream into canonical bookmarks.",
    )

    for ordinal, index in enumerate(_candidate_bookmark_indexes(bookmarks, limit=site_budget), start=1):
        target = bookmarks[index]
        shadow = ReplayInputBookmark(
            frame=int(target.frame),
            input_mask=(int(target.input_mask) ^ 0xFFFF) & 0xFFFF,
        )
        mutated = list(bookmarks)
        mutated.insert(index, shadow)
        add(
            f"zero-duration-shadow-i{index:03d}-n{ordinal}",
            _replace_stage(
                seed_payload,
                stage=stage,
                stage_payload=_stage_payload_from_bookmarks(stage_payload, mutated),
            ),
            description="Insert a same-frame shadow bookmark before a real bookmark; expansion should ignore the zero-duration row.",
        )

    canonical_bookmarks = list(input_masks_to_replay_bookmarks(baseline_masks))
    for ordinal, (frame, input_mask) in enumerate(
        _candidate_split_frames(baseline_masks, limit=site_budget),
        start=1,
    ):
        insertion = ReplayInputBookmark(frame=frame, input_mask=input_mask)
        insert_at = 1
        while insert_at < len(canonical_bookmarks) and canonical_bookmarks[insert_at].frame < frame:
            insert_at += 1
        mutated = list(canonical_bookmarks)
        mutated.insert(insert_at, insertion)
        add(
            f"same-mask-run-split-t{frame}-n{ordinal}",
            _replace_stage(
                seed_payload,
                stage=stage,
                stage_payload=_stage_payload_from_bookmarks(stage_payload, mutated),
            ),
            description="Split a constant-action run with an extra bookmark carrying the same mask.",
        )

    double_sentinel_payload = bytes(stage_payload) + _raw_replay_input(
        REPLAY_STAGE_SENTINEL_FRAME,
        0xFFFF,
        padding=0x5A5A,
    )
    add(
        "double-sentinel-shadow",
        _replace_stage(seed_payload, stage=stage, stage_payload=double_sentinel_payload),
        description="Append a second sentinel record after the first sentinel; parser expansion stops at the first one.",
    )

    post_sentinel_payload = bytes(stage_payload) + _raw_replay_input(
        REPLAY_STAGE_SENTINEL_FRAME + 1,
        0x00FF,
        padding=0xA5A5,
    )
    add(
        "post-sentinel-record-shadow",
        _replace_stage(seed_payload, stage=stage, stage_payload=post_sentinel_payload),
        description="Append a replay input record after the sentinel; parser expansion should ignore it.",
    )

    input_padding = bytearray(stage_payload)
    prefix_size = ctypes.sizeof(StageReplayDataPrefix)
    input_size = ctypes.sizeof(ReplayDataInput)
    cursor = prefix_size
    while cursor + input_size <= len(input_padding):
        struct.pack_into("<H", input_padding, cursor + ReplayDataInput.padding.offset, 0xA55A)
        raw = ReplayDataInput.from_buffer_copy(input_padding, cursor)
        cursor += input_size
        if int(raw.frameNum) == REPLAY_STAGE_SENTINEL_FRAME:
            break
    add(
        "input-padding-pattern",
        _replace_stage(seed_payload, stage=stage, stage_payload=bytes(input_padding)),
        description="Set replay input row padding fields; action expansion ignores padding.",
    )

    prefix_padding = bytearray(stage_payload)
    for offset in range(3):
        prefix_padding[StageReplayDataPrefix.padding.offset + offset] = (0xC0 + offset) & 0xFF
    add(
        "stage-prefix-padding-pattern",
        _replace_stage(seed_payload, stage=stage, stage_payload=bytes(prefix_padding)),
        description="Set StageReplayDataPrefix padding bytes; action expansion ignores prefix padding.",
    )

    def mutate_header_metadata(decoded: bytearray) -> None:
        struct.pack_into("<i", decoded, ReplayHeader.score.offset, 0x12345678)
        struct.pack_into("<f", decoded, ReplayHeader.slowdownRate.offset, 0.5)
        struct.pack_into("<f", decoded, ReplayHeader.slowdownRate2.offset, 0.75)
        struct.pack_into("<f", decoded, ReplayHeader.slowdownRate3.offset, 1.25)
        decoded[ReplayHeader.date.offset : ReplayHeader.date.offset + 9] = _ascii_field("20991231", size=9)
        decoded[ReplayHeader.name.offset : ReplayHeader.name.offset + 8] = _ascii_field("META", size=8)

    add(
        "header-display-metadata-pattern",
        _mutate_decoded_header(seed_payload, mutate_header_metadata),
        description="Change replay header display/score/slowdown metadata while preserving stage payloads.",
    )

    def mutate_header_key(decoded: bytearray) -> None:
        decoded[ReplayHeader.key.offset] = 0x2A

    add(
        "header-key-reobfuscate-2a",
        _mutate_decoded_header(seed_payload, mutate_header_key),
        description="Re-obfuscate the replay with a different key byte while preserving decoded stage payloads.",
    )

    return cases


def _mask_signature(input_masks: list[int]) -> str:
    digest = hashlib.sha256()
    for mask in input_masks:
        digest.update(int(mask & 0xFFFF).to_bytes(2, "little", signed=False))
    return digest.hexdigest()


def _bounded_masks(input_masks: list[int], *, length: int | None) -> list[int]:
    masks = [int(mask) & 0xFFFF for mask in input_masks]
    if length is None:
        return masks
    if len(masks) >= length:
        return masks[:length]
    return masks + ([0] * (length - len(masks)))


def evaluate_replay_metamorphic_payload(
    payload: bytes,
    *,
    stage: int,
    baseline_masks: list[int],
    max_frames: int | None,
) -> dict[str, object]:
    try:
        masks = replay_stage_action_masks(payload, stage, max_frames=max_frames)
    except Exception as exc:
        return {
            "relation_holds": False,
            "metamorphic_violation": True,
            "violation_kind": "parser-error",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    bounded_masks = _bounded_masks(list(masks), length=max_frames)
    bounded_baseline = _bounded_masks(list(baseline_masks), length=max_frames)
    relation_holds = bounded_masks == bounded_baseline
    return {
        "relation_holds": relation_holds,
        "metamorphic_violation": not relation_holds,
        "violation_kind": None if relation_holds else "action-stream-drift",
        "action_count": len(masks),
        "bounded_action_count": len(bounded_masks),
        "action_sha256": _mask_signature(bounded_masks),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run replay metamorphic equivalence checks over alternate replay encodings with the same action stream."
    )
    parser.add_argument("--input", type=Path, help="optional TH06 replay seed; omitted means synthesize from --actions")
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--stage", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--difficulty", type=int)
    parser.add_argument("--character", type=int)
    parser.add_argument("--shot-type", type=int)
    parser.add_argument("--max-ticks", type=int, default=1200)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--trace-compact-counts", dest="trace_compact_counts", action="store_true")
    parser.add_argument("--full-entity-trace", dest="trace_compact_counts", action="store_false")
    parser.set_defaults(trace_compact_counts=DEFAULT_TRACE_COMPACT_COUNTS)
    parser.add_argument("--site-budget", type=int, default=3)
    parser.add_argument("--emit-cases", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    input_path = args.input.resolve() if args.input is not None else None
    stage = args.stage if args.stage is not None else (None if input_path is not None else 6)
    seed = args.seed if args.seed is not None else (None if input_path is not None else 7)
    difficulty = args.difficulty if args.difficulty is not None else (None if input_path is not None else 3)
    character = args.character if args.character is not None else (None if input_path is not None else 0)
    shot_type = args.shot_type if args.shot_type is not None else (None if input_path is not None else 0)
    seed_payload, seed_runtime, baseline_input_masks = _materialize_seed_replay(
        input_path=input_path,
        actions_path=args.actions.resolve(),
        stage=stage,
        seed=seed,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        auto_shoot=True,
    )
    resolved_stage = int(seed_runtime["stage"])
    resolved_seed = int(seed_runtime["seed"])
    resolved_difficulty = int(seed_runtime["difficulty"])
    resolved_character = int(seed_runtime["character"])
    resolved_shot_type = int(seed_runtime["shot_type"])
    max_ticks = min(int(args.max_ticks), len(baseline_input_masks))
    baseline_masks = list(baseline_input_masks[:max_ticks])
    seed_replay_path = artifact_dir / "seed.rpy"
    seed_replay_path.write_bytes(seed_payload)
    baseline_actions_path = artifact_dir / "baseline-actions.txt"
    baseline_actions_path.write_text(serialize_mask_actions(baseline_masks), encoding="utf-8")

    baseline_dir = artifact_dir / "_baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=resolved_stage,
        seed=resolved_seed,
        action_file=baseline_actions_path,
        artifact_dir=baseline_dir,
        difficulty=resolved_difficulty,
        character=resolved_character,
        shot_type=resolved_shot_type,
        max_ticks=max_ticks,
        auto_shoot=False,
        continue_after_hit=args.continue_after_hit,
        trace_compact_counts=args.trace_compact_counts,
        log_path=baseline_dir / "run.log",
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_records = load_trace_records(baseline_trace)
    baseline_trace_sha = _trace_sha256(baseline_trace)
    baseline_state_sha = _trace_state_signature(baseline_records)
    cases = generate_replay_metamorphic_cases(
        seed_payload,
        stage=resolved_stage,
        max_frames=max_ticks,
        site_budget=max(1, int(args.site_budget)),
    )

    summary_path = artifact_dir / "summary.jsonl"
    relation_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    violation_counts: Counter[str] = Counter()
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, case in enumerate(cases, start=1):
            case_name = f"{case_index:04d}-{case.name}"
            case_dir = artifact_dir / case_name
            ensure_directory(case_dir)
            replay_path = case_dir / "input.rpy"
            replay_path.write_bytes(case.payload)
            parser_evaluation = evaluate_replay_metamorphic_payload(
                case.payload,
                stage=resolved_stage,
                baseline_masks=baseline_masks,
                max_frames=max_ticks,
            )
            relation_holds = bool(parser_evaluation.get("relation_holds"))
            relation_counts["holds" if relation_holds else "violated"] += 1
            run: dict[str, object] | None = None
            runtime_evaluation: dict[str, object] | None = None
            classification = "action-equivalent"
            if relation_holds:
                actions_path = case_dir / "actions.txt"
                actions_path.write_text(serialize_mask_actions(baseline_masks), encoding="utf-8")
                run = _run_once(
                    binary=args.headless_bin.resolve(),
                    game_dir=args.game_dir.resolve(),
                    stage=resolved_stage,
                    seed=resolved_seed,
                    action_file=actions_path,
                    difficulty=resolved_difficulty,
                    character=resolved_character,
                    shot_type=resolved_shot_type,
                    max_ticks=max_ticks,
                    auto_shoot=False,
                    continue_after_hit=args.continue_after_hit,
                    timeout_seconds=args.timeout_seconds,
                    trace_compact_counts=args.trace_compact_counts,
                    trace_path=case_dir / "trace.jsonl",
                    log_path=case_dir / "run.log",
                    baseline_records=baseline_records,
                )
                trace_path = Path(str(run.get("trace", "")))
                records = load_trace_records(trace_path) if trace_path.is_file() else []
                state_sha = _trace_state_signature(records)
                runtime_equivalent = (
                    run.get("returncode") == 0
                    and not run.get("timed_out")
                    and run.get("trace_sha256") == baseline_trace_sha
                    and state_sha == baseline_state_sha
                )
                classification = "equivalent" if runtime_equivalent else "runtime-drift"
                runtime_evaluation = {
                    "runtime_equivalent": runtime_equivalent,
                    "baseline_trace_sha256": baseline_trace_sha,
                    "case_trace_sha256": run.get("trace_sha256"),
                    "baseline_state_sha256": baseline_state_sha,
                    "case_state_sha256": state_sha,
                    "first_divergence": _first_state_divergence(baseline_records, records)
                    if state_sha != baseline_state_sha
                    else None,
                    "tail_delta": _tail_state_delta(baseline_records, records)
                    if state_sha != baseline_state_sha
                    else None,
                }
                if not runtime_equivalent:
                    violation_counts["runtime-drift"] += 1
            else:
                classification = str(parser_evaluation.get("violation_kind") or "relation-violation")
                violation_counts[classification] += 1
            classification_counts[classification] += 1
            result = {
                "schema": "danmakufuzz-replay-metamorphic-case-v1",
                "case_name": case_name,
                "mutant_name": case.name,
                "stage": resolved_stage,
                "relation": case.relation,
                "description": case.description,
                "input_replay": str(replay_path.resolve()),
                "payload_sha256": case.sha256,
                "parser_evaluation": parser_evaluation,
                "runtime_evaluation": runtime_evaluation,
                "run": {key: value for key, value in run.items() if key != "findings"} if run else None,
                "classification": classification,
                "metamorphic_violation": classification != "equivalent",
            }
            (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            summary_handle.write(json.dumps(result) + "\n")
            if args.emit_cases:
                print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-replay-metamorphic-campaign-v1",
        "artifact_dir": str(artifact_dir),
        "seed_replay": str(seed_replay_path.resolve()),
        "seed_runtime": seed_runtime,
        "stage": resolved_stage,
        "max_ticks": max_ticks,
        "baseline": baseline_metadata,
        "baseline_action_sha256": _mask_signature(baseline_masks),
        "baseline_trace_sha256": baseline_trace_sha,
        "baseline_state_sha256": baseline_state_sha,
        "cases_generated": len(cases),
        "relation_counts": dict(sorted(relation_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "violation_counts": dict(sorted(violation_counts.items())),
        "summary": str(summary_path.resolve()),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if violation_counts else 0


if __name__ == "__main__":
    raise SystemExit(main())
