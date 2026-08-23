from __future__ import annotations

import ctypes
from dataclasses import dataclass
import struct

from ..corpus.pbg3 import sha256_bytes
from .anm import ANM_OPCODE_JUMP, AnmRawEntry


@dataclass(frozen=True)
class AnmMutant:
    name: str
    payload: bytes
    source: str
    sha256: str


def _replace_i32(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<i", mutable, offset, value)
    return bytes(mutable)


def _replace_u32(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<I", mutable, offset, value & 0xFFFFFFFF)
    return bytes(mutable)


def _replace_u8(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    mutable[offset] = value & 0xFF
    return bytes(mutable)


def _replace_i32_at(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<i", mutable, offset, value)
    return bytes(mutable)


def generate_anm_mutants(seed_payload: bytes) -> list[AnmMutant]:
    if len(seed_payload) < ctypes.sizeof(AnmRawEntry):
        raise ValueError("ANM seed payload is smaller than AnmRawEntry")
    entry = AnmRawEntry.from_buffer_copy(seed_payload)
    sprite_table_offset = ctypes.sizeof(AnmRawEntry)
    script_table_offset = sprite_table_offset + max(0, int(entry.numSprites)) * 4
    mutants: list[AnmMutant] = []

    def add(name: str, payload: bytes, source: str) -> None:
        mutants.append(AnmMutant(name=name, payload=payload, source=source, sha256=sha256_bytes(payload)))

    add("truncate-header-16", seed_payload[:16], "header")
    add("num-sprites-neg1", _replace_i32(seed_payload, AnmRawEntry.numSprites.offset, -1), "header")
    add("num-scripts-neg1", _replace_i32(seed_payload, AnmRawEntry.numScripts.offset, -1), "header")
    add("name-offset-zero", _replace_u32(seed_payload, AnmRawEntry.nameOffset.offset, 0), "header")
    add("name-offset-past-eof", _replace_u32(seed_payload, AnmRawEntry.nameOffset.offset, len(seed_payload) + 16), "header")
    add(
        "alpha-offset-past-eof",
        _replace_u32(seed_payload, AnmRawEntry.alphaNameOffset.offset, len(seed_payload) + 16),
        "header",
    )
    add("width-neg1", _replace_i32(seed_payload, AnmRawEntry.width.offset, -1), "header")
    add("height-neg1", _replace_i32(seed_payload, AnmRawEntry.height.offset, -1), "header")
    add("next-offset-past-eof", _replace_u32(seed_payload, AnmRawEntry.nextOffset.offset, len(seed_payload) + 16), "header")

    if int(entry.numSprites) > 0 and sprite_table_offset + 4 <= len(seed_payload):
        add("first-sprite-offset-zero", _replace_u32(seed_payload, sprite_table_offset, 0), "sprite-table")
        add(
            "first-sprite-offset-past-eof",
            _replace_u32(seed_payload, sprite_table_offset, len(seed_payload) + 16),
            "sprite-table",
        )

    if int(entry.numScripts) > 0 and script_table_offset + 8 <= len(seed_payload):
        first_script_offset = struct.unpack_from("<I", seed_payload, script_table_offset + 4)[0]
        add("first-script-id-ffff", _replace_u32(seed_payload, script_table_offset, 0xFFFF), "script-table")
        add("first-script-offset-zero", _replace_u32(seed_payload, script_table_offset + 4, 0), "script-table")
        add(
            "first-script-offset-past-eof",
            _replace_u32(seed_payload, script_table_offset + 4, len(seed_payload) + 16),
            "script-table",
        )
        if int(entry.numScripts) > 1 and script_table_offset + 16 <= len(seed_payload):
            first_id, first_start = struct.unpack_from("<II", seed_payload, script_table_offset)
            second_id, second_start = struct.unpack_from("<II", seed_payload, script_table_offset + 8)
            swapped = bytearray(seed_payload)
            struct.pack_into("<II", swapped, script_table_offset, second_id, second_start)
            struct.pack_into("<II", swapped, script_table_offset + 8, first_id, first_start)
            add("swap-first-two-scripts", bytes(swapped), "script-table")
        if first_script_offset + 4 <= len(seed_payload):
            add("first-instr-opcode-255", _replace_u8(seed_payload, first_script_offset + 2, 0xFF), "script")
            add("first-instr-argsize-zero", _replace_u8(seed_payload, first_script_offset + 3, 0), "script")
            add("first-instr-argsize-255", _replace_u8(seed_payload, first_script_offset + 3, 0xFF), "script")
            if seed_payload[first_script_offset + 2] == ANM_OPCODE_JUMP and first_script_offset + 8 <= len(seed_payload):
                add(
                    "first-jump-target-neg4096",
                    _replace_i32_at(seed_payload, first_script_offset + 4, -4096),
                    "script",
                )

    deduped: list[AnmMutant] = []
    seen: set[str] = set()
    for mutant in mutants:
        if mutant.sha256 in seen:
            continue
        seen.add(mutant.sha256)
        deduped.append(mutant)
    return deduped
