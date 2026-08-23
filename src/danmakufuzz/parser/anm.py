from __future__ import annotations

import argparse
import ctypes
from collections import Counter
import json
from pathlib import Path
import struct

from ..repo import REFERENCE_DIR
from .common import load_input_bytes


DEFAULT_ARCHIVE = REFERENCE_DIR / "retail" / "game" / "th06" / "紅魔郷ST.DAT"
DEFAULT_ENTRY = "stg1bg.anm"
ANM_OPCODE_EXIT = 0
ANM_OPCODE_EXIT_HIDE = 15
ANM_OPCODE_JUMP = 5


class AnmRawSprite(ctypes.LittleEndianStructure):
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("offset_x", ctypes.c_float),
        ("offset_y", ctypes.c_float),
        ("size_x", ctypes.c_float),
        ("size_y", ctypes.c_float),
    ]


class AnmRawEntry(ctypes.LittleEndianStructure):
    _fields_ = [
        ("numSprites", ctypes.c_int32),
        ("numScripts", ctypes.c_int32),
        ("textureIdx", ctypes.c_uint32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("format", ctypes.c_uint32),
        ("colorKey", ctypes.c_uint32),
        ("nameOffset", ctypes.c_uint32),
        ("spriteIdxOffset", ctypes.c_uint32),
        ("alphaNameOffset", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("unk1", ctypes.c_uint32),
        ("textureOffset", ctypes.c_uint32),
        ("hasData", ctypes.c_uint32),
        ("nextOffset", ctypes.c_uint32),
        ("unk2", ctypes.c_uint32),
    ]


def _decode_ascii_z(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise ValueError(f"string offset is outside the payload: {offset:#x}")
    end = data.find(b"\x00", offset)
    if end < 0:
        raise ValueError(f"unterminated ANM string at {offset:#x}")
    return data[offset:end].decode("ascii", errors="replace")


def _script_boundaries(script_offsets: list[int], payload_size: int) -> dict[int, int]:
    ordered = sorted(set(script_offsets))
    boundaries: dict[int, int] = {}
    for index, start in enumerate(ordered):
        end = ordered[index + 1] if index + 1 < len(ordered) else payload_size
        boundaries[start] = end
    return boundaries


def parse_anm(data: bytes, *, max_script_instructions: int = 4096) -> dict[str, object]:
    if len(data) < ctypes.sizeof(AnmRawEntry):
        raise ValueError("ANM payload is smaller than AnmRawEntry")
    entry = AnmRawEntry.from_buffer_copy(data)
    if int(entry.numSprites) < 0:
        raise ValueError("ANM contains a negative sprite count")
    if int(entry.numScripts) < 0:
        raise ValueError("ANM contains a negative script count")
    if int(entry.numSprites) > 8192 or int(entry.numScripts) > 8192:
        raise ValueError("ANM header counts exceed sanity bounds")

    sprite_table_offset = ctypes.sizeof(AnmRawEntry)
    script_table_offset = sprite_table_offset + int(entry.numSprites) * 4
    if script_table_offset > len(data):
        raise ValueError("ANM sprite-offset table is truncated")
    if script_table_offset + int(entry.numScripts) * 8 > len(data):
        raise ValueError("ANM script table is truncated")

    name = _decode_ascii_z(data, int(entry.nameOffset))
    alpha_name = (
        _decode_ascii_z(data, int(entry.alphaNameOffset))
        if int(entry.alphaNameOffset) != 0
        else None
    )

    sprite_offsets = [
        struct.unpack_from("<I", data, sprite_table_offset + index * 4)[0]
        for index in range(int(entry.numSprites))
    ]
    sprite_offsets_increasing = all(
        left < right for left, right in zip(sprite_offsets, sprite_offsets[1:], strict=False)
    )
    sprite_summaries: list[dict[str, object]] = []
    for sprite_offset in sprite_offsets:
        if sprite_offset + ctypes.sizeof(AnmRawSprite) > len(data):
            raise ValueError(f"ANM sprite offset is outside the payload: {sprite_offset:#x}")
        sprite = AnmRawSprite.from_buffer_copy(data, sprite_offset)
        sprite_summaries.append(
            {
                "id": int(sprite.id),
                "offset": sprite_offset,
                "offset_xy": [float(sprite.offset_x), float(sprite.offset_y)],
                "size_xy": [float(sprite.size_x), float(sprite.size_y)],
            }
        )

    script_entries: list[dict[str, int]] = []
    script_offsets: list[int] = []
    for index in range(int(entry.numScripts)):
        script_id, first_instruction = struct.unpack_from("<II", data, script_table_offset + index * 8)
        if first_instruction >= len(data):
            raise ValueError(f"ANM script offset is outside the payload: {first_instruction:#x}")
        script_entries.append({"id": script_id, "first_instruction": first_instruction})
        script_offsets.append(first_instruction)

    script_offsets_increasing = all(
        left < right for left, right in zip(script_offsets, script_offsets[1:], strict=False)
    )
    boundaries = _script_boundaries(script_offsets, len(data))
    opcode_histogram: Counter[int] = Counter()
    invalid_jump_targets = 0
    total_instructions = 0
    max_time = 0
    max_script_instruction_count = 0
    script_summaries: list[dict[str, object]] = []

    for script in script_entries:
        script_start = int(script["first_instruction"])
        script_end = boundaries[script_start]
        cursor = script_start
        instruction_count = 0
        stop_reason = "boundary"
        while cursor + 4 <= script_end:
            time = int.from_bytes(data[cursor:cursor + 2], "little", signed=True)
            opcode = data[cursor + 2]
            args_count = data[cursor + 3]
            instruction_size = 4 + args_count
            if instruction_size < 4:
                raise ValueError(f"ANM instruction size is too small at {cursor:#x}: {instruction_size}")
            if cursor + instruction_size > script_end:
                raise ValueError(f"ANM instruction overruns script boundary at {cursor:#x}: {instruction_size}")

            opcode_histogram[opcode] += 1
            total_instructions += 1
            instruction_count += 1
            max_time = max(max_time, time)
            if instruction_count >= max_script_instructions:
                stop_reason = "max-script-instructions"
                break

            if opcode == ANM_OPCODE_JUMP and args_count >= 4:
                jump_arg = int.from_bytes(data[cursor + 4:cursor + 8], "little", signed=True)
                jump_target = script_start + jump_arg
                if not script_start <= jump_target < script_end:
                    invalid_jump_targets += 1

            cursor += instruction_size
            if opcode in {ANM_OPCODE_EXIT, ANM_OPCODE_EXIT_HIDE}:
                stop_reason = "exit"
                break

        max_script_instruction_count = max(max_script_instruction_count, instruction_count)
        script_summaries.append(
            {
                "id": int(script["id"]),
                "first_instruction": script_start,
                "instruction_count": instruction_count,
                "stop_reason": stop_reason,
            }
        )

    return {
        "header_size": ctypes.sizeof(AnmRawEntry),
        "payload_size": len(data),
        "num_sprites": int(entry.numSprites),
        "num_scripts": int(entry.numScripts),
        "texture_index": int(entry.textureIdx),
        "width": int(entry.width),
        "height": int(entry.height),
        "format": int(entry.format),
        "color_key": int(entry.colorKey),
        "name_offset": int(entry.nameOffset),
        "alpha_name_offset": int(entry.alphaNameOffset),
        "version": int(entry.version),
        "texture_offset": int(entry.textureOffset),
        "has_data": int(entry.hasData),
        "next_offset": int(entry.nextOffset),
        "name": name,
        "alpha_name": alpha_name,
        "sprite_offsets": sprite_offsets,
        "sprite_offsets_increasing": sprite_offsets_increasing,
        "script_entries": script_entries,
        "script_offsets_increasing": script_offsets_increasing,
        "total_instructions": total_instructions,
        "max_script_instructions": max_script_instruction_count,
        "max_time": max_time,
        "invalid_jump_targets": invalid_jump_targets,
        "opcode_histogram": dict(sorted(opcode_histogram.items())),
        "scripts": script_summaries,
        "sprites": sprite_summaries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and summarize Touhou ANM payloads.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", type=str, default=DEFAULT_ENTRY)
    parser.add_argument("--max-script-instructions", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, source = load_input_bytes(input_path=args.input, archive_path=args.archive, entry_name=args.entry)
    result = {"source": source, **parse_anm(payload, max_script_instructions=args.max_script_instructions)}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
