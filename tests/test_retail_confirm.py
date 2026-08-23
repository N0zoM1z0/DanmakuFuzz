from pathlib import Path

from danmakufuzz.retail.confirm_case import (
    COLOR_MODE_16BIT_OFFSET,
    WINDOWED_OFFSET,
    _augment_run_report_with_baseline,
    _capture_size_from_xvfb_screen_size,
    _classify_control_observation,
    _classify_retail_outcome,
    _configure_windowed,
    _evaluate_retail_expectation,
    _normalize_retail_startup,
    _payload_from_case_result,
    _progress_verification_is_frame_stall,
    _source_default_config,
    _startup_normalization_command,
    _verify_stage_entry,
)


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


def test_classify_control_observation_downgrades_blank_static_window() -> None:
    census = {
        "windows": [
            {"name": "東方紅魔郷　～ the Embodiment of Scarlet Devil"},
        ]
    }
    low_information_profile = {
        "unique_colors": 2,
        "top_two_color_ratio": 1.0,
    }
    oracle = _classify_control_observation(
        census,
        progress_probe={
            "identical_pixels": True,
            "first_pixel_profile": low_information_profile,
            "second_pixel_profile": low_information_profile,
        },
    )
    assert oracle["classification"] == "game-window-blank-static"
    assert oracle["interesting"] is False


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


def test_classify_control_observation_flags_log_dialog_as_environment_error() -> None:
    census = {
        "windows": [
            {"name": "東方紅魔郷　～ the Embodiment of Scarlet Devil"},
            {"name": "log"},
        ]
    }
    oracle = _classify_control_observation(
        census,
        progress_probe={"identical_pixels": True},
    )
    assert oracle["classification"] == "retail-error-dialog"
    assert oracle["interesting"] is False
    assert oracle["error_titles"] == ["log"]


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


def test_retail_expectation_matches_classification_and_signature() -> None:
    report = {
        "run": {
            "oracle": {"classification": "crash-dialog"},
            "retail_signature_key": "crash-dialog:program-error",
        }
    }
    expectation = _evaluate_retail_expectation(
        report,
        expect_classification="crash-dialog",
        expect_signature_key="crash-dialog:program-error",
    )
    assert expectation["enabled"] is True
    assert expectation["passed"] is True


def test_retail_expectation_reports_mismatch() -> None:
    report = {
        "run": {
            "oracle": {"classification": "game-window-live"},
            "retail_signature_key": "game-window-live",
        }
    }
    expectation = _evaluate_retail_expectation(
        report,
        expect_classification="crash-dialog",
        expect_signature_key=None,
    )
    assert expectation["enabled"] is True
    assert expectation["passed"] is False
    assert expectation["checks"][0]["observed"] == "game-window-live"


def test_configure_windowed_allows_color_mode_override() -> None:
    payload = _source_default_config()

    configured = _configure_windowed(payload, color_mode_16bit=1)

    assert configured[WINDOWED_OFFSET] == 1
    assert configured[COLOR_MODE_16BIT_OFFSET] == 1


def test_configure_windowed_can_preserve_source_color_mode() -> None:
    payload = _source_default_config()

    configured = _configure_windowed(payload, color_mode_16bit=None)

    assert configured[WINDOWED_OFFSET] == 1
    assert configured[COLOR_MODE_16BIT_OFFSET] == payload[COLOR_MODE_16BIT_OFFSET]


def test_capture_size_from_xvfb_screen_size_strips_depth() -> None:
    assert _capture_size_from_xvfb_screen_size("1024x768x16") == "1024x768"


def test_payload_from_case_result_accepts_entry_name_override(tmp_path: Path) -> None:
    override_dir = tmp_path / "override"
    payload_path = override_dir / "data" / "stg6bg.anm"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"anm")

    entry_name, payload, source_payload, source_result = _payload_from_case_result(
        {"override_dir": str(override_dir), "entry_name": "stg6bg.anm"},
        tmp_path / "result.json",
    )

    assert entry_name == "stg6bg.anm"
    assert payload == b"anm"
    assert source_payload == payload_path
    assert source_result == tmp_path / "result.json"


