import ctypes
import struct

from danmakufuzz.ecl_ir.model import EclFile, EclSubroutine, RawInstruction, TimelineInstruction
from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl_canonical
from danmakufuzz.findings.closure_analysis import (
    apply_anm_table_delta,
    apply_ecl_timeline_delta,
    describe_anm_table_deltas,
    describe_ecl_semantic_deltas,
    first_temporal_divergence,
)
from danmakufuzz.parser.anm import AnmRawEntry


def _minimal_ecl() -> EclFile:
    return EclFile(
        sub_count=1,
        main_count=0,
        timeline_offsets=(0, 0, 0),
        timeline=[
            TimelineInstruction(time=0, arg0=0, opcode=1, size=8),
            TimelineInstruction(time=-1, arg0=0, opcode=0, size=8),
        ],
        subs=[
            EclSubroutine(
                file_offset=0,
                instructions=[
                    RawInstruction(
                        time=0,
                        opcode=0,
                        offset_to_next=12,
                        unk8=0,
                        skip_for_difficulty=0,
                        unk_a=0,
                        unk_b=0,
                    )
                ],
            )
        ],
    )


def test_ecl_closure_detects_and_rebuilds_single_timeline_delta() -> None:
    original = _minimal_ecl()
    mutant = original.clone()
    mutant.timeline[1].arg0 = 256

    deltas = describe_ecl_semantic_deltas(original, mutant)

    assert deltas == [
        {
            "domain": "ecl",
            "kind": "timeline-field",
            "timeline_index": 1,
            "field": "arg0",
            "original": 0,
            "mutated": 256,
            "instruction": {
                "original_time": -1,
                "mutated_time": -1,
                "original_arg0": 0,
                "mutated_arg0": 256,
                "original_opcode": 0,
                "mutated_opcode": 0,
                "original_size": 8,
                "mutated_size": 8,
            },
        }
    ]

    rebuilt = apply_ecl_timeline_delta(serialize_ecl_canonical(original), deltas[0])

    assert parse_ecl(rebuilt).timeline[1].arg0 == 256


def _minimal_anm_payload() -> bytes:
    entry = AnmRawEntry()
    entry.numSprites = 1
    entry.numScripts = 1
    payload = bytearray(bytes(entry))
    payload += struct.pack("<I", 176)
    payload += struct.pack("<II", 0, 256)
    payload += b"\x00" * 300
    assert len(payload) > ctypes.sizeof(AnmRawEntry) + 12
    return bytes(payload)


def test_anm_closure_detects_and_rebuilds_table_cell_delta() -> None:
    original = _minimal_anm_payload()
    mutant = bytearray(original)
    struct.pack_into("<I", mutant, ctypes.sizeof(AnmRawEntry), 0)

    deltas = describe_anm_table_deltas(original, bytes(mutant))

    assert deltas == [
        {
            "domain": "anm",
            "kind": "table-u32",
            "table": "sprite_offsets",
            "index": 0,
            "field": "offset",
            "byte_offset": ctypes.sizeof(AnmRawEntry),
            "original": 176,
            "mutated": 0,
        }
    ]
    assert apply_anm_table_delta(original, deltas[0]) == bytes(mutant)


def test_temporal_divergence_ignores_input_but_reports_state_fields() -> None:
    baseline = [
        {"tick": 1, "game_frame": 1, "input": 0, "anm_metrics": {"execute_script_calls": 10}},
        {"tick": 2, "game_frame": 2, "input": 0, "anm_metrics": {"execute_script_calls": 20}},
    ]
    case = [
        {"tick": 1, "game_frame": 1, "input": 1, "anm_metrics": {"execute_script_calls": 10}},
        {"tick": 2, "game_frame": 2, "input": 1, "anm_metrics": {"execute_script_calls": 19}},
    ]

    divergence = first_temporal_divergence(baseline, case)

    assert divergence is not None
    assert divergence["line"] == 2
    assert divergence["fields"] == ["anm_metrics.execute_script_calls"]


def test_temporal_divergence_reports_trace_length_shortfall() -> None:
    baseline = [{"tick": 1, "game_frame": 1}, {"tick": 2, "game_frame": 2}]
    case = [{"tick": 1, "game_frame": 1}]

    divergence = first_temporal_divergence(baseline, case)

    assert divergence is not None
    assert divergence["line"] == 2
    assert divergence["fields"] == ["trace_length"]
    assert divergence["baseline_length"] == 2
    assert divergence["case_length"] == 1
