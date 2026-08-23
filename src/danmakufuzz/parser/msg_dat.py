from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import load_input_bytes


MSG_OPCODE_MAX = 13
STOP_OPCODES = {0, 10, 11}
TEXT_OPCODES = {3, 8}
MIN_ARG_SIZES = {
    1: 4,
    2: 4,
    3: 5,
    4: 4,
    5: 3,
    7: 4,
    8: 5,
    13: 4,
}


def _read_i32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little", signed=True)


def _read_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little", signed=False)


def _read_u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little", signed=False)


def _decode_text_payload(payload: bytes) -> str:
    nul_index = payload.find(b"\x00")
    if nul_index < 0:
        raise ValueError("msg text payload is missing a NUL terminator")
    return payload[:nul_index].decode("shift_jis", errors="replace")


def _validate_instruction(
    *,
    opcode: int,
    arg_size: int,
    args: bytes,
    offset: int,
) -> dict[str, object]:
    if not 0 <= opcode <= MSG_OPCODE_MAX:
        raise ValueError(f"msg opcode is outside the supported range at {offset:#x}: {opcode}")
    minimum = MIN_ARG_SIZES.get(opcode)
    if minimum is not None and arg_size < minimum:
        raise ValueError(f"msg argSize is too small at {offset:#x}: opcode={opcode} arg_size={arg_size}")
    text_preview: str | None = None
    if opcode in TEXT_OPCODES:
        text_preview = _decode_text_payload(args[4:])
    return {
        "opcode": opcode,
        "arg_size": arg_size,
        "text_preview": text_preview,
    }


def _walk_message(data: bytes, *, start_offset: int, max_message_instructions: int) -> dict[str, object]:
    cursor = start_offset
    instruction_count = 0
    opcode_histogram: dict[str, int] = {}
    max_time = 0
    stop_reason = "end-of-file"
    while cursor + 4 <= len(data):
        if instruction_count >= max_message_instructions:
            stop_reason = "max-message-instructions"
            break
        time_value = _read_u16(data, cursor)
        opcode = data[cursor + 2]
        arg_size = data[cursor + 3]
        total_size = 4 + arg_size
        if cursor + total_size > len(data):
            raise ValueError(f"msg instruction overruns payload at {cursor:#x}: size={total_size}")
        args = data[cursor + 4:cursor + total_size]
        _validate_instruction(opcode=opcode, arg_size=arg_size, args=args, offset=cursor)
        instruction_count += 1
        opcode_histogram[str(opcode)] = opcode_histogram.get(str(opcode), 0) + 1
        max_time = max(max_time, time_value)
        if opcode in STOP_OPCODES:
            stop_reason = f"stop-opcode-{opcode}"
            break
        cursor += total_size
    return {
        "start_offset": start_offset,
        "instruction_count": instruction_count,
        "max_time": max_time,
        "stop_reason": stop_reason,
        "opcode_histogram": opcode_histogram,
    }


def parse_msg_dat(data: bytes, *, max_message_instructions: int = 4096) -> dict[str, object]:
    if len(data) < 4:
        raise ValueError("msg payload is smaller than MsgRawHeader")
    message_count = _read_i32(data, 0)
    if not 0 <= message_count <= 0x10000:
        raise ValueError(f"invalid msg message count: {message_count}")
    table_end = 4 + message_count * 4
    if table_end > len(data):
        raise ValueError("msg offset table is truncated")
    offsets = [_read_u32(data, 4 + index * 4) for index in range(message_count)]
    if any(offset < table_end or offset >= len(data) for offset in offsets):
        raise ValueError("msg message offset is outside the instruction region")

    message_summaries: list[dict[str, object]] = []
    total_instructions = 0
    combined_histogram: dict[str, int] = {}
    for offset in offsets:
        summary = _walk_message(
            data,
            start_offset=offset,
            max_message_instructions=max_message_instructions,
        )
        message_summaries.append(summary)
        total_instructions += int(summary["instruction_count"])
        for opcode, count in dict(summary["opcode_histogram"]).items():
            combined_histogram[opcode] = combined_histogram.get(opcode, 0) + int(count)

    stop_reasons = [str(summary["stop_reason"]) for summary in message_summaries]
    return {
        "header_size": 4,
        "message_count": message_count,
        "offset_table_size": table_end,
        "offsets": offsets,
        "offsets_increasing": all(left < right for left, right in zip(offsets, offsets[1:], strict=False)),
        "total_instructions": total_instructions,
        "max_message_instructions": max((int(summary["instruction_count"]) for summary in message_summaries), default=0),
        "max_time": max((int(summary["max_time"]) for summary in message_summaries), default=0),
        "stop_reasons": stop_reasons,
        "opcode_histogram": dict(sorted(combined_histogram.items(), key=lambda item: int(item[0]))),
        "messages": message_summaries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and walk Touhou message-script DAT payloads.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--entry", type=str)
    parser.add_argument("--max-message-instructions", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, source = load_input_bytes(input_path=args.input, archive_path=args.archive, entry_name=args.entry)
    result = {
        "source": source,
        **parse_msg_dat(payload, max_message_instructions=args.max_message_instructions),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
