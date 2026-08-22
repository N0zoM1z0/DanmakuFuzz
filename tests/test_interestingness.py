import json
from pathlib import Path

from danmakufuzz.interestingness.rules import score_trace, score_trace_differential


def test_score_trace_flags_non_finite(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"frame": 0, "x": NaN, "bullets": []}\n', encoding="utf-8")
    findings = score_trace(trace)
    assert any(finding.kind == "non-finite" for finding in findings)


def test_score_trace_uses_game_frame_for_stall_detection(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    rows = [
        {"game_frame": 77, "bullets": []},
        {"game_frame": 77, "bullets": []},
        {"game_frame": 77, "bullets": []},
    ]
    trace.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    findings = score_trace(trace, stall_window=2)
    assert any(finding.kind == "stalled-frame" for finding in findings)


def test_score_trace_differential_flags_sustained_bullet_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    case = tmp_path / "case.jsonl"
    baseline_rows = []
    case_rows = []
    for tick in range(1, 9):
        baseline_rows.append(
            {"tick": tick, "terminal_reason": None, "bullets": [{} for _ in range(12)], "lasers": [], "enemies": [], "score": 0, "lives": 2, "bombs": 3}
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
