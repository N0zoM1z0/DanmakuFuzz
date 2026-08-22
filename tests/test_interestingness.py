import json
from pathlib import Path

from danmakufuzz.interestingness.rules import score_trace, score_trace_differential


def test_score_trace_flags_non_finite(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"frame": 0, "x": NaN, "bullets": []}\n', encoding="utf-8")
    findings = score_trace(trace)
    assert any(finding.kind == "non-finite" for finding in findings)


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
