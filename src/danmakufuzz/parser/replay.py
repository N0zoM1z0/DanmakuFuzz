from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path


GAME_VERSION = 0x102


class ReplayHeader(ctypes.LittleEndianStructure):
    _fields_ = [
        ("magic", ctypes.c_char * 4),
        ("version", ctypes.c_uint16),
        ("shottypeChara", ctypes.c_uint8),
        ("difficulty", ctypes.c_uint8),
        ("checksum", ctypes.c_int32),
        ("rngValue1", ctypes.c_uint8),
        ("rngValue2", ctypes.c_uint8),
        ("key", ctypes.c_int8),
        ("rngValue3", ctypes.c_int8),
        ("date", ctypes.c_char * 9),
        ("name", ctypes.c_char * 8),
        ("score", ctypes.c_int32),
        ("slowdownRate2", ctypes.c_float),
        ("slowdownRate", ctypes.c_float),
        ("slowdownRate3", ctypes.c_float),
        ("stageReplayDataOffsets", ctypes.c_uint32 * 7),
    ]


def _decode_ascii(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").rstrip()


def deobfuscate_replay(data: bytes) -> bytes:
    if len(data) < ctypes.sizeof(ReplayHeader):
        raise ValueError("replay payload is smaller than ReplayHeader")
    decoded = bytearray(data)
    key_offset = ReplayHeader.key.offset
    rng3_offset = ReplayHeader.rngValue3.offset
    obfuscation = decoded[key_offset] & 0xFF
    for index in range(rng3_offset, len(decoded)):
        decoded[index] = (decoded[index] - obfuscation) & 0xFF
        obfuscation = (obfuscation + 7) & 0xFF
    return bytes(decoded)


def validate_replay(data: bytes) -> dict[str, object]:
    if len(data) < ctypes.sizeof(ReplayHeader):
        raise ValueError("replay payload is smaller than ReplayHeader")
    raw_header = ReplayHeader.from_buffer_copy(data)
    if bytes(raw_header.magic) != b"T6RP":
        raise ValueError("replay does not have T6RP magic")

    decoded = deobfuscate_replay(data)
    header = ReplayHeader.from_buffer_copy(decoded)

    checksum = 0x3F000318
    for value in decoded[ReplayHeader.key.offset:]:
        checksum = (checksum + value) & 0xFFFFFFFF
    expected_checksum = header.checksum & 0xFFFFFFFF
    if checksum != expected_checksum:
        raise ValueError(f"replay checksum mismatch: {checksum:#x} != {expected_checksum:#x}")
    if header.version != GAME_VERSION:
        raise ValueError(f"unexpected replay version: {header.version:#x}")

    stage_offsets = [int(offset) for offset in header.stageReplayDataOffsets]
    nonzero_offsets = [offset for offset in stage_offsets if offset != 0]
    if any(offset < ctypes.sizeof(ReplayHeader) or offset >= len(decoded) for offset in nonzero_offsets):
        raise ValueError("replay stage data offset is outside the payload")
    if any(left >= right for left, right in zip(nonzero_offsets, nonzero_offsets[1:], strict=False)):
        raise ValueError("replay stage data offsets are not increasing")

    return {
        "header_size": ctypes.sizeof(ReplayHeader),
        "version": header.version,
        "difficulty": header.difficulty,
        "shottype_chara": header.shottypeChara,
        "score": header.score,
        "name": _decode_ascii(bytes(header.name)),
        "date": _decode_ascii(bytes(header.date)),
        "stage_offsets": stage_offsets,
        "decoded_size": len(decoded),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and deobfuscate TH06 replay files.")
    parser.add_argument("--input", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing replay file: {input_path}")
    result = {"input": str(input_path), **validate_replay(input_path.read_bytes())}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
