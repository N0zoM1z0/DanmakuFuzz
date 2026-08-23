from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Sequence

from ..parser.replay import (
    ReplayStageData,
    encode_stage_replay_data,
    input_masks_to_replay_bookmarks,
    parse_stage_replay_data,
    replay_stage_action_masks,
    replace_replay_stage_payloads,
)


TH_BUTTON_SHOOT = 1 << 0
TH_BUTTON_BOMB = 1 << 1
TH_BUTTON_FOCUS = 1 << 2
TH_BUTTON_UP = 1 << 4
TH_BUTTON_DOWN = 1 << 5
TH_BUTTON_LEFT = 1 << 6
TH_BUTTON_RIGHT = 1 << 7
TH_BUTTON_SKIP = 1 << 8
TH_BUTTON_DIRECTION = TH_BUTTON_UP | TH_BUTTON_DOWN | TH_BUTTON_LEFT | TH_BUTTON_RIGHT

CARDINAL_DIRECTIONS = (
    ("stay", 0),
    ("up", TH_BUTTON_UP),
    ("down", TH_BUTTON_DOWN),
    ("left", TH_BUTTON_LEFT),
    ("right", TH_BUTTON_RIGHT),
    ("up_left", TH_BUTTON_UP | TH_BUTTON_LEFT),
    ("up_right", TH_BUTTON_UP | TH_BUTTON_RIGHT),
    ("down_left", TH_BUTTON_DOWN | TH_BUTTON_LEFT),
    ("down_right", TH_BUTTON_DOWN | TH_BUTTON_RIGHT),
)


@dataclass(frozen=True)
class ReplayInputMutant:
    name: str
    payload: bytes
    source: str
    sha256: str
    stage: int
    action_count: int
    metadata: dict[str, object] | None = None


def replay_input_mutant_family(mutant: ReplayInputMutant) -> str:
    metadata = mutant.metadata or {}
    family = metadata.get("family")
    if isinstance(family, str) and family:
        return family
    return mutant.name.split("-", 1)[0]


def replay_input_mutant_site(mutant: ReplayInputMutant) -> str:
    metadata = mutant.metadata or {}
    site_key = metadata.get("site_key")
    if isinstance(site_key, str) and site_key:
        return site_key
    return "raw"


def _site_rng(random_seed: int, *, family: str, start: int, window: int) -> random.Random:
    material = f"{random_seed}:{family}:{start}:{window}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest[:8], "little", signed=False))


def _candidate_windows(length: int) -> list[int]:
    return sorted({size for size in (8, 16, 24, 32, 48, 64) if 0 < size <= length})


def _candidate_starts(length: int, *, minimum_window: int) -> list[int]:
    last_start = max(0, length - minimum_window)
    anchors = {
        0,
        length // 8,
        length // 4,
        length // 2,
        (length * 3) // 4,
        last_start,
    }
    return sorted(start for start in anchors if 0 <= start <= last_start)


def _sample_starts(length: int, *, minimum_window: int, budget: int, rng: random.Random) -> list[int]:
    starts = _candidate_starts(length, minimum_window=minimum_window)
    if len(starts) >= budget:
        return starts[:budget]
    pool = [start for start in range(max(1, length - minimum_window + 1)) if start not in starts]
    rng.shuffle(pool)
    starts.extend(pool[: max(0, budget - len(starts))])
    starts.sort()
    return starts


def _replace_window(
    input_masks: Sequence[int],
    *,
    start: int,
    window: int,
    transform,
) -> tuple[int, ...]:
    mutated = list(int(mask) & 0xFFFF for mask in input_masks)
    for offset in range(window):
        index = start + offset
        if index >= len(mutated):
            break
        mutated[index] = int(transform(mutated[index])) & 0xFFFF
    return tuple(mutated)


def _stage_payload_from_masks(stage_data: ReplayStageData, input_masks: Sequence[int]) -> bytes:
    return encode_stage_replay_data(
        input_bookmarks=input_masks_to_replay_bookmarks(input_masks),
        score=stage_data.score,
        random_seed=stage_data.random_seed,
        point_items_collected=stage_data.point_items_collected,
        power=stage_data.power,
        lives_remaining=stage_data.lives_remaining,
        bombs_remaining=stage_data.bombs_remaining,
        rank=stage_data.rank,
        power_item_count_for_score=stage_data.power_item_count_for_score,
    )


