from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self
import copy


@dataclass
class TimelineInstruction:
    time: int
    arg0: int
    opcode: int
    size: int
    args: bytes = b""

    def to_bytes(self) -> bytes:
        return (
            int(self.time).to_bytes(2, "little", signed=True)
            + int(self.arg0).to_bytes(2, "little", signed=True)
            + int(self.opcode).to_bytes(2, "little", signed=True)
            + int(self.size).to_bytes(2, "little", signed=True)
            + self.args
        )


@dataclass
class RawInstruction:
    time: int
    opcode: int
    offset_to_next: int
    unk8: int
    skip_for_difficulty: int
    unk_a: int
    unk_b: int
    args: bytes = b""

    def to_bytes(self) -> bytes:
        return (
            int(self.time).to_bytes(4, "little", signed=True)
            + int(self.opcode).to_bytes(2, "little", signed=True)
            + int(self.offset_to_next).to_bytes(2, "little", signed=True)
            + bytes((self.unk8 & 0xFF, self.skip_for_difficulty & 0xFF, self.unk_a & 0xFF, self.unk_b & 0xFF))
            + self.args
        )


@dataclass
class EclSubroutine:
    file_offset: int
    instructions: list[RawInstruction] = field(default_factory=list)

    def to_bytes(self) -> bytes:
        return b"".join(instruction.to_bytes() for instruction in self.instructions)


@dataclass
class EclFile:
    sub_count: int
    main_count: int
    timeline_offsets: tuple[int, int, int]
    timeline: list[TimelineInstruction]
    subs: list[EclSubroutine]
    source_payload: bytes | None = field(default=None, repr=False, compare=False)

    def clone(self) -> Self:
        return copy.deepcopy(self)
