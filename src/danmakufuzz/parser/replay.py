from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import struct
from typing import Sequence


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


def _encode_ascii_field(value: str, *, size: int) -> bytes:
    encoded = value.encode("ascii", errors="replace")
    if len(encoded) > size:
        raise ValueError(f"ascii field exceeds fixed size {size}: {value!r}")
    return encoded.ljust(size, b"\x00")


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


def obfuscate_replay(decoded: bytes) -> bytes:
    if len(decoded) < ctypes.sizeof(ReplayHeader):
        raise ValueError("decoded replay payload is smaller than ReplayHeader")
    encoded = bytearray(decoded)
    key_offset = ReplayHeader.key.offset
    rng3_offset = ReplayHeader.rngValue3.offset
    obfuscation = encoded[key_offset] & 0xFF
    for index in range(rng3_offset, len(encoded)):
        encoded[index] = (encoded[index] + obfuscation) & 0xFF
        obfuscation = (obfuscation + 7) & 0xFF
    return bytes(encoded)


def compute_replay_checksum(decoded: bytes) -> int:
    if len(decoded) < ctypes.sizeof(ReplayHeader):
        raise ValueError("decoded replay payload is smaller than ReplayHeader")
    checksum = 0x3F000318
    for value in decoded[ReplayHeader.key.offset:]:
        checksum = (checksum + value) & 0xFFFFFFFF
    return checksum


def with_replay_checksum(decoded: bytes) -> bytes:
    checksum = compute_replay_checksum(decoded)
    mutable = bytearray(decoded)
    struct.pack_into(
        "<i",
        mutable,
        ReplayHeader.checksum.offset,
        checksum if checksum < 0x80000000 else checksum - 0x100000000,
    )
    return bytes(mutable)


def build_replay(
    *,
    version: int = GAME_VERSION,
    shottype_chara: int = 0,
    difficulty: int = 3,
    key: int = 0x31,
    rng_value1: int = 0x12,
    rng_value2: int = 0x34,
    rng_value3: int = 0x05,
    date: str = "20260822",
    name: str = "DANMAKU",
    score: int = 12345678,
    slowdown_rate: float = 1.0,
    slowdown_rate2: float = 1.0,
    slowdown_rate3: float = 1.0,
    stage_payloads: Sequence[bytes] = (),
) -> bytes:
    if len(stage_payloads) > 7:
        raise ValueError("TH06 replay supports at most 7 stage payloads")
    header = ReplayHeader()
    header.magic = b"T6RP"
    header.version = version & 0xFFFF
    header.shottypeChara = shottype_chara & 0xFF
    header.difficulty = difficulty & 0xFF
    header.checksum = 0
    header.rngValue1 = rng_value1 & 0xFF
    header.rngValue2 = rng_value2 & 0xFF
    if not (-128 <= key <= 127):
        raise ValueError("replay key must fit in int8")
    if not (-128 <= rng_value3 <= 127):
        raise ValueError("replay rng_value3 must fit in int8")
    header.key = key
    header.rngValue3 = rng_value3
    header.date = _encode_ascii_field(date, size=9)
    header.name = _encode_ascii_field(name, size=8)
    header.score = score
    header.slowdownRate2 = float(slowdown_rate2)
    header.slowdownRate = float(slowdown_rate)
    header.slowdownRate3 = float(slowdown_rate3)

    header_size = ctypes.sizeof(ReplayHeader)
    offsets = [0] * 7
    payload_chunks: list[bytes] = []
    cursor = header_size
    for index, payload in enumerate(stage_payloads):
        offsets[index] = cursor
        payload_chunks.append(bytes(payload))
        cursor += len(payload)
    for index, offset in enumerate(offsets):
        header.stageReplayDataOffsets[index] = offset

    decoded = bytearray(bytes(header))
    for payload in payload_chunks:
        decoded.extend(payload)
    return obfuscate_replay(with_replay_checksum(bytes(decoded)))


def synthetic_replay_seed() -> bytes:
    return build_replay(
        shottype_chara=1,
        difficulty=2,
        key=0x31,
        rng_value1=0x12,
        rng_value2=0x34,
        rng_value3=0x05,
        date="20260822",
        name="DANMAKU",
        score=98765432,
        stage_payloads=(
            b"\x10\x20\x30\x40",
            b"\x50\x60\x70\x80\x90",
            b"\xA0\xB0\xC0\xD0\xE0\xF0",
        ),
    )


def validate_replay(data: bytes) -> dict[str, object]:
    if len(data) < ctypes.sizeof(ReplayHeader):
        raise ValueError("replay payload is smaller than ReplayHeader")
    raw_header = ReplayHeader.from_buffer_copy(data)
    if bytes(raw_header.magic) != b"T6RP":
        raise ValueError("replay does not have T6RP magic")

    decoded = deobfuscate_replay(data)
    header = ReplayHeader.from_buffer_copy(decoded)

    checksum = compute_replay_checksum(decoded)
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
