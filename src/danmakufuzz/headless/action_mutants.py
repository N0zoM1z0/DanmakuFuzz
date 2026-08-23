from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Sequence

from .actions import ActionStream


CARDINAL_ACTIONS = (
    "left",
    "right",
    "up",
    "down",
    "up_left",
    "up_right",
    "down_left",
    "down_right",
)
FAST_ACTIONS = tuple(f"{action}_fast" for action in CARDINAL_ACTIONS)
WEAVE_PATTERNS = (
    ("left", "right"),
    ("up", "down"),
    ("up_left", "down_right"),
    ("up_right", "down_left"),
)
BOX_PATTERN = (
    "up",
    "up_right",
    "right",
    "down_right",
    "down",
    "down_left",
    "left",
    "up_left",
)


@dataclass(frozen=True)
class ActionMutant:
    name: str
    action_text: str
    source: str
    sha256: str
    action_count: int
    metadata: dict[str, object] | None = None


def action_mutant_family(mutant: ActionMutant) -> str:
    metadata = mutant.metadata or {}
    family = metadata.get("family")
    if isinstance(family, str) and family:
        return family
    return mutant.name.split("-", 1)[0]


def action_mutant_site(mutant: ActionMutant) -> str:
    metadata = mutant.metadata or {}
    site_key = metadata.get("site_key")
    if isinstance(site_key, str) and site_key:
        return site_key
    return "raw"


def serialize_actions_text(actions: Sequence[str]) -> str:
    if not actions:
        raise ValueError("action stream must not be empty")
    lines: list[str] = []
    current = actions[0]
    count = 1
    for action in actions[1:]:
        if action == current:
            count += 1
            continue
        lines.append(current if count == 1 else f"{count} {current}")
        current = action
        count = 1
    lines.append(current if count == 1 else f"{count} {current}")
    return "\n".join(lines) + "\n"


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


def _replace_window(actions: Sequence[str], *, start: int, window: int, pattern: Sequence[str]) -> tuple[str, ...]:
    mutated = list(actions)
    for offset in range(window):
        index = start + offset
        if index >= len(mutated):
            break
        mutated[index] = pattern[offset % len(pattern)]
    return tuple(mutated)


def _add_mutant(
    mutants: list[ActionMutant],
    seen: set[str],
    *,
    name: str,
    actions: Sequence[str],
    source: str,
    metadata: dict[str, object],
) -> None:
    action_text = serialize_actions_text(actions)
    sha256 = hashlib.sha256(action_text.encode("utf-8")).hexdigest()
    if sha256 in seen:
        return
    seen.add(sha256)
    mutants.append(
        ActionMutant(
            name=name,
            action_text=action_text,
            source=source,
            sha256=sha256,
            action_count=len(actions),
            metadata=metadata,
        )
    )


