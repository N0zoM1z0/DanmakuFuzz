from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path

from .common import load_input_bytes


class RawStageHeader(ctypes.LittleEndianStructure):
    _fields_ = [
        ("nbObjects", ctypes.c_int16),
        ("nbFaces", ctypes.c_int16),
        ("facesOffset", ctypes.c_int32),
        ("scriptOffset", ctypes.c_int32),
        ("unk_c", ctypes.c_int32),
        ("stageName", ctypes.c_char * 128),
        ("songNames", (ctypes.c_char * 128) * 4),
        ("songPaths", (ctypes.c_char * 128) * 4),
    ]


class RawStageQuadBasic(ctypes.LittleEndianStructure):
    _fields_ = [
        ("type", ctypes.c_int16),
        ("byteSize", ctypes.c_int16),
        ("anmScript", ctypes.c_int16),
        ("vmIdx", ctypes.c_int16),
        ("position", ctypes.c_float * 3),
        ("size", ctypes.c_float * 2),
    ]


class RawStageObject(ctypes.LittleEndianStructure):
    _fields_ = [
        ("id", ctypes.c_int16),
        ("zLevel", ctypes.c_int8),
        ("flags", ctypes.c_int8),
        ("position", ctypes.c_float * 3),
        ("size", ctypes.c_float * 3),
        ("firstQuad", RawStageQuadBasic),
    ]


def _decode_ascii(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").rstrip()


def parse_stage_std(data: bytes, *, max_script_instructions: int = 100000) -> dict[str, object]:
    if len(data) < ctypes.sizeof(RawStageHeader):
        raise ValueError("stage std payload is smaller than RawStageHeader")
    header = RawStageHeader.from_buffer_copy(data)
    if header.nbObjects < 0 or header.nbFaces < 0:
        raise ValueError("stage header contains negative object/face counts")

    object_table_offset = ctypes.sizeof(RawStageHeader)
    object_table_size = header.nbObjects * 4
    if object_table_offset + object_table_size > len(data):
        raise ValueError("stage object-offset table is truncated")
    if not 0 <= header.facesOffset < len(data):
        raise ValueError("stage facesOffset is outside the payload")
    if not 0 <= header.scriptOffset < len(data):
        raise ValueError("stage scriptOffset is outside the payload")

    object_offsets = [
        int.from_bytes(data[object_table_offset + index * 4:object_table_offset + (index + 1) * 4], "little")
        for index in range(header.nbObjects)
    ]

    object_summaries: list[dict[str, object]] = []
    total_quads = 0
    first_quad_offset = RawStageObject.firstQuad.offset
    for object_offset in object_offsets:
        if not 0 <= object_offset <= len(data) - ctypes.sizeof(RawStageObject):
            raise ValueError(f"stage object offset is outside the payload: {object_offset:#x}")
        obj = RawStageObject.from_buffer_copy(data, object_offset)
        quad_offset = object_offset + first_quad_offset
        quad_count = 0
        while quad_offset + ctypes.sizeof(RawStageQuadBasic) <= len(data):
            quad = RawStageQuadBasic.from_buffer_copy(data, quad_offset)
            if quad.type < 0:
                break
            if quad.byteSize < ctypes.sizeof(RawStageQuadBasic):
                raise ValueError(f"stage quad byteSize is too small at {quad_offset:#x}: {quad.byteSize}")
            if quad_offset + quad.byteSize > len(data):
                raise ValueError(f"stage quad overruns payload at {quad_offset:#x}")
            quad_count += 1
            total_quads += 1
            quad_offset += quad.byteSize
        object_summaries.append({"id": obj.id, "z_level": obj.zLevel, "flags": obj.flags, "quad_count": quad_count})

    script_offset = header.scriptOffset
    script_instructions = 0
    script_stop_reason = "end-of-file"
    while script_offset + 8 <= len(data):
        instruction_size = int.from_bytes(data[script_offset + 6:script_offset + 8], "little", signed=True)
        if instruction_size < 8:
            script_stop_reason = f"size-too-small@{script_offset:#x}:{instruction_size}"
            break
        if script_offset + instruction_size > len(data):
            script_stop_reason = f"size-overrun@{script_offset:#x}:{instruction_size}"
            break
        script_instructions += 1
        script_offset += instruction_size
        if script_instructions >= max_script_instructions:
            script_stop_reason = "max-script-instructions"
            break
        if script_offset == len(data):
            break

    return {
        "header_size": ctypes.sizeof(RawStageHeader),
        "nb_objects": header.nbObjects,
        "nb_faces": header.nbFaces,
        "faces_offset": header.facesOffset,
        "script_offset": header.scriptOffset,
        "stage_name": _decode_ascii(bytes(header.stageName)),
        "song_names": [_decode_ascii(bytes(raw)) for raw in header.songNames],
        "song_paths": [_decode_ascii(bytes(raw)) for raw in header.songPaths],
        "objects": object_summaries,
        "quad_count_walked": total_quads,
        "script_instructions": script_instructions,
        "script_stop_reason": script_stop_reason,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and walk TH06 stage .std payloads.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--entry", type=str)
    parser.add_argument("--max-script-instructions", type=int, default=100000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, source = load_input_bytes(input_path=args.input, archive_path=args.archive, entry_name=args.entry)
    result = {"source": source, **parse_stage_std(payload, max_script_instructions=args.max_script_instructions)}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
