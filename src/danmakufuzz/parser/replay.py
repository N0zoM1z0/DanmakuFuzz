from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import json
from pathlib import Path
import struct
from typing import Mapping, Sequence


GAME_VERSION = 0x102


class ReplayHeader(ctypes.LittleEndianStructure):
    _fields_ = [
        ("magic", ctypes.c_char * 4),
        ("version", ctypes.c_uint16),
        ("shottypeChara", ctypes.c_uint8),
        ("difficulty", ctypes.c_uint8),
        ("checksum", ctypes.c_int32),
        ("rngValue1", ctypes.c_uint8),
        ("rngValue2", ctypes.c_uint8),
        ("key", ctypes.c_int8),
        ("rngValue3", ctypes.c_int8),
        ("date", ctypes.c_char * 9),
        ("name", ctypes.c_char * 8),
        ("score", ctypes.c_int32),
        ("slowdownRate2", ctypes.c_float),
        ("slowdownRate", ctypes.c_float),
        ("slowdownRate3", ctypes.c_float),
        ("stageReplayDataOffsets", ctypes.c_uint32 * 7),
    ]


class ReplayDataInput(ctypes.LittleEndianStructure):
    _fields_ = [
        ("frameNum", ctypes.c_int32),
        ("inputKey", ctypes.c_uint16),
        ("padding", ctypes.c_uint16),
    ]


class StageReplayDataPrefix(ctypes.LittleEndianStructure):
    _fields_ = [
        ("score", ctypes.c_int32),
        ("randomSeed", ctypes.c_int16),
        ("pointItemsCollected", ctypes.c_int16),
        ("power", ctypes.c_uint8),
        ("livesRemaining", ctypes.c_int8),
        ("bombsRemaining", ctypes.c_int8),
        ("rank", ctypes.c_uint8),
        ("powerItemCountForScore", ctypes.c_int8),
        ("padding", ctypes.c_uint8 * 3),
    ]


REPLAY_STAGE_SENTINEL_FRAME = 9_999_999


@dataclass(frozen=True)
class ReplayInputBookmark:
    frame: int
    input_mask: int


@dataclass(frozen=True)
class ReplayStageData:
    stage_index: int
    score: int
    random_seed: int
    point_items_collected: int
    power: int
    lives_remaining: int
    bombs_remaining: int
    rank: int
    power_item_count_for_score: int
    input_bookmarks: tuple[ReplayInputBookmark, ...]
    payload_size: int


