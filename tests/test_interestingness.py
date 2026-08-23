import json
from pathlib import Path

from danmakufuzz.interestingness.rules import (
    Finding,
    first_stall_event,
    score_trace,
    score_trace_differential,
    score_trace_differential_records,
    score_trace_path_with_baseline,
    suppress_baseline_stall_findings,
)


def test_score_trace_flags_non_finite(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"frame": 0, "x": NaN, "bullets": []}\n', encoding="utf-8")
    findings = score_trace(trace)
    assert any(finding.kind == "non-finite" for finding in findings)


def test_score_trace_flags_negative_timeline_next_time(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "tick": 1347,
                "game_frame": 1345,
                "ecl_timeline": {"time": 1345, "next_time": -9163},
                "bullets": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    findings = score_trace(trace)
    finding = next(finding for finding in findings if finding.kind == "timeline-next-time-negative")
    assert "ecl_timeline.next_time=-9163" in finding.detail
    assert "tick=1347" in finding.detail
    assert "game_frame=1345" in finding.detail


def test_score_trace_uses_game_frame_for_stall_detection(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    rows = [
        {
            "tick": 100,
            "game_frame": 77,
            "rng_generation": 555,
            "stage_vm": {"loaded": False, "script_time": 77, "instruction_index": 4},
            "ecl_timeline": {"time": 77, "next_time": 80},
            "bullets": [],
        },
        {
            "tick": 101,
            "game_frame": 77,
            "rng_generation": 555,
            "stage_vm": {"loaded": False, "script_time": 77, "instruction_index": 4},
            "ecl_timeline": {"time": 77, "next_time": 80},
            "bullets": [],
        },
        {
            "tick": 102,
            "game_frame": 77,
            "rng_generation": 555,
            "stage_vm": {"loaded": False, "script_time": 77, "instruction_index": 4},
            "ecl_timeline": {"time": 77, "next_time": 80},
            "bullets": [],
        },
    ]
    trace.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    findings = score_trace(trace, stall_window=2)
    progress = next(finding for finding in findings if finding.kind == "stalled-progress")
    assert "stage_vm.loaded=False" in progress.detail
    assert "ecl_timeline.time=77" in progress.detail
    assert any(finding.kind == "stalled-frame" for finding in findings)


def test_first_stall_event_reports_tick_and_frame(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    rows = [
        {"tick": 10, "game_frame": 5, "bullets": []},
        {"tick": 11, "game_frame": 5, "bullets": []},
        {"tick": 12, "game_frame": 5, "bullets": []},
    ]
    trace.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    event = first_stall_event(trace, stall_window=2)
    assert event is not None
    assert event.frame == 5
    assert event.tick == 12


def test_suppress_baseline_stall_findings_drops_similar_baseline_stall(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = [{"tick": tick, "game_frame": 100 if tick >= 50 else tick, "bullets": []} for tick in range(1, 80)]
    case_rows = [{"tick": tick, "game_frame": 104 if tick >= 54 else tick, "bullets": []} for tick in range(1, 84)]
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    filtered = suppress_baseline_stall_findings(
        [
            Finding("stalled-progress", "frame=104 ..."),
            Finding("stalled-frame", "frame 104 repeated >= 8 times"),
            Finding("score-drift", "tick 60 baseline=100 case=200"),
        ],
        case_trace=case,
        baseline_trace=baseline,
        stall_window=8,
        earlier_tick_margin=16,
        earlier_frame_margin=16,
    )
    assert filtered == [Finding("score-drift", "tick 60 baseline=100 case=200")]


def test_suppress_baseline_stall_findings_keeps_earlier_case_stall(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = [{"tick": tick, "game_frame": 200 if tick >= 100 else tick, "bullets": []} for tick in range(1, 130)]
    case_rows = [{"tick": tick, "game_frame": 80 if tick >= 40 else tick, "bullets": []} for tick in range(1, 90)]
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = [
        Finding("stalled-progress", "frame=80 ..."),
        Finding("stalled-frame", "frame 80 repeated >= 8 times"),
    ]
    filtered = suppress_baseline_stall_findings(
        findings,
        case_trace=case,
        baseline_trace=baseline,
        stall_window=8,
        earlier_tick_margin=16,
        earlier_frame_margin=16,
    )
    assert filtered == findings


def test_score_trace_differential_flags_sustained_bullet_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = []
    case_rows = []
    for tick in range(1, 9):
        baseline_rows.append(
            {"tick": tick, "terminal_reason": None, "bullets": [{} for _ in range(80)], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        )
        case_rows.append(
            {"tick": tick, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        )
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_differential(case, baseline, sustained_window=4, bullet_drift_threshold=8)
    assert any(finding.kind == "bullet-count-drift" for finding in findings)


def test_score_trace_differential_suppresses_weak_bullet_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = []
    case_rows = []
    for tick in range(1, 9):
        baseline_rows.append(
            {"tick": tick, "terminal_reason": None, "bullets": [{} for _ in range(71)], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        )
        case_rows.append(
            {"tick": tick, "terminal_reason": None, "bullets": [{} for _ in range(59)], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        )
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_differential(case, baseline, sustained_window=4, bullet_drift_threshold=8)
    assert not any(finding.kind == "bullet-count-drift" for finding in findings)


def test_score_trace_differential_keeps_bullet_collapse(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = []
    case_rows = []
    for tick in range(1, 9):
        baseline_rows.append(
            {"tick": tick, "terminal_reason": None, "bullets": [{} for _ in range(20)], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        )
        case_rows.append(
            {"tick": tick, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        )
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_differential(case, baseline, sustained_window=4, bullet_drift_threshold=8)
    assert any(finding.kind == "bullet-count-drift" for finding in findings)


def test_score_trace_differential_flags_shortfall(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = [
        {"tick": tick, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        for tick in range(1, 11)
    ]
    case_rows = [
        {"tick": tick, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
        for tick in range(1, 3)
    ]
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_differential(case, baseline, shortfall_threshold=4)
    assert any(finding.kind == "trace-shortfall" for finding in findings)


def test_score_trace_differential_flags_terminal_reason_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = [
        {"tick": 1, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3},
        {"tick": 2, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3},
        {"tick": 311, "terminal_reason": "physical-hit", "bullets": [], "lasers": [], "enemies": [], "score": 2450, "lives": 1, "bombs": 3},
    ]
    case_rows = [
        {"tick": 1, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3},
        {"tick": 2, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3},
        {"tick": 600, "terminal_reason": "tick-limit", "bullets": [], "lasers": [], "enemies": [], "score": 5860, "lives": 2, "bombs": 3},
    ]
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_differential(case, baseline)
    assert any(finding.kind == "terminal-reason-drift" for finding in findings)


def test_score_trace_path_with_baseline_flags_terminal_reason_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = [
        {"tick": 1, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3},
        {"tick": 311, "terminal_reason": "physical-hit", "bullets": [], "lasers": [], "enemies": [], "score": 2450, "lives": 1, "bombs": 3},
    ]
    case_rows = [
        {"tick": 1, "terminal_reason": None, "bullets": [], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3},
        {"tick": 600, "terminal_reason": "tick-limit", "bullets": [], "lasers": [], "enemies": [], "score": 5860, "lives": 2, "bombs": 3},
    ]
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_path_with_baseline(case, baseline_records=baseline_rows)
    assert any(finding.kind == "terminal-reason-drift" for finding in findings)


def test_score_trace_differential_flags_item_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = []
    case_rows = []
    for tick in range(1, 9):
        baseline_rows.append(
            {"tick": tick, "terminal_reason": None, "items": [{"type": 1} for _ in range(6)], "bullets": [], "lasers": [], "enemies": [], "score": 0, "power": 0, "point_items_stage": 0, "lives": 2, "bombs": 3}
        )
        case_rows.append(
            {"tick": tick, "terminal_reason": None, "items": [], "bullets": [], "lasers": [], "enemies": [], "score": 0, "power": 0, "point_items_stage": 0, "lives": 2, "bombs": 3}
        )
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_differential(case, baseline, sustained_window=4, item_drift_threshold=4)
    assert any(finding.kind == "item-count-drift" for finding in findings)


def test_score_trace_differential_flags_stage_and_boss_state_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = []
    case_rows = []
    for tick in range(1, 9):
        baseline_rows.append(
            {
                "tick": tick,
                "terminal_reason": None,
                "bullets": [],
                "lasers": [],
                "enemies": [],
                "score": 0,
                "power": 0,
                "point_items_stage": 0,
                "lives": 2,
                "bombs": 3,
                "stage_vm": {
                    "loaded": True,
                    "script_time": tick,
                    "instruction_index": 10,
                    "unpause_flag": 0,
                    "spellcard_state": 0,
                    "spellcard_ticks": 0,
                },
                "ecl_timeline": {"time": tick, "next_time": 440},
                "boss_ui": {
                    "present": False,
                    "ecl_lives": 0,
                    "spell_seconds": 0,
                    "health1": 0.0,
                    "health2": 0.0,
                    "opacity": 0,
                },
                "spellcard": {
                    "active": 0,
                    "capturing": False,
                    "used_bomb": False,
                    "idx": 0,
                    "capture_score": 0,
                },
            }
        )
        case_rows.append(
            {
                "tick": tick,
                "terminal_reason": None,
                "bullets": [],
                "lasers": [],
                "enemies": [],
                "score": 0,
                "power": 0,
                "point_items_stage": 0,
                "lives": 2,
                "bombs": 3,
                "stage_vm": {
                    "loaded": True,
                    "script_time": tick + 20,
                    "instruction_index": 17,
                    "unpause_flag": 1,
                    "spellcard_state": 1,
                    "spellcard_ticks": tick,
                },
                "ecl_timeline": {"time": tick + 20, "next_time": 512},
                "boss_ui": {
                    "present": True,
                    "ecl_lives": 2,
                    "spell_seconds": 33,
                    "health1": 0.5,
                    "health2": 0.25,
                    "opacity": 255,
                },
                "spellcard": {
                    "active": 1,
                    "capturing": True,
                    "used_bomb": False,
                    "idx": 7,
                    "capture_score": 12345,
                },
            }
        )
    baseline.write_text("\n".join(json.dumps(row) for row in baseline_rows) + "\n", encoding="utf-8")
    case.write_text("\n".join(json.dumps(row) for row in case_rows) + "\n", encoding="utf-8")
    findings = score_trace_differential(case, baseline, sustained_window=4)
    kinds = {finding.kind for finding in findings}
    assert "stage-script-drift" in kinds
    assert "ecl-timeline-drift" in kinds
    assert "boss-ui-drift" in kinds
    assert "spellcard-drift" in kinds
    assert "boss-health-drift" in kinds


def test_score_trace_differential_can_align_by_semantic_keys() -> None:
    baseline_rows = []
    case_rows = []
    for tick in range(1, 7):
        baseline_rows.append(
            {
                "tick": tick,
                "game_frame": tick,
                "terminal_reason": None,
                "bullets": [],
                "lasers": [],
                "enemies": [],
                "score": 0,
                "lives": 2,
                "bombs": 3,
                "stage_vm": {"loaded": True, "script_time": tick, "instruction_index": 10},
                "ecl_timeline": {"time": tick, "next_time": tick + 10},
            }
        )
        semantic_time = max(1, tick - 1)
        case_rows.append(
            {
                "tick": tick,
                "game_frame": semantic_time,
                "terminal_reason": None,
                "bullets": [],
                "lasers": [],
                "enemies": [],
                "score": 0,
                "lives": 2,
                "bombs": 3,
                "stage_vm": {"loaded": True, "script_time": semantic_time, "instruction_index": 10},
                "ecl_timeline": {"time": semantic_time, "next_time": semantic_time + 10},
            }
        )

    row_findings = score_trace_differential_records(
        case_rows,
        baseline_rows,
        alignment="row",
        sustained_window=2,
    )
    assert any(finding.kind == "stage-script-drift" for finding in row_findings)
    assert any(finding.kind == "ecl-timeline-drift" for finding in row_findings)

    for alignment in ("game_frame", "stage_vm_pc", "timeline_time"):
        aligned_findings = score_trace_differential_records(
            case_rows,
            baseline_rows,
            alignment=alignment,
            sustained_window=2,
        )
        kinds = {finding.kind for finding in aligned_findings}
        assert "stage-script-drift" not in kinds
        assert "ecl-timeline-drift" not in kinds
