from pathlib import Path

from danmakufuzz.ecl_ir.model import EclFile, EclSubroutine, RawInstruction
from danmakufuzz.ecl_ir.mutators import generate_targeted_mutants
from danmakufuzz.interestingness.rules import Finding
from danmakufuzz.semantic.ecl_campaign import (
    DEFAULT_CORE_NAME_FILTERS,
    DEFAULT_BOSS_NAME_FILTERS,
    LONG_ACTION_FILE,
    classify_process_result,
    filter_mutants_by_name,
    infer_stage_from_ecl_name,
    practice_stage_supported,
    resolve_campaign_profile,
)
from danmakufuzz.semantic.minimize_case import TargetFinding, _ddmin_delete
from danmakufuzz.semantic.payload_mutants import PayloadMutant
from danmakufuzz.semantic.payload_mutants import generate_structural_mutants


def test_infer_stage_from_ecl_name() -> None:
    assert infer_stage_from_ecl_name(Path("ecldata6.ecl")) == 6


def test_classify_process_result_flags_signal() -> None:
    findings = classify_process_result(-11, timed_out=False)
    assert findings[0].kind == "process-signal"


def test_classify_process_result_flags_timeout() -> None:
    findings = classify_process_result(None, timed_out=True)
    assert findings[0].kind == "timeout"


def test_generate_structural_mutants_includes_empty_payload() -> None:
    mutants = generate_structural_mutants(b"\x01\x00\x00\x00" + b"\x00" * 28)
    assert mutants[0].name == "struct-empty-file"
    assert mutants[0].payload == b""


def test_filter_mutants_by_multiple_name_filters() -> None:
    mutants = [
        PayloadMutant(name="boss-timer-zero", payload=b"", source="ir"),
        PayloadMutant(name="move-time-zero", payload=b"", source="ir"),
        PayloadMutant(name="time-set-zero", payload=b"", source="ir"),
    ]
    filtered = filter_mutants_by_name(mutants, ["boss-timer-", "time-set-"])
    assert [mutant.name for mutant in filtered] == ["boss-timer-zero", "time-set-zero"]


def test_resolve_campaign_profile_boss_defaults() -> None:
    resolved = resolve_campaign_profile(
        profile="boss",
        action_file=Path("config/headless_baseline_actions.txt"),
        max_ticks=600,
        timeout_seconds=5.0,
        continue_after_hit=False,
        case_prefix="campaign",
        name_filters=None,
    )
    assert resolved["action_file"] == LONG_ACTION_FILE
    assert resolved["max_ticks"] == 1800
    assert resolved["timeout_seconds"] == 15.0
    assert resolved["continue_after_hit"] is True
    assert resolved["case_prefix"] == "boss"
    assert resolved["name_filters"] == list(DEFAULT_BOSS_NAME_FILTERS)


def test_resolve_campaign_profile_core_defaults() -> None:
    resolved = resolve_campaign_profile(
        profile="core",
        action_file=Path("config/headless_baseline_actions.txt"),
        max_ticks=600,
        timeout_seconds=5.0,
        continue_after_hit=False,
        case_prefix="campaign",
        name_filters=None,
    )
    assert resolved["action_file"] == Path("config/headless_baseline_actions.txt").resolve()
    assert resolved["max_ticks"] == 600
    assert resolved["timeout_seconds"] == 5.0
    assert resolved["continue_after_hit"] is False
    assert resolved["case_prefix"] == "core"
    assert resolved["name_filters"] == list(DEFAULT_CORE_NAME_FILTERS)


def test_practice_stage_supported_skips_stage_seven() -> None:
    assert practice_stage_supported(6) is True
    assert practice_stage_supported(7) is False


def test_target_finding_matches_kind_and_detail() -> None:
    target = TargetFinding(kind="process-signal", detail="SIGSEGV")
    assert target.matches([Finding("process-signal", "SIGSEGV")])
    assert not target.matches([Finding("process-signal", "SIGABRT")])


def test_ddmin_delete_reduces_to_single_required_byte() -> None:
    evaluations = [0]
    minimized = _ddmin_delete(
        b"abcXdef",
        lambda payload: payload.count(b"X") == 1,
        max_evaluations=64,
        evaluation_counter=evaluations,
    )
    assert minimized == b"X"


def test_generate_targeted_mutants_includes_semantic_interval_and_move_time_mutants() -> None:
    ecl = EclFile(
        sub_count=1,
        main_count=0,
        timeline_offsets=(0, 0, 0),
        timeline=[],
        subs=[
            EclSubroutine(
                file_offset=0,
                instructions=[
                    RawInstruction(
                        time=0,
                        opcode=76,
                        offset_to_next=16,
                        unk8=0,
                        skip_for_difficulty=0,
                        unk_a=0,
                        unk_b=0,
                        args=(5).to_bytes(4, "little", signed=True),
                    ),
                    RawInstruction(
                        time=0,
                        opcode=57,
                        offset_to_next=28,
                        unk8=0,
                        skip_for_difficulty=0,
                        unk_a=0,
                        unk_b=0,
                        args=b"\x00" * 16,
                    ),
                ],
            )
        ],
    )
    names = {mutant.name for mutant in generate_targeted_mutants(ecl)}
    assert {"shoot-interval-zero", "shoot-interval-one", "shoot-interval-negative-one"} <= names
    assert {"move-time-zero", "move-time-negative-one"} <= names


def test_generate_targeted_mutants_includes_drop_item_mutants() -> None:
    ecl = EclFile(
        sub_count=1,
        main_count=0,
        timeline_offsets=(0, 0, 0),
        timeline=[],
        subs=[
            EclSubroutine(
                file_offset=0,
                instructions=[
                    RawInstruction(
                        time=0,
                        opcode=119,
                        offset_to_next=16,
                        unk8=0,
                        skip_for_difficulty=0,
                        unk_a=0,
                        unk_b=0,
                        args=(3).to_bytes(4, "little", signed=True),
                    ),
                    RawInstruction(
                        time=0,
                        opcode=124,
                        offset_to_next=16,
                        unk8=0,
                        skip_for_difficulty=0,
                        unk_a=0,
                        unk_b=0,
                        args=(1).to_bytes(4, "little", signed=True),
                    ),
                    RawInstruction(
                        time=0,
                        opcode=121,
                        offset_to_next=16,
                        unk8=0,
                        skip_for_difficulty=0,
                        unk_a=0,
                        unk_b=0,
                        args=(0).to_bytes(4, "little", signed=True),
                    ),
                ],
            )
        ],
    )
    names = {mutant.name for mutant in generate_targeted_mutants(ecl)}
    assert {"drop-items-32", "drop-item-id-life", "exinscall-17"} <= names
