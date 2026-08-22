from danmakufuzz.retail.confirm_case import _classify_control_observation, _classify_retail_outcome


def test_classify_control_observation_flags_static_game_window() -> None:
    census = {
        "windows": [
            {"name": "東方紅魔郷　～ the Embodiment of Scarlet Devil"},
            {"name": "Default IME"},
        ]
    }
    oracle = _classify_control_observation(
        census,
        progress_probe={"identical_pixels": True},
    )
    assert oracle["classification"] == "game-window-static"
    assert oracle["interesting"] is True


def test_classify_control_observation_crash_dialog_wins() -> None:
    census = {
        "windows": [
            {"name": "プログラム エラー"},
            {"name": "東方紅魔郷　～ the Embodiment of Scarlet Devil"},
        ]
    }
    oracle = _classify_control_observation(
        census,
        progress_probe={"identical_pixels": True},
    )
    assert oracle["classification"] == "crash-dialog"
    assert oracle["interesting"] is True


def test_classify_retail_outcome_preserves_static_window_interest() -> None:
    outcome = _classify_retail_outcome(
        window_oracle={"classification": "game-window-static", "interesting": True},
        wine_log={
            "classification": "no-crash-signature",
            "primary_signature": None,
            "normalized_primary_signature": None,
        },
        observed_returncode=None,
        timed_out=True,
    )
    assert outcome["classification"] == "game-window-static"
    assert outcome["interesting"] is True