def _add_mutant(
    mutants: list[ReplayInputMutant],
    seen: set[str],
    *,
    seed_payload: bytes,
    stage_data: ReplayStageData,
    name: str,
    input_masks: Sequence[int],
    source: str,
    metadata: dict[str, object],
) -> None:
    payload = replace_replay_stage_payloads(
        seed_payload,
        {stage_data.stage_index: _stage_payload_from_masks(stage_data, input_masks)},
    )
    sha256 = hashlib.sha256(payload).hexdigest()
    if sha256 in seen:
        return
    seen.add(sha256)
    mutants.append(
        ReplayInputMutant(
            name=name,
            payload=payload,
            source=source,
            sha256=sha256,
            stage=stage_data.stage_index,
            action_count=len(input_masks),
            metadata=metadata,
        )
    )


def generate_replay_input_mutants(
    seed_payload: bytes,
    *,
    stage: int,
    max_frames: int | None = None,
    random_seed: int = 0,
    samples_per_site: int = 4,
) -> list[ReplayInputMutant]:
    stage_data = parse_stage_replay_data(seed_payload)[stage - 1]
    if stage_data is None:
        raise ValueError(f"replay payload has no stage {stage} data")
    input_masks = replay_stage_action_masks(seed_payload, stage, max_frames=max_frames)
    if not input_masks:
        raise ValueError(f"replay stage {stage} action mask stream is empty")

    window_sizes = _candidate_windows(len(input_masks))
    if not window_sizes:
        return []

    rng = random.Random(random_seed)
    starts = _sample_starts(
        len(input_masks),
        minimum_window=window_sizes[0],
        budget=max(4, samples_per_site * 2),
        rng=rng,
    )
    mutants: list[ReplayInputMutant] = []
    seen: set[str] = set()

    for start in starts:
        for window in window_sizes[: min(3, len(window_sizes))]:
            window_rng = _site_rng(random_seed, family="replay-window", start=start, window=window)

            cleared = _replace_window(input_masks, start=start, window=window, transform=lambda _: 0)
            _add_mutant(
                mutants,
                seen,
                seed_payload=seed_payload,
                stage_data=stage_data,
                name=f"mask-clear-t{start}-w{window}",
                input_masks=cleared,
                source="replay-input",
                metadata={
                    "family": "mask-clear",
                    "stage": stage,
                    "site_key": f"t{start:04d}",
                    "start": start,
                    "window": window,
                },
            )

            focus_flipped = _replace_window(
                input_masks,
                start=start,
                window=window,
                transform=lambda mask: mask ^ TH_BUTTON_FOCUS,
            )
            _add_mutant(
                mutants,
                seen,
                seed_payload=seed_payload,
                stage_data=stage_data,
                name=f"focus-flip-t{start}-w{window}",
                input_masks=focus_flipped,
                source="replay-input",
                metadata={
                    "family": "focus-flip",
                    "stage": stage,
                    "site_key": f"t{start:04d}",
                    "start": start,
                    "window": window,
                },
            )

            shoot_flipped = _replace_window(
                input_masks,
                start=start,
                window=window,
                transform=lambda mask: mask ^ TH_BUTTON_SHOOT,
            )
            _add_mutant(
                mutants,
                seen,
                seed_payload=seed_payload,
                stage_data=stage_data,
                name=f"shoot-flip-t{start}-w{window}",
                input_masks=shoot_flipped,
                source="replay-input",
                metadata={
                    "family": "shoot-flip",
                    "stage": stage,
                    "site_key": f"t{start:04d}",
                    "start": start,
                    "window": window,
                },
            )

            direction_name, direction_mask = CARDINAL_DIRECTIONS[window_rng.randrange(len(CARDINAL_DIRECTIONS))]
            direction_burst = _replace_window(
                input_masks,
                start=start,
                window=window,
                transform=lambda mask: (mask & ~TH_BUTTON_DIRECTION) | direction_mask,
            )
            _add_mutant(
                mutants,
                seen,
                seed_payload=seed_payload,
                stage_data=stage_data,
                name=f"direction-burst-{direction_name}-t{start}-w{window}",
                input_masks=direction_burst,
                source="replay-input",
                metadata={
                    "family": "direction-burst",
                    "stage": stage,
                    "site_key": f"t{start:04d}",
                    "start": start,
                    "window": window,
                    "direction": direction_name,
                },
            )

            bomb_window = _replace_window(
                input_masks,
                start=start,
                window=window,
                transform=lambda mask: mask | TH_BUTTON_BOMB,
            )
            _add_mutant(
                mutants,
                seen,
                seed_payload=seed_payload,
                stage_data=stage_data,
                name=f"bomb-window-t{start}-w{window}",
                input_masks=bomb_window,
                source="replay-input",
                metadata={
                    "family": "bomb-window",
                    "stage": stage,
                    "site_key": f"t{start:04d}",
                    "start": start,
                    "window": window,
                },
            )

            skip_window = _replace_window(
                input_masks,
                start=start,
                window=window,
                transform=lambda mask: mask | TH_BUTTON_SKIP,
            )
            _add_mutant(
                mutants,
                seen,
                seed_payload=seed_payload,
                stage_data=stage_data,
                name=f"skip-window-t{start}-w{window}",
                input_masks=skip_window,
                source="replay-input",
                metadata={
                    "family": "skip-window",
                    "stage": stage,
                    "site_key": f"t{start:04d}",
                    "start": start,
                    "window": window,
                },
            )

    pair_budget = max(2, samples_per_site)
    pair_candidates = starts[: max(2, min(len(starts), pair_budget * 2))]
    for index, left_start in enumerate(pair_candidates):
        for right_start in pair_candidates[index + 1:index + 1 + pair_budget]:
            window = window_sizes[index % len(window_sizes)]
            pair_rng = _site_rng(random_seed, family="replay-coordinated", start=left_start ^ right_start, window=window)
            direction_name, direction_mask = CARDINAL_DIRECTIONS[pair_rng.randrange(len(CARDINAL_DIRECTIONS))]
            mutated = _replace_window(
                input_masks,
                start=left_start,
                window=window,
                transform=lambda mask: (mask & ~TH_BUTTON_DIRECTION) | direction_mask,
            )
            mutated = _replace_window(
                mutated,
                start=right_start,
                window=window,
                transform=lambda mask: mask ^ TH_BUTTON_FOCUS ^ TH_BUTTON_SHOOT,
            )
            _add_mutant(
                mutants,
                seen,
                seed_payload=seed_payload,
                stage_data=stage_data,
                name=f"coordinated-{direction_name}-focusshoot-t{left_start}-t{right_start}-w{window}",
                input_masks=mutated,
                source="replay-input",
                metadata={
                    "family": "coordinated-replay-burst",
                    "stage": stage,
                    "site_key": f"t{left_start:04d}__t{right_start:04d}",
                    "sites": [
                        {"tick_start": left_start, "window": window},
                        {"tick_start": right_start, "window": window},
                    ],
                    "left_start": left_start,
                    "right_start": right_start,
                    "window": window,
                    "direction": direction_name,
                },
            )
    return mutants


