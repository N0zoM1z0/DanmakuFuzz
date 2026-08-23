from __future__ import annotations

from dataclasses import replace
import hashlib
import random
import struct
from typing import Sequence

from ..parser.replay import (
    REPLAY_STAGE_SENTINEL_FRAME,
    ReplayHeader,
    ReplayInputBookmark,
    ReplayStageData,
    deobfuscate_replay,
    encode_stage_replay_data,
    extract_stage_payloads,
    parse_stage_replay_data,
    replay_stage_action_masks,
    replace_replay_stage_payloads,
    with_replay_checksum,
    obfuscate_replay,
)
from .replay_input_mutants import ReplayInputMutant


def _replace_u8(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    struct.pack_into("<B", mutable, offset, value & 0xFF)
    return bytes(mutable)


def _rechecksum(decoded: bytes) -> bytes:
    return obfuscate_replay(with_replay_checksum(decoded))


def _site_rng(random_seed: int, *, family: str, site: int) -> random.Random:
    digest = hashlib.sha256(f"{random_seed}:{family}:{site}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "little", signed=False))


def _stage_payload_from_bookmarks(
    stage_data: ReplayStageData,
    bookmarks: Sequence[ReplayInputBookmark],
    *,
    random_seed: int | None = None,
) -> bytes:
    return encode_stage_replay_data(
        input_bookmarks=bookmarks,
        score=stage_data.score,
        random_seed=stage_data.random_seed if random_seed is None else int(random_seed),
        point_items_collected=stage_data.point_items_collected,
        power=stage_data.power,
        lives_remaining=stage_data.lives_remaining,
        bombs_remaining=stage_data.bombs_remaining,
        rank=stage_data.rank,
        power_item_count_for_score=stage_data.power_item_count_for_score,
    )


def _candidate_bookmark_indexes(bookmarks: Sequence[ReplayInputBookmark]) -> list[int]:
    if len(bookmarks) <= 2:
        return []
    usable = [
        index
        for index in range(1, len(bookmarks) - 1)
        if bookmarks[index].frame != REPLAY_STAGE_SENTINEL_FRAME
    ]
    if not usable:
        return []
    anchors = {
        usable[0],
        usable[len(usable) // 4],
        usable[len(usable) // 2],
        usable[(len(usable) * 3) // 4],
        usable[-1],
    }
    return sorted(index for index in anchors if index in usable)


def _mutated_bookmarks_drop(
    bookmarks: Sequence[ReplayInputBookmark],
    *,
    index: int,
) -> tuple[ReplayInputBookmark, ...] | None:
    if not (0 < index < len(bookmarks) - 1):
        return None
    mutated = list(bookmarks)
    del mutated[index]
    if len(mutated) < 2:
        return None
    return tuple(mutated)


def _mutated_bookmarks_cut_tail(
    bookmarks: Sequence[ReplayInputBookmark],
    *,
    index: int,
) -> tuple[ReplayInputBookmark, ...] | None:
    if not (0 < index < len(bookmarks) - 1):
        return None
    cut_frame = int(bookmarks[index].frame)
    if cut_frame <= 0:
        return None
    prefix = list(bookmarks[:index])
    if not prefix:
        return None
    if prefix[-1].frame != cut_frame or prefix[-1].input_mask != 0:
        prefix.append(ReplayInputBookmark(frame=cut_frame, input_mask=0))
    prefix.append(ReplayInputBookmark(frame=REPLAY_STAGE_SENTINEL_FRAME, input_mask=0))
    return tuple(prefix)


def _mutated_bookmarks_snap_prev(
    bookmarks: Sequence[ReplayInputBookmark],
    *,
    index: int,
) -> tuple[ReplayInputBookmark, ...] | None:
    if not (0 < index < len(bookmarks) - 1):
        return None
    previous = bookmarks[index - 1]
    current = bookmarks[index]
    if current.frame == previous.frame:
        return None
    mutated = list(bookmarks)
    mutated[index] = replace(current, frame=previous.frame)
    return tuple(mutated)


def _mutated_bookmarks_shift(
    bookmarks: Sequence[ReplayInputBookmark],
    *,
    index: int,
    delta: int,
) -> tuple[ReplayInputBookmark, ...] | None:
    if not (0 < index < len(bookmarks) - 1):
        return None
    previous = bookmarks[index - 1]
    current = bookmarks[index]
    next_bookmark = bookmarks[index + 1]
    new_frame = int(current.frame) + int(delta)
    new_frame = max(int(previous.frame), new_frame)
    new_frame = min(int(next_bookmark.frame), new_frame)
    if new_frame == current.frame:
        return None
    mutated = list(bookmarks)
    mutated[index] = replace(current, frame=new_frame)
    return tuple(mutated)


def _add_mutant(
    mutants: list[ReplayInputMutant],
    seen: set[str],
    *,
    name: str,
    payload: bytes,
    stage: int,
    source: str,
    metadata: dict[str, object],
    max_frames: int | None,
) -> None:
    sha256 = hashlib.sha256(payload).hexdigest()
    if sha256 in seen:
        return
    try:
        action_count = len(replay_stage_action_masks(payload, stage, max_frames=max_frames))
    except Exception:
        action_count = 0
    seen.add(sha256)
    mutants.append(
        ReplayInputMutant(
            name=name,
            payload=payload,
            source=source,
            sha256=sha256,
            stage=stage,
            action_count=action_count,
            metadata=metadata,
        )
    )


def generate_replay_native_mutants(
    seed_payload: bytes,
    *,
    stage: int,
    max_frames: int | None = None,
    random_seed: int = 0,
    samples_per_site: int = 4,
) -> list[ReplayInputMutant]:
    if not (1 <= stage <= 7):
        raise ValueError(f"replay stage must be 1..7, got {stage}")
    parsed = parse_stage_replay_data(seed_payload)
    stage_data = parsed[stage - 1]
    if stage_data is None:
        raise ValueError(f"replay payload has no stage {stage} data")

    decoded = deobfuscate_replay(seed_payload)
    header = ReplayHeader.from_buffer_copy(decoded)
    stage_payloads = extract_stage_payloads(seed_payload)
    mutants: list[ReplayInputMutant] = []
    seen: set[str] = set()

    for difficulty in range(4):
        if difficulty == int(header.difficulty):
            continue
        mutated_decoded = _replace_u8(decoded, ReplayHeader.difficulty.offset, difficulty)
        _add_mutant(
            mutants,
            seen,
            name=f"header-difficulty-{difficulty}",
            payload=_rechecksum(mutated_decoded),
            stage=stage,
            source="replay-native",
            metadata={
                "family": "header-difficulty",
                "site_key": "header:difficulty",
                "stage": stage,
                "difficulty": difficulty,
            },
            max_frames=max_frames,
        )

    for shottype_chara in range(4):
        if shottype_chara == int(header.shottypeChara):
            continue
        mutated_decoded = _replace_u8(decoded, ReplayHeader.shottypeChara.offset, shottype_chara)
        _add_mutant(
            mutants,
            seen,
            name=f"header-route-{shottype_chara}",
            payload=_rechecksum(mutated_decoded),
            stage=stage,
            source="replay-native",
            metadata={
                "family": "header-route",
                "site_key": "header:route",
                "stage": stage,
                "shottype_chara": shottype_chara,
                "character": shottype_chara // 2,
                "shot_type": shottype_chara % 2,
            },
            max_frames=max_frames,
        )

    for seed_value in (0, 1, 7, 0x1234, 0x7FFF, -1, -0x8000):
        if seed_value == stage_data.random_seed:
            continue
        stage_payload = _stage_payload_from_bookmarks(
            stage_data,
            stage_data.input_bookmarks,
            random_seed=seed_value,
        )
        payload = replace_replay_stage_payloads(seed_payload, {stage: stage_payload})
        _add_mutant(
            mutants,
            seen,
            name=f"stage-seed-{seed_value & 0xFFFF:04x}",
            payload=payload,
            stage=stage,
            source="replay-native",
            metadata={
                "family": "stage-seed",
                "site_key": f"stage{stage}:seed",
                "stage": stage,
                "random_seed": seed_value,
                "random_seed_u16": seed_value & 0xFFFF,
            },
            max_frames=max_frames,
        )

    bookmarks = stage_data.input_bookmarks
    candidate_indexes = _candidate_bookmark_indexes(bookmarks)
    if candidate_indexes:
        bookmark_budget = max(2, samples_per_site)
        rng = _site_rng(random_seed, family="bookmark-sites", site=stage)
        if len(candidate_indexes) > bookmark_budget:
            extras = candidate_indexes[:]
            rng.shuffle(extras)
            keep = set(candidate_indexes[:2] + extras[: max(0, bookmark_budget - 2)])
            candidate_indexes = sorted(keep)

    for index in candidate_indexes:
        frame = int(bookmarks[index].frame)
        for family, builder in (
            ("bookmark-drop", _mutated_bookmarks_drop),
            ("bookmark-cut-tail", _mutated_bookmarks_cut_tail),
            ("bookmark-snap-prev", _mutated_bookmarks_snap_prev),
        ):
            mutated_bookmarks = builder(bookmarks, index=index)
            if mutated_bookmarks is None:
                continue
            stage_payload = _stage_payload_from_bookmarks(stage_data, mutated_bookmarks)
            payload = replace_replay_stage_payloads(seed_payload, {stage: stage_payload})
            _add_mutant(
                mutants,
                seen,
                name=f"{family}-i{index:03d}-t{frame}",
                payload=payload,
                stage=stage,
                source="replay-native",
                metadata={
                    "family": family,
                    "site_key": f"bookmark:{index:03d}",
                    "stage": stage,
                    "bookmark_index": index,
                    "frame": frame,
                },
                max_frames=max_frames,
            )

        shift_rng = _site_rng(random_seed, family="bookmark-shift", site=(stage << 16) ^ index)
        deltas = sorted({4, 8, 16, 32, max(1, shift_rng.randrange(2, 48))})
        for delta in deltas[: min(3, len(deltas))]:
            for direction_name, signed_delta in (("early", -delta), ("late", delta)):
                mutated_bookmarks = _mutated_bookmarks_shift(bookmarks, index=index, delta=signed_delta)
                if mutated_bookmarks is None:
                    continue
                stage_payload = _stage_payload_from_bookmarks(stage_data, mutated_bookmarks)
                payload = replace_replay_stage_payloads(seed_payload, {stage: stage_payload})
                _add_mutant(
                    mutants,
                    seen,
                    name=f"bookmark-shift-{direction_name}-d{delta}-i{index:03d}-t{frame}",
                    payload=payload,
                    stage=stage,
                    source="replay-native",
                    metadata={
                        "family": "bookmark-shift",
                        "site_key": f"bookmark:{index:03d}",
                        "stage": stage,
                        "bookmark_index": index,
                        "frame": frame,
                        "delta": signed_delta,
                    },
                    max_frames=max_frames,
                )

    for neighbor_stage, direction in ((stage - 1, "prev"), (stage + 1, "next")):
        if not (1 <= neighbor_stage <= 7):
            continue
        payload = stage_payloads[neighbor_stage - 1]
        if payload is None:
            continue
        mutated = replace_replay_stage_payloads(seed_payload, {stage: payload})
        _add_mutant(
            mutants,
            seen,
            name=f"stage-payload-borrow-{direction}-s{neighbor_stage}",
            payload=mutated,
            stage=stage,
            source="replay-native",
            metadata={
                "family": "stage-payload-borrow",
                "site_key": f"stage{stage}:borrow",
                "stage": stage,
                "borrowed_stage": neighbor_stage,
                "direction": direction,
            },
            max_frames=max_frames,
        )
    return mutants