def generate_action_mutants(
    seed_stream: ActionStream,
    *,
    random_seed: int = 0,
    samples_per_site: int = 4,
) -> list[ActionMutant]:
    actions = seed_stream.actions
    if not actions:
        raise ValueError("seed action stream must not be empty")

    window_sizes = _candidate_windows(len(actions))
    if not window_sizes:
        return []

    rng = random.Random(random_seed)
    starts = _sample_starts(
        len(actions),
        minimum_window=window_sizes[0],
        budget=max(4, samples_per_site * 2),
        rng=rng,
    )
    mutants: list[ActionMutant] = []
    seen: set[str] = set()

    for start in starts:
        for window in window_sizes[: min(3, len(window_sizes))]:
            if start + 1 > len(actions):
                continue
            window_rng = _site_rng(random_seed, family="window", start=start, window=window)

            direction = CARDINAL_ACTIONS[window_rng.randrange(len(CARDINAL_ACTIONS))]
            direction_actions = _replace_window(actions, start=start, window=window, pattern=(direction,))
            _add_mutant(
                mutants,
                seen,
                name=f"direction-burst-{direction}-t{start}-w{window}",
                actions=direction_actions,
                source="input",
                metadata={
                    "family": "direction-burst",
                    "site_key": f"t{start:04d}",
                    "site_slug": f"t{start:04d}",
                    "start": start,
                    "window": window,
                    "action": direction,
                    "random_seed": random_seed,
                },
            )

            fast_action = FAST_ACTIONS[window_rng.randrange(len(FAST_ACTIONS))]
            fast_actions = _replace_window(actions, start=start, window=window, pattern=(fast_action,))
            _add_mutant(
                mutants,
                seen,
                name=f"fast-burst-{fast_action}-t{start}-w{window}",
                actions=fast_actions,
                source="input",
                metadata={
                    "family": "fast-burst",
                    "site_key": f"t{start:04d}",
                    "site_slug": f"t{start:04d}",
                    "start": start,
                    "window": window,
                    "action": fast_action,
                    "random_seed": random_seed,
                },
            )

            weave_pattern = WEAVE_PATTERNS[window_rng.randrange(len(WEAVE_PATTERNS))]
            weave_actions = _replace_window(actions, start=start, window=window, pattern=weave_pattern)
            _add_mutant(
                mutants,
                seen,
                name=f"weave-burst-{'-'.join(weave_pattern)}-t{start}-w{window}",
                actions=weave_actions,
                source="input",
                metadata={
                    "family": "weave-burst",
                    "site_key": f"t{start:04d}",
                    "site_slug": f"t{start:04d}",
                    "start": start,
                    "window": window,
                    "pattern": list(weave_pattern),
                    "random_seed": random_seed,
                },
            )

            box_actions = _replace_window(actions, start=start, window=window, pattern=BOX_PATTERN)
            _add_mutant(
                mutants,
                seen,
                name=f"box-sweep-t{start}-w{window}",
                actions=box_actions,
                source="input",
                metadata={
                    "family": "box-sweep",
                    "site_key": f"t{start:04d}",
                    "site_slug": f"t{start:04d}",
                    "start": start,
                    "window": window,
                    "pattern": list(BOX_PATTERN),
                    "random_seed": random_seed,
                },
            )

    pair_budget = max(2, samples_per_site)
    pair_candidates = starts[: max(2, min(len(starts), pair_budget * 2))]
    for index, left_start in enumerate(pair_candidates):
        for right_start in pair_candidates[index + 1:index + 1 + pair_budget]:
            window = window_sizes[index % len(window_sizes)]
            pair_rng = _site_rng(random_seed, family="coordinated", start=left_start ^ right_start, window=window)
            left_action = CARDINAL_ACTIONS[pair_rng.randrange(len(CARDINAL_ACTIONS))]
            right_action = FAST_ACTIONS[pair_rng.randrange(len(FAST_ACTIONS))]
            mutated = _replace_window(actions, start=left_start, window=window, pattern=(left_action,))
            mutated = _replace_window(mutated, start=right_start, window=window, pattern=(right_action,))
            _add_mutant(
                mutants,
                seen,
                name=f"coordinated-burst-{left_action}-{right_action}-t{left_start}-t{right_start}-w{window}",
                actions=mutated,
                source="input",
                metadata={
                    "family": "coordinated-burst",
                    "site_key": f"t{left_start:04d}__t{right_start:04d}",
                    "site_slug": f"t{left_start:04d}__t{right_start:04d}",
                    "sites": [
                        {"tick_start": left_start, "window": window},
                        {"tick_start": right_start, "window": window},
                    ],
                    "left_start": left_start,
                    "right_start": right_start,
                    "window": window,
                    "left_action": left_action,
                    "right_action": right_action,
                    "random_seed": random_seed,
                },
            )

    return mutants


def select_diverse_action_mutants(mutants: Sequence[ActionMutant], *, limit: int | None) -> list[ActionMutant]:
    if limit is None or limit >= len(mutants):
        return list(mutants)
    if limit <= 0:
        return []

    buckets: dict[str, dict[str, list[ActionMutant]]] = {}
    family_order: list[str] = []
    site_order_by_family: dict[str, list[str]] = {}
    next_site_index: dict[str, int] = {}
    for mutant in mutants:
        family = action_mutant_family(mutant)
        site = action_mutant_site(mutant)
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

    def pop_next(family: str) -> ActionMutant | None:
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

    selected: list[ActionMutant] = []
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
