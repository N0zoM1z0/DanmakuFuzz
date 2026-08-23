from danmakufuzz.corpus.pbg3 import Pbg3Archive
from danmakufuzz.parser.stage_std_campaign import evaluate_stage_std_payload
from danmakufuzz.parser.stage_std_metamorphic_runtime import (
    DEFAULT_ARCHIVE,
    generate_stage_std_metamorphic_cases,
)
from danmakufuzz.parser.stage_std import parse_stage_std


def test_stage_std_metamorphic_cases_are_generated_for_retail_stage_when_available() -> None:
    if not DEFAULT_ARCHIVE.is_file():
        return
    archive = Pbg3Archive.from_bytes(DEFAULT_ARCHIVE.read_bytes())
    payload = archive.extract("stage6.std")
    baseline = {"input": "stage6.std", **parse_stage_std(payload)}

    cases = generate_stage_std_metamorphic_cases(payload)

    names = {case.name for case in cases}
    assert "header-unk-c-pattern" in names
    assert "stage-name-tail-padding-aa" in names
    assert "song-paths-text-pattern" in names
    for case in cases:
        evaluation = evaluate_stage_std_payload(case.payload, baseline, max_script_instructions=100000)
        assert evaluation["classification"] == "accepted", case.name
