from danmakufuzz.parser.replay import (
    REPLAY_STAGE_SENTINEL_FRAME,
    ReplayInputBookmark,
    build_replay_with_stage_slots,
    encode_stage_replay_data,
)
from danmakufuzz.semantic.replay_metamorphic import (
    evaluate_replay_metamorphic_payload,
    generate_replay_metamorphic_cases,
)


def _seed_replay() -> bytes:
    stage_payload = encode_stage_replay_data(
        input_bookmarks=[
            ReplayInputBookmark(frame=0, input_mask=1),
            ReplayInputBookmark(frame=8, input_mask=5),
            ReplayInputBookmark(frame=16, input_mask=0),
            ReplayInputBookmark(frame=24, input_mask=0),
            ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0),
        ],
        random_seed=7,
        power=12,
    )
    return build_replay_with_stage_slots(
        difficulty=3,
        shottype_chara=0,
        stage_payloads_by_slot=[None, stage_payload],
    )


def test_replay_metamorphic_cases_preserve_action_stream() -> None:
    seed = _seed_replay()
    baseline = [1] * 8 + [5] * 8 + [0] * 8

    cases = generate_replay_metamorphic_cases(seed, stage=2, max_frames=24)

    names = {case.name for case in cases}
    assert "zero-duration-shadow-i001-n1" in names
    assert "same-mask-run-split-t4-n1" in names
    assert "post-sentinel-record-shadow" in names
    for case in cases:
        evaluation = evaluate_replay_metamorphic_payload(
            case.payload,
            stage=2,
            baseline_masks=baseline,
            max_frames=24,
        )
        assert evaluation["relation_holds"] is True, case.name
        assert evaluation["metamorphic_violation"] is False, case.name


def test_replay_metamorphic_violation_reports_action_drift() -> None:
    changed_stage = encode_stage_replay_data(
        input_bookmarks=[
            ReplayInputBookmark(frame=0, input_mask=2),
            ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0),
        ],
        random_seed=7,
    )
    payload = build_replay_with_stage_slots(stage_payloads_by_slot=[changed_stage])

    evaluation = evaluate_replay_metamorphic_payload(
        payload,
        stage=1,
        baseline_masks=[1, 1, 1],
        max_frames=3,
    )

    assert evaluation["relation_holds"] is False
    assert evaluation["metamorphic_violation"] is True
    assert evaluation["violation_kind"] == "action-stream-drift"