def _decode_ascii(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").rstrip()


def _encode_ascii_field(value: str, *, size: int) -> bytes:
    encoded = value.encode("ascii", errors="replace")
    if len(encoded) > size:
        raise ValueError(f"ascii field exceeds fixed size {size}: {value!r}")
    return encoded.ljust(size, b"\x00")


def deobfuscate_replay(data: bytes) -> bytes:
    if len(data) < ctypes.sizeof(ReplayHeader):
        raise ValueError("replay payload is smaller than ReplayHeader")
    decoded = bytearray(data)
    key_offset = ReplayHeader.key.offset
    rng3_offset = ReplayHeader.rngValue3.offset
    obfuscation = decoded[key_offset] & 0xFF
    for index in range(rng3_offset, len(decoded)):
        decoded[index] = (decoded[index] - obfuscation) & 0xFF
        obfuscation = (obfuscation + 7) & 0xFF
    return bytes(decoded)


def obfuscate_replay(decoded: bytes) -> bytes:
    if len(decoded) < ctypes.sizeof(ReplayHeader):
        raise ValueError("decoded replay payload is smaller than ReplayHeader")
    encoded = bytearray(decoded)
    key_offset = ReplayHeader.key.offset
    rng3_offset = ReplayHeader.rngValue3.offset
    obfuscation = encoded[key_offset] & 0xFF
    for index in range(rng3_offset, len(encoded)):
        encoded[index] = (encoded[index] + obfuscation) & 0xFF
        obfuscation = (obfuscation + 7) & 0xFF
    return bytes(encoded)


def compute_replay_checksum(decoded: bytes) -> int:
    if len(decoded) < ctypes.sizeof(ReplayHeader):
        raise ValueError("decoded replay payload is smaller than ReplayHeader")
    checksum = 0x3F000318
    for value in decoded[ReplayHeader.key.offset:]:
        checksum = (checksum + value) & 0xFFFFFFFF
    return checksum


def with_replay_checksum(decoded: bytes) -> bytes:
    checksum = compute_replay_checksum(decoded)
    mutable = bytearray(decoded)
    struct.pack_into(
        "<i",
        mutable,
        ReplayHeader.checksum.offset,
        checksum if checksum < 0x80000000 else checksum - 0x100000000,
    )
    return bytes(mutable)


def build_replay(
    *,
    version: int = GAME_VERSION,
    shottype_chara: int = 0,
    difficulty: int = 3,
    key: int = 0x31,
    rng_value1: int = 0x12,
    rng_value2: int = 0x34,
    rng_value3: int = 0x05,
    date: str = "20260822",
    name: str = "DANMAKU",
    score: int = 12345678,
    slowdown_rate: float = 1.0,
    slowdown_rate2: float = 1.0,
    slowdown_rate3: float = 1.0,
    stage_payloads: Sequence[bytes] = (),
) -> bytes:
    stage_slots: list[bytes | None] = list(stage_payloads)
    return build_replay_with_stage_slots(
        version=version,
        shottype_chara=shottype_chara,
        difficulty=difficulty,
        key=key,
        rng_value1=rng_value1,
        rng_value2=rng_value2,
        rng_value3=rng_value3,
        date=date,
        name=name,
        score=score,
        slowdown_rate=slowdown_rate,
        slowdown_rate2=slowdown_rate2,
        slowdown_rate3=slowdown_rate3,
        stage_payloads_by_slot=stage_slots,
    )


def build_replay_with_stage_slots(
    *,
    version: int = GAME_VERSION,
    shottype_chara: int = 0,
    difficulty: int = 3,
    key: int = 0x31,
    rng_value1: int = 0x12,
    rng_value2: int = 0x34,
    rng_value3: int = 0x05,
    date: str = "20260822",
    name: str = "DANMAKU",
    score: int = 12345678,
    slowdown_rate: float = 1.0,
    slowdown_rate2: float = 1.0,
    slowdown_rate3: float = 1.0,
    stage_payloads_by_slot: Sequence[bytes | None] = (),
) -> bytes:
    if len(stage_payloads_by_slot) > 7:
        raise ValueError("TH06 replay supports at most 7 stage payloads")
    header = ReplayHeader()
    header.magic = b"T6RP"
    header.version = version & 0xFFFF
    header.shottypeChara = shottype_chara & 0xFF
    header.difficulty = difficulty & 0xFF
    header.checksum = 0
    header.rngValue1 = rng_value1 & 0xFF
    header.rngValue2 = rng_value2 & 0xFF
    if not (-128 <= key <= 127):
        raise ValueError("replay key must fit in int8")
    if not (-128 <= rng_value3 <= 127):
        raise ValueError("replay rng_value3 must fit in int8")
    header.key = key
    header.rngValue3 = rng_value3
    header.date = _encode_ascii_field(date, size=9)
    header.name = _encode_ascii_field(name, size=8)
    header.score = score
    header.slowdownRate2 = float(slowdown_rate2)
    header.slowdownRate = float(slowdown_rate)
    header.slowdownRate3 = float(slowdown_rate3)

    header_size = ctypes.sizeof(ReplayHeader)
    offsets = [0] * 7
    payload_chunks: list[bytes] = []
    cursor = header_size
    for index in range(7):
        payload = stage_payloads_by_slot[index] if index < len(stage_payloads_by_slot) else None
        if payload is None:
            continue
        offsets[index] = cursor
        payload_chunks.append(bytes(payload))
        cursor += len(payload)
    for index, offset in enumerate(offsets):
        header.stageReplayDataOffsets[index] = offset

    decoded = bytearray(bytes(header))
    for payload in payload_chunks:
        decoded.extend(payload)
    return obfuscate_replay(with_replay_checksum(bytes(decoded)))


def synthetic_replay_seed() -> bytes:
    return build_replay(
        shottype_chara=1,
        difficulty=2,
        key=0x31,
        rng_value1=0x12,
        rng_value2=0x34,
        rng_value3=0x05,
        date="20260822",
        name="DANMAKU",
        score=98765432,
        stage_payloads=(
            b"\x10\x20\x30\x40",
            b"\x50\x60\x70\x80\x90",
            b"\xA0\xB0\xC0\xD0\xE0\xF0",
        ),
    )


def _stage_payload_bounds(decoded: bytes, stage_offsets: Sequence[int]) -> list[tuple[int, int] | None]:
    nonzero = [(index, offset) for index, offset in enumerate(stage_offsets) if offset != 0]
    bounds: list[tuple[int, int] | None] = [None] * 7
    for position, (stage_index, start) in enumerate(nonzero):
        end = len(decoded)
        if position + 1 < len(nonzero):
            end = nonzero[position + 1][1]
        bounds[stage_index] = (start, end)
    return bounds


def extract_stage_payloads(data: bytes) -> list[bytes | None]:
    decoded = deobfuscate_replay(data)
    header = ReplayHeader.from_buffer_copy(decoded)
    stage_offsets = [int(offset) for offset in header.stageReplayDataOffsets]
    payloads: list[bytes | None] = [None] * 7
    for stage_index, bound in enumerate(_stage_payload_bounds(decoded, stage_offsets)):
        if bound is None:
            continue
        start, end = bound
        payloads[stage_index] = decoded[start:end]
    return payloads


def parse_stage_replay_data(data: bytes) -> list[ReplayStageData | None]:
    decoded = deobfuscate_replay(data)
    header = ReplayHeader.from_buffer_copy(decoded)
    stage_offsets = [int(offset) for offset in header.stageReplayDataOffsets]
    prefix_size = ctypes.sizeof(StageReplayDataPrefix)
    input_size = ctypes.sizeof(ReplayDataInput)
    parsed: list[ReplayStageData | None] = [None] * 7
    for stage_index, bound in enumerate(_stage_payload_bounds(decoded, stage_offsets)):
        if bound is None:
            continue
        start, end = bound
        payload = decoded[start:end]
        if len(payload) < prefix_size:
            raise ValueError(f"stage {stage_index + 1} replay payload is smaller than StageReplayDataPrefix")
        prefix = StageReplayDataPrefix.from_buffer_copy(payload)
        cursor = prefix_size
        bookmarks: list[ReplayInputBookmark] = []
        while cursor + input_size <= len(payload):
            raw = ReplayDataInput.from_buffer_copy(payload, cursor)
            bookmark = ReplayInputBookmark(frame=int(raw.frameNum), input_mask=int(raw.inputKey))
            bookmarks.append(bookmark)
            cursor += input_size
            if bookmark.frame == REPLAY_STAGE_SENTINEL_FRAME:
                break
        if not bookmarks:
            raise ValueError(f"stage {stage_index + 1} replay payload has no input bookmarks")
        if bookmarks[0].frame != 0:
            raise ValueError(f"stage {stage_index + 1} replay input stream does not start at frame 0")
        for left, right in zip(bookmarks, bookmarks[1:], strict=False):
            if left.frame > right.frame:
                raise ValueError(f"stage {stage_index + 1} replay input frames are not monotonic")
        parsed[stage_index] = ReplayStageData(
            stage_index=stage_index + 1,
            score=int(prefix.score),
            random_seed=int(prefix.randomSeed),
            point_items_collected=int(prefix.pointItemsCollected),
            power=int(prefix.power),
            lives_remaining=int(prefix.livesRemaining),
            bombs_remaining=int(prefix.bombsRemaining),
            rank=int(prefix.rank),
            power_item_count_for_score=int(prefix.powerItemCountForScore),
            input_bookmarks=tuple(bookmarks),
            payload_size=len(payload),
        )
    return parsed


def expand_replay_input_bookmarks(
    bookmarks: Sequence[ReplayInputBookmark],
    *,
    max_frames: int | None = None,
) -> list[int]:
    if not bookmarks:
        raise ValueError("replay input bookmark stream must not be empty")
    effective_end = bookmarks[-1].frame
    if effective_end == REPLAY_STAGE_SENTINEL_FRAME and len(bookmarks) >= 2:
        effective_end = bookmarks[-2].frame
    if max_frames is not None:
        effective_end = min(effective_end, int(max_frames))
    if effective_end < 0:
        return []
    masks: list[int] = []
    for index, bookmark in enumerate(bookmarks):
        if bookmark.frame >= effective_end:
            break
        next_frame = effective_end
        if index + 1 < len(bookmarks):
            next_frame = min(next_frame, bookmarks[index + 1].frame)
        if next_frame < bookmark.frame:
            raise ValueError("replay input bookmarks are not monotonic")
        masks.extend([bookmark.input_mask] * max(0, next_frame - bookmark.frame))
    return masks


def encode_stage_replay_data(
    *,
    input_bookmarks: Sequence[ReplayInputBookmark],
    score: int = 0,
    random_seed: int = 0,
    point_items_collected: int = 0,
    power: int = 0,
    lives_remaining: int = 2,
    bombs_remaining: int = 3,
    rank: int = 0,
    power_item_count_for_score: int = 0,
) -> bytes:
    if not input_bookmarks:
        raise ValueError("stage replay input bookmarks must not be empty")
    prefix = StageReplayDataPrefix()
    prefix.score = int(score)
    prefix.randomSeed = int(random_seed)
    prefix.pointItemsCollected = int(point_items_collected)
    prefix.power = int(power) & 0xFF
    prefix.livesRemaining = int(lives_remaining)
    prefix.bombsRemaining = int(bombs_remaining)
    prefix.rank = int(rank) & 0xFF
    prefix.powerItemCountForScore = int(power_item_count_for_score)
    buffer = bytearray(bytes(prefix))
    last_frame = -1
    for bookmark in input_bookmarks:
        if bookmark.frame < 0:
            raise ValueError("replay bookmark frame must be non-negative")
        if bookmark.frame < last_frame:
            raise ValueError("replay bookmark frames must be monotonic")
        last_frame = bookmark.frame
        raw = ReplayDataInput()
        raw.frameNum = int(bookmark.frame)
        raw.inputKey = int(bookmark.input_mask) & 0xFFFF
        raw.padding = 0
        buffer.extend(bytes(raw))
    if input_bookmarks[-1].frame != REPLAY_STAGE_SENTINEL_FRAME:
        sentinel = ReplayDataInput()
        sentinel.frameNum = REPLAY_STAGE_SENTINEL_FRAME
        sentinel.inputKey = 0
        sentinel.padding = 0
        buffer.extend(bytes(sentinel))
    return bytes(buffer)


def input_masks_to_replay_bookmarks(input_masks: Sequence[int]) -> tuple[ReplayInputBookmark, ...]:
    if not input_masks:
        return (
            ReplayInputBookmark(frame=0, input_mask=0),
            ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0),
        )
    bookmarks: list[ReplayInputBookmark] = [ReplayInputBookmark(frame=0, input_mask=int(input_masks[0]) & 0xFFFF)]
    previous = int(input_masks[0]) & 0xFFFF
    for frame, input_mask in enumerate(input_masks[1:], start=1):
        mask = int(input_mask) & 0xFFFF
        if mask == previous:
            continue
        bookmarks.append(ReplayInputBookmark(frame=frame, input_mask=mask))
        previous = mask
    if previous != 0:
        bookmarks.append(ReplayInputBookmark(frame=len(input_masks), input_mask=0))
    bookmarks.append(ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0))
    return tuple(bookmarks)


