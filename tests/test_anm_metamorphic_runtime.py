from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive
from danmakufuzz.parser.anm import DEFAULT_ARCHIVE
from danmakufuzz.parser.anm_metamorphic_runtime import generate_anm_metamorphic_cases


def test_generate_anm_metamorphic_cases_for_retail_entry_when_available() -> None:
    archive_path = Path(DEFAULT_ARCHIVE)
    if not archive_path.is_file():
        return
    payload = Pbg3Archive.from_bytes(archive_path.read_bytes()).extract("stg6bg.anm")

    cases = generate_anm_metamorphic_cases(payload)
    names = {case.name for case in cases}

    assert "header-unk1-pattern" in names
    assert "header-unk2-pattern" in names
    assert "script-table-swap-first-two" in names
    assert "script-table-reverse" in names
