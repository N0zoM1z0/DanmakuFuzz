from __future__ import annotations

import argparse
import ctypes
from collections import Counter
import json
from pathlib import Path
import struct

from ..repo import REFERENCE_DIR


TH6K_MAGIC = int.from_bytes(b"TH6K", "little")
HSCR_MAGIC = int.from_bytes(b"HSCR", "little")
CLRD_MAGIC = int.from_bytes(b"CLRD", "little")
PSCR_MAGIC = int.from_bytes(b"PSCR", "little")
CATK_MAGIC = int.from_bytes(b"CATK", "little")
TH6K_VERSION = 16

HSCR_NUM_CHARS_SHOTTYPES = 4
HSCR_NUM_DIFFICULTIES = 5
CLRD_NUM_CHARACTERS = 4
CATK_NUM_CAPTURES = 64
PSCR_NUM_CHARS_SHOTTYPES = 4
PSCR_NUM_STAGES = 6
PSCR_NUM_DIFFICULTIES = 4

DEFAULT_SCORE_PATH = REFERENCE_DIR / "retail" / "game" / "th06" / "score.dat"


class Th6k(ctypes.LittleEndianStructure):
    _fields_ = [
        ("magic", ctypes.c_uint32),
        ("th6kLen", ctypes.c_uint16),
        ("unkLen", ctypes.c_uint16),
        ("version", ctypes.c_uint8),
        ("unk_9", ctypes.c_uint8),
    ]


class Hscr(ctypes.LittleEndianStructure):
    _fields_ = [
        ("base", Th6k),
        ("score", ctypes.c_uint32),
        ("character", ctypes.c_uint8),
        ("difficulty", ctypes.c_uint8),
        ("stage", ctypes.c_uint8),
        ("name", ctypes.c_char * 9),
    ]


