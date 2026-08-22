from pathlib import Path

from danmakufuzz.semantic.payload_mutants import generate_structural_mutants
from danmakufuzz.semantic.ecl_campaign import classify_process_result, infer_stage_from_ecl_name


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
