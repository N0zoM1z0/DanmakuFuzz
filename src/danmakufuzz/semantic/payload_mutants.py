from __future__ import annotations

from dataclasses import dataclass

from ..ecl_ir.mutators import generate_targeted_mutants
from ..ecl_ir.parser import parse_ecl
from ..ecl_ir.serializer import serialize_ecl


@dataclass(frozen=True)
class PayloadMutant:
    name: str
    payload: bytes
    source: str
    path: tuple[int, int] | None = None


def _replace_i16(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    mutable[offset:offset + 2] = int(value).to_bytes(2, "little", signed=True)
    return bytes(mutable)


def _replace_u32(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    mutable[offset:offset + 4] = int(value).to_bytes(4, "little", signed=False)
    return bytes(mutable)


def generate_structural_mutants(seed_payload: bytes) -> list[PayloadMutant]:
    mutants = [
        PayloadMutant(name="struct-empty-file", payload=b"", source="structural"),
        PayloadMutant(name="struct-truncate-half", payload=seed_payload[: max(1, len(seed_payload) // 2)], source="structural"),
        PayloadMutant(name="struct-primary-timeline-zero", payload=_replace_u32(seed_payload, 4, 0), source="structural"),
        PayloadMutant(
            name="struct-primary-timeline-outside",
            payload=_replace_u32(seed_payload, 4, len(seed_payload) + 0x100),
            source="structural",
        ),
        PayloadMutant(name="struct-subcount-zero", payload=_replace_i16(seed_payload, 0, 0), source="structural"),
    ]
    sub_count = int.from_bytes(seed_payload[0:2], "little", signed=True)
    if sub_count > 0:
        mutants.append(PayloadMutant(name="struct-first-sub-zero", payload=_replace_u32(seed_payload, 16, 0), source="structural"))
        mutants.append(
            PayloadMutant(
                name="struct-first-sub-outside",
                payload=_replace_u32(seed_payload, 16, len(seed_payload) + 0x100),
                source="structural",
            )
        )
    return mutants


def generate_payload_mutants(seed_payload: bytes, *, include_structural: bool = True) -> list[PayloadMutant]:
    mutants: list[PayloadMutant] = []
    if include_structural:
        mutants.extend(generate_structural_mutants(seed_payload))

    ecl = parse_ecl(seed_payload)
    for mutant in generate_targeted_mutants(ecl):
        mutants.append(
            PayloadMutant(
                name=mutant.name,
                payload=serialize_ecl(mutant.ecl),
                source="ir",
                path=mutant.path,
            )
        )
    return mutants
