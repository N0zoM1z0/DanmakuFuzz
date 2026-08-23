from __future__ import annotations

import ctypes
from dataclasses import dataclass

from ..corpus.pbg3 import sha256_bytes
from .stage_std import RawStageHeader, RawStageObject, RawStageQuadBasic


@dataclass(frozen=True)
class StageStdMutant:
    name: str
    payload: bytes
    source: str
    sha256: str


def _replace_i16(payload: bytes, offset: int, value: int) -> bytes:
    return payload[:offset] + int(value).to_bytes(2, "little", signed=True) + payload[offset + 2:]


def _replace_i32(payload: bytes, offset: int, value: int) -> bytes:
    return payload[:offset] + int(value).to_bytes(4, "little", signed=True) + payload[offset + 4:]


def _replace_u32(payload: bytes, offset: int, value: int) -> bytes:
    return payload[:offset] + int(value).to_bytes(4, "little", signed=False) + payload[offset + 4:]


def generate_stage_std_mutants(seed_payload: bytes) -> list[StageStdMutant]:
    if len(seed_payload) < ctypes.sizeof(RawStageHeader):
        raise ValueError("stage std seed payload is smaller than RawStageHeader")

    header = RawStageHeader.from_buffer_copy(seed_payload)
    object_table_offset = ctypes.sizeof(RawStageHeader)
    object_offsets: list[int] = []
    for index in range(max(0, int(header.nbObjects))):
        start = object_table_offset + index * 4
        end = start + 4
        if end > len(seed_payload):
            break
        object_offsets.append(int.from_bytes(seed_payload[start:end], "little"))

    first_object_offset = object_offsets[0] if object_offsets else None
    first_quad_offset = (
        first_object_offset + RawStageObject.firstQuad.offset
        if first_object_offset is not None
        else None
    )
    script_size_offset = int(header.scriptOffset) + 6

    mutants: list[StageStdMutant] = []

    def add(name: str, payload: bytes, source: str) -> None:
        mutants.append(
            StageStdMutant(
                name=name,
                payload=payload,
                source=source,
                sha256=sha256_bytes(payload),
            )
        )

    add(
        "nb-objects-zero",
        _replace_i16(seed_payload, RawStageHeader.nbObjects.offset, 0),
        "header",
    )
    add(
        "nb-objects-neg1",
        _replace_i16(seed_payload, RawStageHeader.nbObjects.offset, -1),
        "header",
    )
    add(
        "nb-faces-neg1",
        _replace_i16(seed_payload, RawStageHeader.nbFaces.offset, -1),
        "header",
    )
    add(
        "faces-offset-zero",
        _replace_i32(seed_payload, RawStageHeader.facesOffset.offset, 0),
        "header",
    )
    add(
        "faces-offset-past-eof",
        _replace_i32(seed_payload, RawStageHeader.facesOffset.offset, len(seed_payload) + 4),
        "header",
    )
    add(
        "script-offset-zero",
        _replace_i32(seed_payload, RawStageHeader.scriptOffset.offset, 0),
        "header",
    )
    add(
        "script-offset-past-eof",
        _replace_i32(seed_payload, RawStageHeader.scriptOffset.offset, len(seed_payload) + 4),
        "header",
    )

    if object_offsets:
        add(
            "first-object-offset-zero",
            _replace_u32(seed_payload, object_table_offset, 0),
            "object-table",
        )
        add(
            "first-object-offset-header-alias",
            _replace_u32(seed_payload, object_table_offset, ctypes.sizeof(RawStageHeader)),
            "object-table",
        )
        add(
            "first-object-offset-past-eof",
            _replace_u32(seed_payload, object_table_offset, len(seed_payload)),
            "object-table",
        )

    if first_quad_offset is not None and first_quad_offset + ctypes.sizeof(RawStageQuadBasic) <= len(seed_payload):
        add(
            "first-quad-type-neg1",
            _replace_i16(seed_payload, first_quad_offset + RawStageQuadBasic.type.offset, -1),
            "quad",
        )
        add(
            "first-quad-bytesize-zero",
            _replace_i16(seed_payload, first_quad_offset + RawStageQuadBasic.byteSize.offset, 0),
            "quad",
        )
        add(
            "first-quad-bytesize-overrun",
            _replace_i16(seed_payload, first_quad_offset + RawStageQuadBasic.byteSize.offset, 0x7FFF),
            "quad",
        )

    if script_size_offset + 2 <= len(seed_payload):
        add(
            "script-first-size-zero",
            _replace_i16(seed_payload, script_size_offset, 0),
            "script",
        )
        add(
            "script-first-size-eight",
            _replace_i16(seed_payload, script_size_offset, 8),
            "script",
        )
        add(
            "script-first-size-4096",
            _replace_i16(seed_payload, script_size_offset, 4096),
            "script",
        )

    deduped: list[StageStdMutant] = []
    seen: set[str] = set()
    for mutant in mutants:
        if mutant.sha256 in seen:
            continue
        seen.add(mutant.sha256)
        deduped.append(mutant)
    return deduped
