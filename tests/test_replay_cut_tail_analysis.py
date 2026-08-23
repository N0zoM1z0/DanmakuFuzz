from danmakufuzz.parser.replay import (
    REPLAY_STAGE_SENTINEL_FRAME,
    ReplayInputBookmark,
    build_replay_with_stage_slots,
    encode_stage_replay_data,
    replay_stage_action_masks,
)
from danmakufuzz.semantic.replay_cut_tail_analysis import (
    analyze_replay_cut_tail,
    build_cut_tail_case,
    cut_tail_bookmarks,
    generate_cut_tail_composition_cases,
    replay_input_exhaustion_model,
)


def _seed_replay() -> bytes:
    stage_payload = encode_stage_replay_data(
        input_bookmarks=[
            ReplayInputBookmark(frame=0, input_mask=1),
            ReplayInputBookmark(frame=8, input_mask=5),
            ReplayInputBookmark(frame=16, input_mask=0),
            ReplayInputBookmark(frame=24, input_mask=7),
            ReplayInputBookmark(frame=32, input_mask=0),
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


def test_cut_tail_bookmarks_minimize_to_input_exhaustion_point() -> None:
    bookmarks = [
        ReplayInputBookmark(frame=0, input_mask=1),
        ReplayInputBookmark(frame=8, input_mask=5),
        ReplayInputBookmark(frame=16, input_mask=0),
        ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0),
    ]

    reduced = cut_tail_bookmarks(bookmarks, index=1)

    assert reduced == (
        ReplayInputBookmark(frame=0, input_mask=1),
        ReplayInputBookmark(frame=8, input_mask=0),
        ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0),
    )
    assert replay_input_exhaustion_model(8)["expected_terminal_tick"] == 10


def test_build_cut_tail_case_preserves_prefix_and_models_terminal_tick() -> None:
    case = build_cut_tail_case(_seed_replay(), stage=2)

    assert case.bookmark_index == 1
    assert case.cut_frame == 8
    assert case.expected_terminal_tick == 10
    assert replay_stage_action_masks(case.payload, 2, max_frames=32) == [1] * 8


def test_cut_tail_composition_wrappers_preserve_cut_tail_action_stream() -> None:
    seed = _seed_replay()
    cut_tail = build_cut_tail_case(seed, stage=2)
    baseline_masks = replay_stage_action_masks(cut_tail.payload, 2, max_frames=32)

    cases = generate_cut_tail_composition_cases(seed, stage=2, max_frames=32)

    assert {case.order for case in cases} == {
        "delta-then-equivalent-wrapper",
        "equivalent-wrapper-then-delta",
    }
    for case in cases:
        assert replay_stage_action_masks(case.payload, 2, max_frames=32) == baseline_masks


def test_analyze_replay_cut_tail_reports_reducer_composition_and_temporal_oracle() -> None:
    report = analyze_replay_cut_tail(_seed_replay(), stage=2, max_frames=32)

    assert report["selected"]["bookmark_index"] == 1
    assert report["model_reducer"]["minimal_bookmark_index"] == 1
    assert report["temporal_oracle"]["input_exhaustion_model"]["expected_terminal_tick"] == 10
    assert report["composition"]["cases_generated"] > 0
    assert report["composition"]["relation_counts"] == {"holds": report["composition"]["cases_generated"]}
