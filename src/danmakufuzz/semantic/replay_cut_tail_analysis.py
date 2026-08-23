from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Sequence

from ..parser.replay import (
    REPLAY_STAGE_SENTINEL_FRAME,
    ReplayInputBookmark,
    ReplayStageData,
    encode_stage_replay_data,
    parse_stage_replay_data,
    replay_stage_action_masks,
    replace_replay_stage_payloads,
)
from ..reduction import BisectionResult, first_prefix_divergence, first_true_index
from ..repo import ARTIFACTS_DIR, ensure_directory
from .replay_metamorphic import (
    ReplayMetamorphicCase,
    evaluate_replay_metamorphic_payload,
    generate_replay_metamorphic_cases,
)


@dataclass(frozen=True)
class ReplayCutTailCase:
    name: str
    payload: bytes
    stage: int
    bookmark_index: int
    cut_frame: int
    expected_terminal_tick: int
    payload_sha256: str


@dataclass(frozen=True)
class ReplayCutTailCompositionCase:
    name: str
    payload: bytes
    order: str
    wrapper_name: str
    stage: int
    bookmark_index: int
    cut_frame: int
    expected_terminal_tick: int
    payload_sha256: str


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-replay-cut-tail-analysis" / stamp


def candidate_cut_tail_indexes(bookmarks: Sequence[ReplayInputBookmark]) -> tuple[int, ...]:
    return tuple(
        index
        for index in range(1, len(bookmarks) - 1)
        if bookmarks[index].frame not in (0, REPLAY_STAGE_SENTINEL_FRAME)
    )


def first_cut_tail_bookmark_index(bookmarks: Sequence[ReplayInputBookmark]) -> int:
    candidates = candidate_cut_tail_indexes(bookmarks)
    if not candidates:
        raise ValueError("replay stage has no non-initial cut-tail bookmark candidate")
    return int(candidates[0])


def find_bookmark_index_at_frame(bookmarks: Sequence[ReplayInputBookmark], frame: int) -> int | None:
    for index in candidate_cut_tail_indexes(bookmarks):
        if int(bookmarks[index].frame) == int(frame):
            return index
    return None


def cut_tail_bookmarks(
    bookmarks: Sequence[ReplayInputBookmark],
    *,
    index: int,
) -> tuple[ReplayInputBookmark, ...]:
    if not (0 < index < len(bookmarks) - 1):
        raise ValueError(f"bookmark index is not cuttable: {index}")
    cut_frame = int(bookmarks[index].frame)
    if cut_frame <= 0 or cut_frame == REPLAY_STAGE_SENTINEL_FRAME:
        raise ValueError(f"bookmark frame is not cuttable: {cut_frame}")
    prefix = list(bookmarks[:index])
    if not prefix:
        raise ValueError("cut-tail prefix must keep the initial bookmark")
    if prefix[-1].frame != cut_frame or prefix[-1].input_mask != 0:
        prefix.append(ReplayInputBookmark(frame=cut_frame, input_mask=0))
    prefix.append(ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0))
    return tuple(prefix)


def stage_payload_from_bookmarks(
    stage_data: ReplayStageData,
    bookmarks: Sequence[ReplayInputBookmark],
) -> bytes:
    return encode_stage_replay_data(
        input_bookmarks=bookmarks,
        score=stage_data.score,
        random_seed=stage_data.random_seed,
        point_items_collected=stage_data.point_items_collected,
        power=stage_data.power,
        lives_remaining=stage_data.lives_remaining,
        bombs_remaining=stage_data.bombs_remaining,
        rank=stage_data.rank,
        power_item_count_for_score=stage_data.power_item_count_for_score,
    )


def replay_input_exhaustion_model(cut_frame: int) -> dict[str, object]:
    expected_terminal_tick = int(cut_frame) + 2
    return {
        "model": "th06-replay-cut-tail-input-exhaustion-v1",
        "input_exhaustion_frame": int(cut_frame),
        "expected_terminal_reason": "input-error",
        "expected_terminal_tick": expected_terminal_tick,
        "latency_ticks_after_cut": 2,
    }