class Catk(ctypes.LittleEndianStructure):
    _fields_ = [
        ("base", Th6k),
        ("captureScore", ctypes.c_int32),
        ("idx", ctypes.c_uint16),
        ("nameCsum", ctypes.c_uint8),
        ("characterShotType", ctypes.c_uint8),
        ("unk_14", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
        ("unk_38", ctypes.c_uint32),
        ("numAttempts", ctypes.c_uint16),
        ("numSuccess", ctypes.c_uint16),
    ]


class Clrd(ctypes.LittleEndianStructure):
    _fields_ = [
        ("base", Th6k),
        ("difficultyClearedWithRetries", ctypes.c_uint8 * 5),
        ("difficultyClearedWithoutRetries", ctypes.c_uint8 * 5),
        ("characterShotType", ctypes.c_uint8),
    ]


class Pscr(ctypes.LittleEndianStructure):
    _fields_ = [
        ("base", Th6k),
        ("score", ctypes.c_int32),
        ("character", ctypes.c_uint8),
        ("difficulty", ctypes.c_uint8),
        ("stage", ctypes.c_uint8),
    ]


class ScoreRaw(ctypes.LittleEndianStructure):
    _fields_ = [
        ("xorseed", ctypes.c_uint8 * 2),
        ("csum", ctypes.c_uint16),
        ("unk_8", ctypes.c_uint16),
        ("unk", ctypes.c_uint8 * 2),
        ("dataOffset", ctypes.c_uint32),
        ("padding", ctypes.c_uint32),
        ("fileLen", ctypes.c_uint32),
    ]


def _rotate_score_xor(value: int) -> int:
    value &= 0xFF
    return (((value & 0xE0) >> 5) | ((value & 0x1F) << 3)) & 0xFF


def decode_score_dat(data: bytes) -> bytes:
    if len(data) < ctypes.sizeof(ScoreRaw):
        raise ValueError("score.dat payload is smaller than ScoreRaw")
    mutable = bytearray(data)
    xor_value = 0
    cursor = 1
    remaining = len(mutable) - 2
    while remaining > 0:
        xor_value = _rotate_score_xor(xor_value + mutable[cursor])
        mutable[cursor + 1] ^= xor_value
        cursor += 1
        remaining -= 1
    return bytes(mutable)


def encode_score_dat(decoded: bytes) -> bytes:
    if len(decoded) < ctypes.sizeof(ScoreRaw):
        raise ValueError("decoded score.dat payload is smaller than ScoreRaw")
    encoded = bytearray(decoded)
    xor_value = 0
    cursor = 1
    remaining = len(decoded) - 2
    while remaining > 0:
        xor_value = _rotate_score_xor(xor_value + decoded[cursor])
        encoded[cursor + 1] = decoded[cursor + 1] ^ xor_value
        cursor += 1
        remaining -= 1
    return bytes(encoded)


def compute_score_checksum(decoded: bytes) -> int:
    if len(decoded) < ctypes.sizeof(ScoreRaw):
        raise ValueError("decoded score.dat payload is smaller than ScoreRaw")
    return sum(decoded[4:]) & 0xFFFF


def with_score_checksum(decoded: bytes) -> bytes:
    checksum = compute_score_checksum(decoded)
    mutable = bytearray(decoded)
    struct.pack_into("<H", mutable, ScoreRaw.csum.offset, checksum)
    return bytes(mutable)


def _magic_name(value: int) -> str:
    try:
        return value.to_bytes(4, "little").decode("ascii")
    except UnicodeDecodeError:
        return f"0x{value:08x}"


def _fallback_summary(
    decoded: bytes | None,
    data: bytes,
    reasons: list[str],
) -> dict[str, object]:
    raw = ScoreRaw.from_buffer_copy(decoded) if decoded is not None and len(decoded) >= ctypes.sizeof(ScoreRaw) else None
    return {
        "classification": "fallback-empty",
        "fallback_reasons": reasons,
        "encoded_size": len(data),
        "decoded_size": len(decoded) if decoded is not None else 0,
        "header_size": ctypes.sizeof(ScoreRaw),
        "xorseed": list(raw.xorseed) if raw is not None else None,
        "checksum": int(raw.csum) if raw is not None else None,
        "expected_checksum": compute_score_checksum(decoded) if decoded is not None and len(decoded) >= ctypes.sizeof(ScoreRaw) else None,
        "data_offset": int(raw.dataOffset) if raw is not None else None,
        "file_len": int(raw.fileLen) if raw is not None else None,
        "record_count": 0,
        "record_histogram": {},
        "valid_hscr_records": 0,
        "invalid_hscr_records": 0,
        "valid_catk_records": 0,
        "invalid_catk_records": 0,
        "valid_clrd_records": 0,
        "invalid_clrd_records": 0,
        "valid_pscr_records": 0,
        "invalid_pscr_records": 0,
        "walk_stop_reason": "fallback",
        "first_th6k_offset": None,
    }


def summarize_score_dat(data: bytes, *, max_records: int = 4096) -> dict[str, object]:
    if len(data) < ctypes.sizeof(ScoreRaw):
        return _fallback_summary(None, data, ["truncated-header"])

    decoded = decode_score_dat(data)
    raw = ScoreRaw.from_buffer_copy(decoded)
    reasons: list[str] = []
    expected_checksum = compute_score_checksum(decoded)
    if int(raw.csum) != expected_checksum:
        reasons.append("checksum-mismatch")
    if int(raw.fileLen) < ctypes.sizeof(ScoreRaw) or int(raw.fileLen) > len(decoded):
        reasons.append("file-length-outside-payload")
    if int(raw.dataOffset) < ctypes.sizeof(ScoreRaw) or int(raw.dataOffset) > min(len(decoded), int(raw.fileLen)):
        reasons.append("data-offset-outside-payload")
    if reasons:
        return _fallback_summary(decoded, data, reasons)

    file_limit = min(len(decoded), int(raw.fileLen))
    first_th6k_offset: int | None = None
    cursor = int(raw.dataOffset)
    visited_offsets: set[int] = set()
    search_stop_reason = "found"
    while cursor + ctypes.sizeof(Th6k) <= file_limit:
        if cursor in visited_offsets:
            search_stop_reason = "th6k-search-loop"
            break
        visited_offsets.add(cursor)
        record = Th6k.from_buffer_copy(decoded, cursor)
        if int(record.magic) == TH6K_MAGIC:
            first_th6k_offset = cursor
            break
        if int(record.th6kLen) < ctypes.sizeof(Th6k):
            search_stop_reason = f"th6k-search-size-too-small@{cursor:#x}:{int(record.th6kLen)}"
            break
        next_cursor = cursor + int(record.th6kLen)
        if next_cursor <= cursor or next_cursor > file_limit:
            search_stop_reason = f"th6k-search-overrun@{cursor:#x}:{int(record.th6kLen)}"
            break
        cursor = next_cursor
    if first_th6k_offset is None:
        return _fallback_summary(decoded, data, [search_stop_reason, "missing-th6k-root"])

    record_histogram: Counter[str] = Counter()
    valid_hscr_records = 0
    invalid_hscr_records = 0
    valid_catk_records = 0
    invalid_catk_records = 0
    valid_clrd_records = 0
    invalid_clrd_records = 0
    valid_pscr_records = 0
    invalid_pscr_records = 0
    record_count = 0
    walk_stop_reason = "end-of-file"
    cursor = first_th6k_offset
    while cursor + ctypes.sizeof(Th6k) <= file_limit:
        record = Th6k.from_buffer_copy(decoded, cursor)
        record_len = int(record.th6kLen)
        if record_len < ctypes.sizeof(Th6k):
            walk_stop_reason = f"record-size-too-small@{cursor:#x}:{record_len}"
            break
        if cursor + record_len > file_limit:
            walk_stop_reason = f"record-overrun@{cursor:#x}:{record_len}"
            break
        record_count += 1
        if record_count > max_records:
            walk_stop_reason = "max-records"
            break

        magic = int(record.magic)
        magic_name = _magic_name(magic)
        record_histogram[magic_name] += 1

        if magic == HSCR_MAGIC and int(record.version) == TH6K_VERSION and record_len >= ctypes.sizeof(Hscr):
            parsed = Hscr.from_buffer_copy(decoded, cursor)
            if int(parsed.character) < HSCR_NUM_CHARS_SHOTTYPES and int(parsed.difficulty) < HSCR_NUM_DIFFICULTIES:
                valid_hscr_records += 1
            else:
                invalid_hscr_records += 1
        elif magic == CATK_MAGIC and int(record.version) == TH6K_VERSION and record_len >= ctypes.sizeof(Catk):
            parsed = Catk.from_buffer_copy(decoded, cursor)
            if int(parsed.idx) < CATK_NUM_CAPTURES:
                valid_catk_records += 1
            else:
                invalid_catk_records += 1
        elif magic == CLRD_MAGIC and int(record.version) == TH6K_VERSION and record_len >= ctypes.sizeof(Clrd):
            parsed = Clrd.from_buffer_copy(decoded, cursor)
            if int(parsed.characterShotType) < CLRD_NUM_CHARACTERS:
                valid_clrd_records += 1
            else:
                invalid_clrd_records += 1
        elif magic == PSCR_MAGIC and int(record.version) == TH6K_VERSION and record_len >= ctypes.sizeof(Pscr):
            parsed = Pscr.from_buffer_copy(decoded, cursor)
            if (
                int(parsed.character) < PSCR_NUM_CHARS_SHOTTYPES
                and int(parsed.difficulty) < PSCR_NUM_DIFFICULTIES + 1
                and int(parsed.stage) < PSCR_NUM_STAGES + 1
            ):
                valid_pscr_records += 1
            else:
                invalid_pscr_records += 1

        cursor += record_len
        if cursor >= file_limit:
            break

    return {
        "classification": "loaded",
        "fallback_reasons": [],
        "encoded_size": len(data),
        "decoded_size": len(decoded),
        "header_size": ctypes.sizeof(ScoreRaw),
        "xorseed": list(raw.xorseed),
        "checksum": int(raw.csum),
        "expected_checksum": expected_checksum,
        "data_offset": int(raw.dataOffset),
        "file_len": int(raw.fileLen),
        "first_th6k_offset": first_th6k_offset,
        "record_count": record_count,
        "record_histogram": dict(sorted(record_histogram.items())),
        "valid_hscr_records": valid_hscr_records,
        "invalid_hscr_records": invalid_hscr_records,
        "valid_catk_records": valid_catk_records,
        "invalid_catk_records": invalid_catk_records,
        "valid_clrd_records": valid_clrd_records,
        "invalid_clrd_records": invalid_clrd_records,
        "valid_pscr_records": valid_pscr_records,
        "invalid_pscr_records": invalid_pscr_records,
        "walk_stop_reason": walk_stop_reason,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and summarize Touhou score.dat payloads.")
    parser.add_argument("--input", type=Path, default=DEFAULT_SCORE_PATH)
    parser.add_argument("--max-records", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing score.dat file: {input_path}")
    result = {
        "input": str(input_path),
        **summarize_score_dat(input_path.read_bytes(), max_records=args.max_records),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
