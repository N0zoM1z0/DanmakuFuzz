from __future__ import annotations

from dataclasses import dataclass
import struct

from .replay import (
    ReplayHeader,
    deobfuscate_replay,
    obfuscate_replay,
    synthetic_replay_seed,
    with_replay_checksum,
)
from ..corpus.pbg3 import sha256_bytes


@dataclass(frozen=True)
class ReplayMutant:
    name: str
    payload: bytes
    source: str
    sha256: str


def _replace_u16(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    struct.pack_into("<H", mutable, offset, value & 0xFFFF)
    return bytes(mutable)


def _replace_i32(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    struct.pack_into("<i", mutable, offset, value)
    return bytes(mutable)


def _replace_u32(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    struct.pack_into("<I", mutable, offset, value & 0xFFFFFFFF)
    return bytes(mutable)


def _replace_bytes(buffer: bytes, offset: int, data: bytes) -> bytes:
    mutable = bytearray(buffer)
    mutable[offset:offset + len(data)] = data
    return bytes(mutable)


def _rechecksum(mutant_decoded: bytes) -> bytes:
    return obfuscate_replay(with_replay_checksum(mutant_decoded))


def generate_replay_mutants(seed_payload: bytes | None = None) -> list[ReplayMutant]:
    payload = seed_payload if seed_payload is not None else synthetic_replay_seed()
    decoded = deobfuscate_replay(payload)
    header = ReplayHeader.from_buffer_copy(decoded)
    stage_offsets = [int(offset) for offset in header.stageReplayDataOffsets]
    nonzero_stage_indexes = [index for index, offset in enumerate(stage_offsets) if offset != 0]
    mutants: list[ReplayMutant] = []

    def add(name: str, mutant_payload: bytes, source: str) -> None:
        mutants.append(
            ReplayMutant(
                name=name,
                payload=mutant_payload,
                source=source,
                sha256=sha256_bytes(mutant_payload),
            )
        )

    add("magic-zero", b"\x00\x00\x00\x00" + payload[4:], "header")
    add("truncate-header-8", payload[:8], "header")
    add(
        "version-zero",
        _rechecksum(_replace_u16(decoded, ReplayHeader.version.offset, 0)),
        "header",
    )
    add(
        "checksum-zero",
        obfuscate_replay(_replace_i32(decoded, ReplayHeader.checksum.offset, 0)),
        "header",
    )
    if nonzero_stage_indexes:
        last_index = nonzero_stage_indexes[-1]
        add(
            "last-stage-offset-zero",
            _rechecksum(
                _replace_u32(
                    decoded,
                    ReplayHeader.stageReplayDataOffsets.offset + (last_index * 4),
                    0,
                )
            ),
            "header",
        )
        add(
            "last-stage-offset-outside",
            _rechecksum(
                _replace_u32(
                    decoded,
                    ReplayHeader.stageReplayDataOffsets.offset + (last_index * 4),
                    len(decoded) + 16,
                )
            ),
            "header",
        )
    if len(nonzero_stage_indexes) >= 2:
        first_index = nonzero_stage_indexes[0]
        second_index = nonzero_stage_indexes[1]
        first_offset = stage_offsets[first_index]
        second_offset = stage_offsets[second_index]
        unsorted = _replace_u32(
            decoded,
            ReplayHeader.stageReplayDataOffsets.offset + (first_index * 4),
            second_offset,
        )
        unsorted = _replace_u32(
            unsorted,
            ReplayHeader.stageReplayDataOffsets.offset + (second_index * 4),
            first_offset,
        )
        add("swap-first-two-stage-offsets", _rechecksum(unsorted), "header")
    add(
        "score-plus-one",
        _rechecksum(_replace_i32(decoded, ReplayHeader.score.offset, header.score + 1)),
        "header",
    )
    add(
        "name-empty",
        _rechecksum(_replace_bytes(decoded, ReplayHeader.name.offset, b"\x00" * 8)),
        "header",
    )

    deduped: list[ReplayMutant] = []
    seen: set[tuple[str, str]] = set()
    for mutant in mutants:
        key = (mutant.name, mutant.sha256)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mutant)
    return deduped
