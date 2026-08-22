from pathlib import Path

from danmakufuzz.interestingness.rules import score_trace


def test_score_trace_flags_non_finite(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"frame": 0, "x": NaN, "bullets": []}\n', encoding="utf-8")
    findings = score_trace(trace)
    assert any(finding.kind == "non-finite" for finding in findings)
