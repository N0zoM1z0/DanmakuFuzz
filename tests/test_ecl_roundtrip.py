from pathlib import Path

from danmakufuzz.ecl_ir.model import EclFile, EclSubroutine, RawInstruction, TimelineInstruction
from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl


def test_roundtrip_preserves_minimal_shape() -> None:
    ecl = EclFile(
        sub_count=1,
        main_count=1,
        timeline_offsets=(0, 0, 0),
        timeline=[
            TimelineInstruction(time=0, arg0=1, opcode=0, size=8, args=b""),
            TimelineInstruction(time=-1, arg0=0, opcode=0, size=8, args=b""),
        ],
        subs=[
            EclSubroutine(
                file_offset=0,
                instructions=[
                    RawInstruction(time=0, opcode=35, offset_to_next=32, unk8=0, skip_for_difficulty=0, unk_a=0, unk_b=0, args=b"\x00" * 20),
                    RawInstruction(time=10, opcode=36, offset_to_next=12, unk8=0, skip_for_difficulty=0, unk_a=0, unk_b=0, args=b""),
                ],
            )
        ],
    )
    blob = serialize_ecl(ecl)
    reparsed = parse_ecl(blob)
    assert reparsed.sub_count == 1
    assert len(reparsed.timeline) == 2
    assert len(reparsed.subs) == 1
    assert reparsed.subs[0].instructions[0].opcode == 35


def test_retail_ecl_corpus_parses_when_available() -> None:
    corpus_dir = Path("reference/corpus/ecl/original")
    if not corpus_dir.is_dir():
        return
    parsed = 0
    for path in sorted(corpus_dir.glob("ecldata*.ecl")):
        ecl = parse_ecl(path.read_bytes())
        assert ecl.sub_count == len(ecl.subs)
        assert ecl.timeline
        parsed += 1
    assert parsed == 7
