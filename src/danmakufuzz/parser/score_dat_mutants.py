from __future__ import annotations

import ctypes
from dataclasses import dataclass
import struct

from ..corpus.pbg3 import sha256_bytes
from .score_dat import (
    CLRD_MAGIC,
    CATK_MAGIC,
    PSCR_MAGIC,
    Clrd,
    ScoreRaw,
    Th6k,
    decode_score_dat,
    encode_score_dat,
    with_score_checksum,
)


@dataclass(frozen=True)
class ScoreDatMutant:
    name: str
    payload: bytes
    source: str
    sha256: str


def _replace_u16(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<H", mutable, offset, value & 0xFFFF)
    return bytes(mutable)


def _replace_u32(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<I", mutable, offset, value & 0xFFFFFFFF)
    return bytes(mutable)


def _replace_u8(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    mutable[offset] = value & 0xFF
    return bytes(mutable)


def _first_record_offsets(decoded: bytes) -> dict[int, int]:
    raw = ScoreRaw.from_buffer_copy(decoded)
    file_limit = min(len(decoded), int(raw.fileLen))
    cursor = int(raw.dataOffset)
    offsets: dict[int, int] = {}
    while cursor + ctypes.sizeof(Th6k) <= file_limit:
        record = Th6k.from_buffer_copy(decoded, cursor)
        record_len = int(record.th6kLen)
        if record_len < ctypes.sizeof(Th6k) or cursor + record_len > file_limit:
            break
        offsets.setdefault(int(record.magic), cursor)
        cursor += record_len
        if cursor >= file_limit:
            break
    return offsets


def generate_score_dat_mutants(seed_payload: bytes) -> list[ScoreDatMutant]:
    if len(seed_payload) < ctypes.sizeof(ScoreRaw):
        raise ValueError("score.dat seed payload is smaller than ScoreRaw")
    decoded = decode_score_dat(seed_payload)
    offsets = _first_record_offsets(decoded)
    mutants: list[ScoreDatMutant] = []

    def add(name: str, payload: bytes, source: str) -> None:
        mutants.append(
            ScoreDatMutant(
                name=name,
                payload=payload,
                source=source,
                sha256=sha256_bytes(payload),
            )
        )

    add("truncate-header-8", seed_payload[:8], "header")

    wrong_checksum = _replace_u16(decoded, ScoreRaw.csum.offset, 0)
    add("checksum-zero", encode_score_dat(wrong_checksum), "header")

    add(
        "data-offset-zero",
        encode_score_dat(with_score_checksum(_replace_u32(decoded, ScoreRaw.dataOffset.offset, 0))),
        "header",
    )
    add(
        "data-offset-past-eof",
        encode_score_dat(with_score_checksum(_replace_u32(decoded, ScoreRaw.dataOffset.offset, len(decoded) + 16))),
        "header",
    )
    add(
        "file-len-zero",
        encode_score_dat(with_score_checksum(_replace_u32(decoded, ScoreRaw.fileLen.offset, 0))),
        "header",
    )
    add(
        "file-len-header-only",
        encode_score_dat(with_score_checksum(_replace_u32(decoded, ScoreRaw.fileLen.offset, ctypes.sizeof(ScoreRaw)))),
        "header",
    )

    first_th6k_offset = offsets.get(int.from_bytes(b"TH6K", "little"))
    if first_th6k_offset is not None:
        add(
            "first-record-magic-zero",
            encode_score_dat(with_score_checksum(_replace_u32(decoded, first_th6k_offset, 0))),
            "records",
        )
        add(
            "first-record-len-zero",
            encode_score_dat(with_score_checksum(_replace_u16(decoded, first_th6k_offset + Th6k.th6kLen.offset, 0))),
            "records",
        )

    first_clrd_offset = offsets.get(CLRD_MAGIC)
    if first_clrd_offset is not None:
        add(
            "first-clrd-character-255",
            encode_score_dat(
                with_score_checksum(
                    _replace_u8(decoded, first_clrd_offset + Clrd.characterShotType.offset, 0xFF)
                )
            ),
            "clrd",
        )

    first_catk_offset = offsets.get(CATK_MAGIC)
    if first_catk_offset is not None:
        add(
            "first-catk-idx-ffff",
            encode_score_dat(
                with_score_checksum(
                    _replace_u16(decoded, first_catk_offset + 16, 0xFFFF)
                )
            ),
            "catk",
        )

    first_pscr_offset = offsets.get(PSCR_MAGIC)
    if first_pscr_offset is not None:
        add(
            "first-pscr-difficulty-255",
            encode_score_dat(
                with_score_checksum(
                    _replace_u8(decoded, first_pscr_offset + 17, 0xFF)
                )
            ),
            "pscr",
        )
        add(
            "first-pscr-stage-255",
            encode_score_dat(
                with_score_checksum(
                    _replace_u8(decoded, first_pscr_offset + 18, 0xFF)
                )
            ),
            "pscr",
        )

    deduped: list[ScoreDatMutant] = []
    seen: set[str] = set()
    for mutant in mutants:
        if mutant.sha256 in seen:
            continue
        seen.add(mutant.sha256)
        deduped.append(mutant)
    return deduped