def replay_stage_action_masks(data: bytes, stage: int, *, max_frames: int | None = None) -> list[int]:
    if not (1 <= stage <= 7):
        raise ValueError(f"replay stage must be 1..7, got {stage}")
    stage_data = parse_stage_replay_data(data)[stage - 1]
    if stage_data is None:
        raise ValueError(f"replay payload has no stage {stage} data")
    return expand_replay_input_bookmarks(stage_data.input_bookmarks, max_frames=max_frames)


def replace_replay_stage_payloads(seed_payload: bytes, payload_overrides: Mapping[int, bytes]) -> bytes:
    decoded = deobfuscate_replay(seed_payload)
    header = ReplayHeader.from_buffer_copy(decoded)
    stage_payloads = extract_stage_payloads(seed_payload)
    stage_slots: list[bytes | None] = list(stage_payloads)
    for stage, payload in payload_overrides.items():
        if not (1 <= int(stage) <= 7):
            raise ValueError(f"replay stage slot must be 1..7, got {stage}")
        stage_slots[int(stage) - 1] = bytes(payload)
    return build_replay_with_stage_slots(
        version=int(header.version),
        shottype_chara=int(header.shottypeChara),
        difficulty=int(header.difficulty),
        key=int(header.key),
        rng_value1=int(header.rngValue1),
        rng_value2=int(header.rngValue2),
        rng_value3=int(header.rngValue3),
        date=_decode_ascii(bytes(header.date)),
        name=_decode_ascii(bytes(header.name)),
        score=int(header.score),
        slowdown_rate=float(header.slowdownRate),
        slowdown_rate2=float(header.slowdownRate2),
        slowdown_rate3=float(header.slowdownRate3),
        stage_payloads_by_slot=stage_slots,
    )


