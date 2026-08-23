from __future__ import annotations

from .model import EclFile


class EclSerializeError(ValueError):
    """Raised when an ECL payload cannot be serialized in the requested mode."""


def _reject_unsupported_canonical_layout(ecl: EclFile, *, allow_multi_timeline: bool) -> None:
    secondary_offsets = [offset for offset in ecl.timeline_offsets[1:] if offset != 0]
    if secondary_offsets and not allow_multi_timeline:
        raise EclSerializeError(
            "canonical ECL serialization does not preserve secondary timeline offsets; "
            f"got {ecl.timeline_offsets!r}"
        )


def serialize_ecl_canonical(ecl: EclFile, *, allow_multi_timeline: bool = False) -> bytes:
    _reject_unsupported_canonical_layout(ecl, allow_multi_timeline=allow_multi_timeline)
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


def serialize_ecl_lossless(ecl: EclFile) -> bytes:
    if ecl.source_payload is None:
        raise EclSerializeError("lossless ECL serialization requires an ECL parsed from source bytes")

    from .parser import parse_ecl

    original = parse_ecl(ecl.source_payload)
    if original != ecl:
        raise EclSerializeError("lossless ECL serialization cannot emit a modified IR without layout metadata")
    return ecl.source_payload


def serialize_ecl(ecl: EclFile) -> bytes:
    return serialize_ecl_canonical(ecl)
