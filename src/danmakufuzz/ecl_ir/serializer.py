from __future__ import annotations

from .model import EclFile


def serialize_ecl(ecl: EclFile) -> bytes:
    sub_count = len(ecl.subs)
    header_size = 16 + 4 * sub_count
    timeline_blob = b"".join(instruction.to_bytes() for instruction in ecl.timeline)
    sub_blobs = [sub.to_bytes() for sub in ecl.subs]
    timeline_offset = header_size
    current_offset = timeline_offset + len(timeline_blob)
    sub_offsets: list[int] = []
    for blob in sub_blobs:
        sub_offsets.append(current_offset)
        current_offset += len(blob)
    output = bytearray()
    output += int(sub_count).to_bytes(2, "little", signed=True)
    output += int(ecl.main_count).to_bytes(2, "little", signed=True)
    output += int(timeline_offset).to_bytes(4, "little", signed=False)
    output += int(ecl.timeline_offsets[1]).to_bytes(4, "little", signed=False)
    output += int(ecl.timeline_offsets[2]).to_bytes(4, "little", signed=False)
    for offset in sub_offsets:
        output += int(offset).to_bytes(4, "little", signed=False)
    output += timeline_blob
    for blob in sub_blobs:
        output += blob
    return bytes(output)
