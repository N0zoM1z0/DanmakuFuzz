from __future__ import annotations

from .model import EclFile, EclSubroutine, RawInstruction, TimelineInstruction


class EclParseError(ValueError):
    """Raised when an ECL payload is structurally invalid."""


def _i16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little", signed=True)


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little", signed=False)


def _i32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little", signed=True)


def _next_boundary(offset: int, boundaries: list[int], data_size: int) -> int:
    for boundary in boundaries:
        if boundary > offset:
            return boundary
    return data_size


def parse_timeline(data: bytes, start: int, end: int) -> list[TimelineInstruction]:
    instructions: list[TimelineInstruction] = []
    cursor = start
    while cursor + 8 <= end:
        time = _i16(data, cursor)
        arg0 = _i16(data, cursor + 2)
        opcode = _i16(data, cursor + 4)
        size = _i16(data, cursor + 6)
        if size < 8 or cursor + size > end:
            raise EclParseError(f"invalid timeline instruction size at {cursor:#x}: {size}")
        args = data[cursor + 8:cursor + size]
        instructions.append(TimelineInstruction(time=time, arg0=arg0, opcode=opcode, size=size, args=args))
        cursor += size
        if time < 0:
            break
    if not instructions:
        raise EclParseError("timeline is empty")
    return instructions


def parse_sub(data: bytes, start: int, end: int) -> EclSubroutine:
    cursor = start
    instructions: list[RawInstruction] = []
    while cursor + 12 <= end:
        time = _i32(data, cursor)
        opcode = _i16(data, cursor + 4)
        offset_to_next = _i16(data, cursor + 6)
        if offset_to_next < 12 or cursor + offset_to_next > end:
            raise EclParseError(f"invalid raw instruction size at {cursor:#x}: {offset_to_next}")
        instruction = RawInstruction(
            time=time,
            opcode=opcode,
            offset_to_next=offset_to_next,
            unk8=data[cursor + 8],
            skip_for_difficulty=data[cursor + 9],
            unk_a=data[cursor + 10],
            unk_b=data[cursor + 11],
            args=data[cursor + 12:cursor + offset_to_next],
        )
        instructions.append(instruction)
        cursor += offset_to_next
        if cursor == end:
            break
    if not instructions:
        raise EclParseError(f"subroutine at {start:#x} is empty")
    return EclSubroutine(file_offset=start, instructions=instructions)


def parse_ecl(data: bytes) -> EclFile:
    if len(data) < 16:
        raise EclParseError("ECL payload is too small")
    sub_count = _i16(data, 0)
    main_count = _i16(data, 2)
    timeline_offsets = (_u32(data, 4), _u32(data, 8), _u32(data, 12))
    if sub_count < 0:
        raise EclParseError(f"negative sub_count: {sub_count}")
    table_size = 16 + 4 * sub_count
    if len(data) < table_size:
        raise EclParseError("truncated subroutine offset table")
    sub_offsets = [_u32(data, 16 + 4 * index) for index in range(sub_count)]
    if not sub_offsets:
        raise EclParseError("ECL has no subroutines")
    if any(offset >= len(data) for offset in sub_offsets):
        raise EclParseError("subroutine offset is outside the payload")
    sorted_offsets = sorted(sub_offsets)
    nonzero_timeline_offsets = [offset for offset in timeline_offsets if offset != 0]
    if not nonzero_timeline_offsets:
        raise EclParseError("ECL has no timeline offset")
    if any(offset >= len(data) for offset in nonzero_timeline_offsets):
        raise EclParseError("timeline offset is outside the payload")

    boundaries = sorted(set(sorted_offsets + nonzero_timeline_offsets + [len(data)]))
    timeline_start = timeline_offsets[0]
    if timeline_start == 0:
        raise EclParseError("primary timeline offset is zero")
    if timeline_start < table_size:
        raise EclParseError("primary timeline overlaps header")
    timeline_end = _next_boundary(timeline_start, boundaries, len(data))
    timeline = parse_timeline(data, timeline_start, timeline_end)

    subs: list[EclSubroutine] = []
    for sub_offset in sub_offsets:
        end = _next_boundary(sub_offset, boundaries, len(data))
        subs.append(parse_sub(data, sub_offset, end))
    return EclFile(
        sub_count=sub_count,
        main_count=main_count,
        timeline_offsets=timeline_offsets,
        timeline=timeline,
        subs=subs,
        source_payload=data,
    )
