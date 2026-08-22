from __future__ import annotations

from .model import EclFile


def serialize_ecl(ecl: EclFile) -> bytes:
    sub_count = len(ecl.subs)
    header_size = 16 + 4 * sub_count
    sub_blobs = [sub.to_bytes() for sub in ecl.subs]
    current_offset = header_size
    sub_offsets: list[int] = []
    for blob in sub_blobs:
        sub_offsets.append(current_offset)
        current_offset += len(blob)
    timeline_blob = b"".join(instruction.to_bytes() for instruction in ecl.timeline)
    timeline_offset = current_offset
    output = bytearray()
    output += int(sub_count).to_bytes(2, "little", signed=True)
    output += int(ecl.main_count).to_bytes(2, "little", signed=True)
    output += int(timeline_offset).to_bytes(4, "little", signed=False)
    output += (0).to_bytes(4, "little", signed=False)
    output += (0).to_bytes(4, "little", signed=False)
    for offset in sub_offsets:
        output += int(offset).to_bytes(4, "little", signed=False)
    for blob in sub_blobs:
        output += blob
    output += timeline_blob
    return bytes(output)