def test_baseline_equivalent_overrides_static_window_interest() -> None:
    run_report = {
        "termination_reason": "game-window-static",
        "oracle": {
            "classification": "game-window-static",
            "interesting": True,
            "sources": ["window-census"],
        },
        "wine_log": {"primary_signature": None},
    }

    augmented = _augment_run_report_with_baseline(
        run_report,
        {"classification": "baseline-equivalent", "interesting": False},
    )

    assert augmented is not None
    assert augmented["termination_reason"] == "retail-baseline-equivalent"
    assert augmented["retail_signature_key"] == "retail-baseline-equivalent"
    assert augmented["oracle"]["classification"] == "retail-baseline-equivalent"
    assert augmented["oracle"]["interesting"] is False


def test_baseline_control_error_stays_uninteresting() -> None:
    run_report = {
        "termination_reason": "retail-control-error",
        "oracle": {
            "classification": "retail-control-error",
            "interesting": False,
            "sources": ["window-census"],
        },
        "wine_log": {"primary_signature": None},
    }

    augmented = _augment_run_report_with_baseline(
        run_report,
        {"classification": "baseline-control-error", "interesting": False},
    )

    assert augmented is not None
    assert augmented["termination_reason"] == "retail-baseline-control-error"
    assert augmented["retail_signature_key"] == "retail-baseline-control-error"
    assert augmented["oracle"]["classification"] == "retail-baseline-control-error"
    assert augmented["oracle"]["interesting"] is False


def test_verify_stage_entry_requires_matching_live_stage() -> None:
    verification = _verify_stage_entry(
        {
            "readable": True,
            "in_menu": False,
            "stage": 1,
            "difficulty": 3,
            "frame": 42,
        },
        expected_stage=1,
        expected_difficulty=3,
    )

    assert verification["verified"] is True
    assert verification["reasons"] == []


def test_verify_stage_entry_rejects_menu_state() -> None:
    verification = _verify_stage_entry(
        {
            "readable": True,
            "in_menu": True,
            "stage": 1,
            "difficulty": 3,
            "frame": 42,
        },
        expected_stage=1,
        expected_difficulty=3,
    )

    assert verification["verified"] is False
    assert "still-in-menu" in verification["reasons"]


def test_progress_verification_frame_stall_requires_only_frame_reasons() -> None:
    assert _progress_verification_is_frame_stall(
        {
            "verified": False,
            "reasons": ["frame-before-minimum"],
            "runtime": {"frame": 955, "stage": 1, "difficulty": 3},
        }
    )
    assert not _progress_verification_is_frame_stall(
        {
            "verified": False,
            "reasons": ["still-in-menu", "frame-before-minimum"],
            "runtime": {"frame": 955, "stage": 1, "difficulty": 3},
        }
    )


def test_startup_normalization_command_uses_noninteractive_sudo() -> None:
    command = _startup_normalization_command(
        sudo=Path("/usr/bin/sudo"),
        gdb=Path("/usr/bin/gdb"),
        process_id=1234,
    )

    assert command[:7] == [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/gdb",
        "-q",
        "-nx",
        "-batch",
        "-p",
    ]
    assert command[7] == "1234"
    assert command[-2] == "-x"
    assert command[-1].endswith("normalize_th06_startup.py")


def test_startup_normalization_off_does_not_attempt_gdb(tmp_path: Path) -> None:
    report = _normalize_retail_startup(
        artifact_dir=tmp_path,
        sudo=Path("/usr/bin/sudo"),
        gdb=Path("/usr/bin/gdb"),
        process_id=1234,
        mode="off",
    )

    assert report["attempted"] is False
    assert report["normalized"] is False
    assert report["required"] is False