def build_cut_tail_case(
    seed_payload: bytes,
    *,
    stage: int,
    bookmark_index: int | None = None,
) -> ReplayCutTailCase:
    stage_data = parse_stage_replay_data(seed_payload)[stage - 1]
    if stage_data is None:
        raise ValueError(f"replay payload has no stage {stage} data")
    index = first_cut_tail_bookmark_index(stage_data.input_bookmarks) if bookmark_index is None else int(bookmark_index)
    cut_frame = int(stage_data.input_bookmarks[index].frame)
    bookmarks = cut_tail_bookmarks(stage_data.input_bookmarks, index=index)
    stage_payload = stage_payload_from_bookmarks(stage_data, bookmarks)
    payload = replace_replay_stage_payloads(seed_payload, {stage: stage_payload})
    expected_tick = int(replay_input_exhaustion_model(cut_frame)["expected_terminal_tick"])
    return ReplayCutTailCase(
        name=f"bookmark-cut-tail-i{index:03d}-t{cut_frame}",
        payload=payload,
        stage=stage,
        bookmark_index=index,
        cut_frame=cut_frame,
        expected_terminal_tick=expected_tick,
        payload_sha256=_sha256(payload),
    )


def reduce_cut_tail_index(
    seed_payload: bytes,
    *,
    stage: int,
    predicate: Callable[[ReplayCutTailCase], bool],
    max_evaluations: int = 64,
) -> BisectionResult[int]:
    stage_data = parse_stage_replay_data(seed_payload)[stage - 1]
    if stage_data is None:
        raise ValueError(f"replay payload has no stage {stage} data")
    candidates = candidate_cut_tail_indexes(stage_data.input_bookmarks)

    def matches(index: int) -> bool:
        return bool(predicate(build_cut_tail_case(seed_payload, stage=stage, bookmark_index=index)))

    return first_true_index(candidates, matches, max_evaluations=max_evaluations)


def _composition_case(
    *,
    name: str,
    payload: bytes,
    order: str,
    wrapper_name: str,
    stage: int,
    bookmark_index: int,
    cut_frame: int,
) -> ReplayCutTailCompositionCase:
    expected_tick = int(replay_input_exhaustion_model(cut_frame)["expected_terminal_tick"])
    return ReplayCutTailCompositionCase(
        name=name,
        payload=payload,
        order=order,
        wrapper_name=wrapper_name,
        stage=stage,
        bookmark_index=bookmark_index,
        cut_frame=cut_frame,
        expected_terminal_tick=expected_tick,
        payload_sha256=_sha256(payload),
    )


def generate_cut_tail_composition_cases(
    seed_payload: bytes,
    *,
    stage: int,
    bookmark_index: int | None = None,
    max_frames: int | None = None,
    site_budget: int = 3,
) -> list[ReplayCutTailCompositionCase]:
    base_case = build_cut_tail_case(seed_payload, stage=stage, bookmark_index=bookmark_index)
    seen = {("base", base_case.payload_sha256)}
    cases: list[ReplayCutTailCompositionCase] = []

    def add(case: ReplayCutTailCompositionCase) -> None:
        key = (case.order, case.payload_sha256)
        if key in seen:
            return
        seen.add(key)
        cases.append(case)

    for wrapper in generate_replay_metamorphic_cases(
        base_case.payload,
        stage=stage,
        max_frames=max_frames,
        site_budget=site_budget,
    ):
        add(
            _composition_case(
                name=f"delta-then-wrapper-{wrapper.name}",
                payload=wrapper.payload,
                order="delta-then-equivalent-wrapper",
                wrapper_name=wrapper.name,
                stage=stage,
                bookmark_index=base_case.bookmark_index,
                cut_frame=base_case.cut_frame,
            )
        )

    for wrapper in generate_replay_metamorphic_cases(
        seed_payload,
        stage=stage,
        max_frames=max_frames,
        site_budget=site_budget,
    ):
        stage_data = parse_stage_replay_data(wrapper.payload)[stage - 1]
        if stage_data is None:
            continue
        wrapped_index = find_bookmark_index_at_frame(stage_data.input_bookmarks, base_case.cut_frame)
        if wrapped_index is None:
            continue
        wrapped_delta = build_cut_tail_case(wrapper.payload, stage=stage, bookmark_index=wrapped_index)
        add(
            _composition_case(
                name=f"wrapper-then-delta-{wrapper.name}",
                payload=wrapped_delta.payload,
                order="equivalent-wrapper-then-delta",
                wrapper_name=wrapper.name,
                stage=stage,
                bookmark_index=wrapped_index,
                cut_frame=base_case.cut_frame,
            )
        )

    return cases


