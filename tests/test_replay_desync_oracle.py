from danmakufuzz.semantic.replay_desync_campaign import (
    _first_state_divergence,
    _replay_state_findings,
    _tail_state_delta,
)


def test_first_state_divergence_ignores_input_but_reports_game_state() -> None:
    baseline = [
        {"tick": 1, "game_frame": 1, "input": 0, "player": {"x": 10, "y": 20}, "score": 0},
        {"tick": 2, "game_frame": 2, "input": 0, "player": {"x": 10, "y": 20}, "score": 0},
    ]
    case = [
        {"tick": 1, "game_frame": 1, "input": 1, "player": {"x": 10, "y": 20}, "score": 0},
        {"tick": 2, "game_frame": 2, "input": 1, "player": {"x": 12, "y": 20}, "score": 0},
    ]

    divergence = _first_state_divergence(baseline, case)

    assert divergence is not None
    assert divergence["line"] == 2
    assert "input" not in divergence["fields"]
    assert "player.x" in divergence["fields"]


def test_first_state_divergence_ignores_replay_seed_metadata() -> None:
    baseline = [{"tick": 1, "game_frame": 1, "rng_seed": 7, "rng_generation": 3}]
    case = [{"tick": 1, "game_frame": 1, "rng_seed": 42, "rng_generation": 3}]

    assert _first_state_divergence(baseline, case) is None


def test_replay_state_finding_requires_stable_baseline_divergence() -> None:
    finding = _replay_state_findings(
        {
            "stable": True,
            "diverged_from_baseline": True,
            "first_divergence": {
                "line": 5,
                "baseline_tick": 5,
                "case_tick": 5,
                "baseline_game_frame": 5,
                "case_game_frame": 5,
                "fields": ["player.x", "score"],
            },
        }
    )

    assert [item.kind for item in finding] == ["replay-stable-state-drift"]
    assert "fields=player.x,score" in finding[0].detail


def test_tail_state_delta_reports_length_compatible_tail_changes() -> None:
    baseline = [{"tick": 1, "game_frame": 1, "score": 0}]
    case = [{"tick": 1, "game_frame": 1, "score": 100}]

    delta = _tail_state_delta(baseline, case)

    assert delta is not None
    assert delta["fields"] == ["score"]