def select_diverse_replay_input_mutants(
    mutants: Sequence[ReplayInputMutant],
    *,
    limit: int | None,
) -> list[ReplayInputMutant]:
    if limit is None or limit >= len(mutants):
        return list(mutants)
    if limit <= 0:
        return []

    buckets: dict[str, dict[str, list[ReplayInputMutant]]] = {}
    family_order: list[str] = []
    site_order_by_family: dict[str, list[str]] = {}
    next_site_index: dict[str, int] = {}
    for mutant in mutants:
        family = replay_input_mutant_family(mutant)
        site = replay_input_mutant_site(mutant)
        if family not in buckets:
            buckets[family] = {}
            family_order.append(family)
            site_order_by_family[family] = []
            next_site_index[family] = 0
        family_sites = buckets[family]
        if site not in family_sites:
            family_sites[site] = []
            site_order_by_family[family].append(site)
        family_sites[site].append(mutant)

    def pop_next(family: str) -> ReplayInputMutant | None:
        order = site_order_by_family[family]
        if not order:
            return None
        attempts = 0
        index = next_site_index[family]
        while attempts < len(order):
            site = order[index % len(order)]
            index += 1
            attempts += 1
            bucket = buckets[family][site]
            if bucket:
                next_site_index[family] = index % len(order)
                return bucket.pop(0)
        next_site_index[family] = index % len(order)
        return None

    selected: list[ReplayInputMutant] = []
    while len(selected) < limit:
        progressed = False
        for family in family_order:
            mutant = pop_next(family)
            if mutant is None:
                continue
            selected.append(mutant)
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected


def select_diverse_replay_mutants(
    mutants: Sequence[ReplayInputMutant],
    *,
    limit: int | None,
) -> list[ReplayInputMutant]:
    return select_diverse_replay_input_mutants(mutants, limit=limit)