def evaluate_cut_tail_composition_case(
    payload: bytes,
    *,
    stage: int,
    cut_tail_masks: list[int],
    max_frames: int | None,
) -> dict[str, object]:
    evaluation = evaluate_replay_metamorphic_payload(
        payload,
        stage=stage,
        baseline_masks=cut_tail_masks,
        max_frames=max_frames,
    )
    if not evaluation.get("relation_holds"):
        return evaluation
    try:
        masks = replay_stage_action_masks(payload, stage, max_frames=max_frames)
    except Exception as exc:
        return {
            **evaluation,
            "relation_holds": False,
            "metamorphic_violation": True,
            "violation_kind": "parser-error",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    action_count_holds = len(masks) == len(cut_tail_masks)
    if action_count_holds:
        return {
            **evaluation,
            "cut_tail_action_count_holds": True,
            "baseline_cut_tail_action_count": len(cut_tail_masks),
            "case_cut_tail_action_count": len(masks),
            "expected_input_error_tick_from_action_count": len(masks) + 2,
        }
    return {
        **evaluation,
        "relation_holds": False,
        "metamorphic_violation": True,
        "violation_kind": "input-exhaustion-point-drift",
        "cut_tail_action_count_holds": False,
        "baseline_cut_tail_action_count": len(cut_tail_masks),
        "case_cut_tail_action_count": len(masks),
        "baseline_expected_input_error_tick_from_action_count": len(cut_tail_masks) + 2,
        "case_expected_input_error_tick_from_action_count": len(masks) + 2,
    }


def temporal_cut_tail_oracle(
    seed_payload: bytes,
    cut_tail_payload: bytes,
    *,
    stage: int,
    cut_frame: int,
    max_frames: int | None,
) -> dict[str, object]:
    seed_masks = replay_stage_action_masks(seed_payload, stage, max_frames=max_frames)
    cut_tail_masks = replay_stage_action_masks(cut_tail_payload, stage, max_frames=max_frames)
    model = replay_input_exhaustion_model(cut_frame)
    expected_tick = int(model["expected_terminal_tick"])
    high_tick = max(expected_tick + 1, max_frames or len(seed_masks) or expected_tick)
    bisection = first_true_index(
        tuple(range(high_tick + 1)),
        lambda tick: int(tick) >= expected_tick,
        max_evaluations=32,
    )
    return {
        "action_first_divergence_frame": first_prefix_divergence(seed_masks, cut_tail_masks),
        "seed_action_count": len(seed_masks),
        "cut_tail_action_count": len(cut_tail_masks),
        "input_exhaustion_model": model,
        "terminal_tick_bisection": {
            "index": bisection.index,
            "tick": bisection.item,
            "evaluations": bisection.evaluations,
            "exhausted_budget": bisection.exhausted_budget,
            "history": bisection.history,
        },
    }


def analyze_replay_cut_tail(
    seed_payload: bytes,
    *,
    stage: int,
    bookmark_index: int | None = None,
    max_frames: int | None = None,
    site_budget: int = 3,
) -> dict[str, object]:
    stage_data = parse_stage_replay_data(seed_payload)[stage - 1]
    if stage_data is None:
        raise ValueError(f"replay payload has no stage {stage} data")
    base_case = build_cut_tail_case(seed_payload, stage=stage, bookmark_index=bookmark_index)
    cut_tail_masks = replay_stage_action_masks(base_case.payload, stage, max_frames=max_frames)
    composition_cases = generate_cut_tail_composition_cases(
        seed_payload,
        stage=stage,
        bookmark_index=base_case.bookmark_index,
        max_frames=max_frames,
        site_budget=site_budget,
    )

    composition_results: list[dict[str, object]] = []
    relation_counts: Counter[str] = Counter()
    for case in composition_cases:
        evaluation = evaluate_cut_tail_composition_case(
            case.payload,
            stage=stage,
            cut_tail_masks=cut_tail_masks,
            max_frames=max_frames,
        )
        relation_counts["holds" if evaluation.get("relation_holds") else "violated"] += 1
        composition_results.append(
            {
                "name": case.name,
                "order": case.order,
                "wrapper_name": case.wrapper_name,
                "stage": case.stage,
                "bookmark_index": case.bookmark_index,
                "cut_frame": case.cut_frame,
                "expected_terminal_tick": case.expected_terminal_tick,
                "payload_sha256": case.payload_sha256,
                "parser_evaluation": evaluation,
            }
        )

    reducer_result = reduce_cut_tail_index(
        seed_payload,
        stage=stage,
        predicate=lambda case: case.expected_terminal_tick >= base_case.expected_terminal_tick,
    )
    return {
        "schema": "danmakufuzz-replay-cut-tail-analysis-v1",
        "stage": stage,
        "seed_payload_sha256": _sha256(seed_payload),
        "candidate_bookmark_indexes": list(candidate_cut_tail_indexes(stage_data.input_bookmarks)),
        "selected": {
            key: value
            for key, value in asdict(base_case).items()
            if key != "payload"
        },
        "model_reducer": {
            "predicate": f"expected_terminal_tick >= {base_case.expected_terminal_tick}",
            "minimal_bookmark_index": reducer_result.item,
            "evaluations": reducer_result.evaluations,
            "exhausted_budget": reducer_result.exhausted_budget,
            "history": reducer_result.history,
        },
        "temporal_oracle": temporal_cut_tail_oracle(
            seed_payload,
            base_case.payload,
            stage=stage,
            cut_frame=base_case.cut_frame,
            max_frames=max_frames,
        ),
        "composition": {
            "relation": "cut-tail-action-stream-and-exhaustion-point-stability-under-equivalent-wrappers",
            "cases_generated": len(composition_cases),
            "relation_counts": dict(sorted(relation_counts.items())),
            "cases": composition_results,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze replay bookmark cut-tail with reducer, metamorphic composition, model, and temporal bisection oracles."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--bookmark-index", type=int)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--site-budget", type=int, default=3)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--emit-cases", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing replay input: {input_path}")
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    seed_payload = input_path.read_bytes()
    report = analyze_replay_cut_tail(
        seed_payload,
        stage=args.stage,
        bookmark_index=args.bookmark_index,
        max_frames=args.max_frames,
        site_budget=max(1, int(args.site_budget)),
    )
    base_case = build_cut_tail_case(
        seed_payload,
        stage=args.stage,
        bookmark_index=args.bookmark_index,
    )
    (artifact_dir / "seed.rpy").write_bytes(seed_payload)
    (artifact_dir / "cut-tail.rpy").write_bytes(base_case.payload)
    report["input"] = str(input_path)
    report["artifact_dir"] = str(artifact_dir)
    report["cut_tail_replay"] = str((artifact_dir / "cut-tail.rpy").resolve())
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.emit_cases:
        for case in report["composition"]["cases"]:  # type: ignore[index]
            print(json.dumps(case, ensure_ascii=False))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
