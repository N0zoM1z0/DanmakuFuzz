from __future__ import annotations

from dataclasses import dataclass

from ..corpus.pbg3 import sha256_bytes


TEXT_OPCODES = {3, 8}
STOP_OPCODES = {0, 10, 11}


@dataclass(frozen=True)
class MsgDatMutant:
    name: str
    payload: bytes
    source: str
    sha256: str


def _replace_i32(payload: bytes, offset: int, value: int) -> bytes:
    return payload[:offset] + int(value).to_bytes(4, "little", signed=True) + payload[offset + 4:]


def _replace_u32(payload: bytes, offset: int, value: int) -> bytes:
    return payload[:offset] + int(value).to_bytes(4, "little", signed=False) + payload[offset + 4:]


def _replace_u16(payload: bytes, offset: int, value: int) -> bytes:
    return payload[:offset] + int(value).to_bytes(2, "little", signed=False) + payload[offset + 2:]


def _replace_u8(payload: bytes, offset: int, value: int) -> bytes:
    return payload[:offset] + bytes([value & 0xFF]) + payload[offset + 1:]


def _header_offsets(payload: bytes) -> tuple[int, list[int]]:
    message_count = int.from_bytes(payload[0:4], "little", signed=True)
    if message_count <= 0:
        return message_count, []
    offsets = [
        int.from_bytes(payload[4 + index * 4:8 + index * 4], "little", signed=False)
        for index in range(message_count)
        if 8 + index * 4 <= len(payload)
    ]
    return message_count, offsets


def _walk_instruction_offsets(payload: bytes, *, start_offset: int, max_steps: int = 512) -> list[tuple[int, int, int]]:
    rows: list[tuple[int, int, int]] = []
    cursor = start_offset
    for _ in range(max_steps):
        if cursor + 4 > len(payload):
            break
        opcode = payload[cursor + 2]
        arg_size = payload[cursor + 3]
        rows.append((cursor, opcode, arg_size))
        if opcode in STOP_OPCODES:
            break
        cursor += 4 + arg_size
    return rows


def generate_msg_dat_mutants(seed_payload: bytes) -> list[MsgDatMutant]:
    if len(seed_payload) < 8:
        raise ValueError("msg dat seed payload is too small")
    message_count, offsets = _header_offsets(seed_payload)
    first_offset = offsets[0] if offsets else None
    table_end = 4 + max(0, message_count) * 4

    first_instruction_offset = first_offset
    first_text_offset = None
    if first_offset is not None:
        for cursor, opcode, _arg_size in _walk_instruction_offsets(seed_payload, start_offset=first_offset):
            if opcode in TEXT_OPCODES:
                first_text_offset = cursor
                break

    mutants: list[MsgDatMutant] = []

    def add(name: str, payload: bytes, source: str) -> None:
        mutants.append(
            MsgDatMutant(
                name=name,
                payload=payload,
                source=source,
                sha256=sha256_bytes(payload),
            )
        )

    add("message-count-zero", _replace_i32(seed_payload, 0, 0), "header")
    add("message-count-neg1", _replace_i32(seed_payload, 0, -1), "header")
    add("message-count-huge", _replace_i32(seed_payload, 0, 0x7FFF), "header")

    if offsets:
        add("first-offset-zero", _replace_u32(seed_payload, 4, 0), "offset-table")
        add("first-offset-header-alias", _replace_u32(seed_payload, 4, table_end - 1), "offset-table")
        add("first-offset-past-eof", _replace_u32(seed_payload, 4, len(seed_payload) + 4), "offset-table")
    if len(offsets) >= 2:
        swapped = _replace_u32(seed_payload, 4, offsets[1])
        swapped = _replace_u32(swapped, 8, offsets[0])
        add("swap-first-two-offsets", swapped, "offset-table")

    if first_instruction_offset is not None and first_instruction_offset + 4 <= len(seed_payload):
        add("first-instr-time-zero", _replace_u16(seed_payload, first_instruction_offset, 0), "instruction")
        add("first-instr-opcode-255", _replace_u8(seed_payload, first_instruction_offset + 2, 0xFF), "instruction")
        add("first-instr-argsize-zero", _replace_u8(seed_payload, first_instruction_offset + 3, 0), "instruction")
        add("first-instr-argsize-255", _replace_u8(seed_payload, first_instruction_offset + 3, 0xFF), "instruction")

    if first_text_offset is not None and first_text_offset + 9 <= len(seed_payload):
        text_arg_size = seed_payload[first_text_offset + 3]
        if text_arg_size >= 5:
            add(
                "first-text-argsize-four",
                _replace_u8(seed_payload, first_text_offset + 3, 4),
                "text",
            )
            text_start = first_text_offset + 8
            text_end = first_text_offset + 4 + text_arg_size
            nul_index = seed_payload.find(b"\x00", text_start, text_end)
            if nul_index >= 0:
                add(
                    "first-text-strip-nul",
                    _replace_u8(seed_payload, nul_index, 0x41),
                    "text",
                )

    deduped: list[MsgDatMutant] = []
    seen: set[str] = set()
    for mutant in mutants:
        if mutant.sha256 in seen:
            continue
        seen.add(mutant.sha256)
        deduped.append(mutant)
    return deduped
