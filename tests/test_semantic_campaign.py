from pathlib import Path

from danmakufuzz.ecl_ir.model import EclFile, EclSubroutine, RawInstruction
from danmakufuzz.ecl_ir.mutators import generate_exploration_mutants, generate_targeted_mutants
from danmakufuzz.interestingness.rules import Finding
from danmakufuzz.semantic.ecl_campaign import (
    DEFAULT_CORE_NAME_FILTERS,
    DEFAULT_BOSS_NAME_FILTERS,
    LONG_ACTION_FILE,
    classify_process_result,
    filter_mutants_by_name,
    infer_stage_from_ecl_name,
    mutant_bucket_key,
    mutant_family,
    practice_stage_supported,
    resolve_campaign_profile,
    resolve_mutant_limit,
    resolve_selection_mode,
    select_diverse_mutants,
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


def test_mutant_family_prefers_filter_match() -> None:
    mutant = PayloadMutant(name="bullet-count1-zero", payload=b"", source="ir")
    assert mutant_family(mutant, ["bullet-count", "shoot-interval-"]) == "bullet-count"


def test_select_diverse_mutants_round_robins_across_families() -> None:
    mutants = [
        PayloadMutant(name="bullet-count1-zero", payload=b"", source="ir"),
        PayloadMutant(name="bullet-count2-zero", payload=b"", source="ir"),
        PayloadMutant(name="bullet-count1-negative-one", payload=b"", source="ir"),
        PayloadMutant(name="shoot-interval-zero", payload=b"", source="ir"),
        PayloadMutant(name="shoot-interval-one", payload=b"", source="ir"),
        PayloadMutant(name="time-set-zero", payload=b"", source="ir"),
    ]
    selected = select_diverse_mutants(
        mutants,
        limit=4,
        family_filters=["bullet-count", "shoot-interval-", "time-set-"],
    )
    assert [mutant.name for mutant in selected] == [
        "bullet-count1-zero",
        "shoot-interval-zero",
        "time-set-zero",
        "bullet-count2-zero",
    ]


def test_select_diverse_mutants_site_mode_spreads_across_sites() -> None:
    mutants = [
        PayloadMutant(name="jump-offset-sampled-1", payload=b"", source="ir", path=(4, 19)),
        PayloadMutant(name="jump-offset-sampled-2", payload=b"", source="ir", path=(4, 19)),
        PayloadMutant(name="call-sub-sampled-1", payload=b"", source="ir", path=(9, 15)),
        PayloadMutant(name="call-sub-sampled-2", payload=b"", source="ir", path=(9, 15)),
        PayloadMutant(name="jump-offset-sampled-3", payload=b"", source="ir", path=(13, 33)),
    ]
    selected = select_diverse_mutants(
        mutants,
        limit=3,
        family_filters=["jump-offset-", "call-sub-"],
        selection_mode="site",
    )
    assert [mutant.name for mutant in selected] == [
        "jump-offset-sampled-1",
        "call-sub-sampled-1",
        "jump-offset-sampled-3",
    ]


def test_resolve_selection_mode_auto_prefers_site_for_exploration() -> None:
    assert resolve_selection_mode(mutation_mode="deterministic", selection_mode="auto") == "family"
    assert resolve_selection_mode(mutation_mode="exploration", selection_mode="auto") == "site"


def test_resolve_mutant_limit_applies_auto_budget_for_exploration() -> None:
    resolved = resolve_mutant_limit(
        mutation_mode="exploration",
        requested_limit=None,
        full_mutant_set=False,
        default_exploration_limit=32,
    )
    assert resolved == {
        "requested_limit": None,
        "effective_limit": 32,
        "auto_applied": True,
        "reason": "exploration-auto-budget",
    }


def test_resolve_mutant_limit_preserves_explicit_limit() -> None:
    resolved = resolve_mutant_limit(
        mutation_mode="exploration",
        requested_limit=96,
        full_mutant_set=False,
        default_exploration_limit=32,
    )
    assert resolved == {
        "requested_limit": 96,
        "effective_limit": 96,
        "auto_applied": False,
        "reason": "explicit-limit",
    }


def test_resolve_mutant_limit_full_mutant_set_disables_auto_budget() -> None:
    resolved = resolve_mutant_limit(
        mutation_mode="exploration",
        requested_limit=None,
        full_mutant_set=True,
        default_exploration_limit=32,
    )
    assert resolved == {
        "requested_limit": None,
        "effective_limit": None,
        "auto_applied": False,
        "reason": "full-mutant-set",
    }


def test_mutant_bucket_key_family_site_combines_dimensions() -> None:
    mutant = PayloadMutant(name="jump-offset-sampled-1", payload=b"", source="ir", path=(4, 19))
    assert mutant_bucket_key(
        mutant,
        family_filters=["jump-offset-"],
        selection_mode="family-site",
    ) == "jump-offset|s04:i0019"


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


def test_generate_exploration_mutants_is_seeded_for_time_set() -> None:
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
                        opcode=123,
                        offset_to_next=16,
                        unk8=0,
                        skip_for_difficulty=0,
                        unk_a=0,
                        unk_b=0,
                        args=(120).to_bytes(4, "little", signed=True),
                    ),
                ],
            )
        ],
    )
    first = generate_exploration_mutants(ecl, random_seed=17, samples_per_site=4)
    second = generate_exploration_mutants(ecl, random_seed=17, samples_per_site=4)
    third = generate_exploration_mutants(ecl, random_seed=18, samples_per_site=4)

    first_names = [mutant.name for mutant in first]
    second_names = [mutant.name for mutant in second]
    third_names = [mutant.name for mutant in third]

    assert first_names == second_names
    assert first_names != third_names
    assert all(name.startswith("time-set-sampled-") for name in first_names)
    assert all(mutant.metadata is not None for mutant in first)