def validate_replay(data: bytes) -> dict[str, object]:
    if len(data) < ctypes.sizeof(ReplayHeader):
        raise ValueError("replay payload is smaller than ReplayHeader")
    raw_header = ReplayHeader.from_buffer_copy(data)
    if bytes(raw_header.magic) != b"T6RP":
        raise ValueError("replay does not have T6RP magic")

    decoded = deobfuscate_replay(data)
    header = ReplayHeader.from_buffer_copy(decoded)

    checksum = compute_replay_checksum(decoded)
    expected_checksum = header.checksum & 0xFFFFFFFF
    if checksum != expected_checksum:
        raise ValueError(f"replay checksum mismatch: {checksum:#x} != {expected_checksum:#x}")
    if header.version != GAME_VERSION:
        raise ValueError(f"unexpected replay version: {header.version:#x}")

    stage_offsets = [int(offset) for offset in header.stageReplayDataOffsets]
    nonzero_offsets = [offset for offset in stage_offsets if offset != 0]
    if any(offset < ctypes.sizeof(ReplayHeader) or offset >= len(decoded) for offset in nonzero_offsets):
        raise ValueError("replay stage data offset is outside the payload")
    if any(left >= right for left, right in zip(nonzero_offsets, nonzero_offsets[1:], strict=False)):
        raise ValueError("replay stage data offsets are not increasing")

    return {
        "header_size": ctypes.sizeof(ReplayHeader),
        "version": header.version,
        "difficulty": header.difficulty,
        "shottype_chara": header.shottypeChara,
        "score": header.score,
        "name": _decode_ascii(bytes(header.name)),
        "date": _decode_ascii(bytes(header.date)),
        "stage_offsets": stage_offsets,
        "decoded_size": len(decoded),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and deobfuscate TH06 replay files.")
    parser.add_argument("--input", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing replay file: {input_path}")
    result = {"input": str(input_path), **validate_replay(input_path.read_bytes())}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
