from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class SequenceReductionResult(Generic[T]):
    items: tuple[T, ...]
    evaluations: int
    history: tuple[dict[str, object], ...]
    exhausted_budget: bool


@dataclass(frozen=True)
class BisectionResult(Generic[T]):
    index: int | None
    item: T | None
    evaluations: int
    history: tuple[dict[str, object], ...]
    exhausted_budget: bool


def ddmin_sequence(
    items: Sequence[T],
    predicate: Callable[[tuple[T, ...]], bool],
    *,
    min_size: int = 0,
    max_evaluations: int = 128,
) -> SequenceReductionResult[T]:
    """Reduce a sequence by deleting contiguous chunks while predicate holds."""

    if min_size < 0:
        raise ValueError("min_size must be non-negative")
    if max_evaluations < 1:
        raise ValueError("max_evaluations must be positive")

    current = list(items)
    granularity = 2
    evaluations = 0
    history: list[dict[str, object]] = []

    while len(current) > min_size and evaluations < max_evaluations:
        chunk_size = max(1, ceil(len(current) / granularity))
        reduced = False
        for start in range(0, len(current), chunk_size):
            stop = min(len(current), start + chunk_size)
            candidate = current[:start] + current[stop:]
            if len(candidate) < min_size:
                continue
            evaluations += 1
            matched = bool(predicate(tuple(candidate)))
            history.append(
                {
                    "operation": "delete-chunk",
                    "start": start,
                    "stop": stop,
                    "candidate_size": len(candidate),
                    "matched": matched,
                }
            )
            if matched:
                current = candidate
                granularity = max(2, granularity - 1)
                reduced = True
                break
            if evaluations >= max_evaluations:
                break
        if reduced:
            continue
        if granularity >= len(current):
            break
        granularity = min(len(current), granularity * 2)

    return SequenceReductionResult(
        items=tuple(current),
        evaluations=evaluations,
        history=tuple(history),
        exhausted_budget=evaluations >= max_evaluations,
    )


def first_true_index(
    items: Sequence[T],
    predicate: Callable[[T], bool],
    *,
    max_evaluations: int = 64,
) -> BisectionResult[T]:
    """Find the first item matching a monotonic false->true predicate."""

    if max_evaluations < 1:
        raise ValueError("max_evaluations must be positive")
    if not items:
        return BisectionResult(index=None, item=None, evaluations=0, history=(), exhausted_budget=False)

    evaluations = 0
    history: list[dict[str, object]] = []
    low = 0
    high = len(items) - 1
    found: int | None = None

    while low <= high and evaluations < max_evaluations:
        mid = (low + high) // 2
        matched = bool(predicate(items[mid]))
        evaluations += 1
        history.append(
            {
                "operation": "bisect",
                "low": low,
                "high": high,
                "index": mid,
                "matched": matched,
            }
        )
        if matched:
            found = mid
            high = mid - 1
        else:
            low = mid + 1

    item = items[found] if found is not None else None
    return BisectionResult(
        index=found,
        item=item,
        evaluations=evaluations,
        history=tuple(history),
        exhausted_budget=evaluations >= max_evaluations and low <= high,
    )


def first_prefix_divergence(
    left: Sequence[T],
    right: Sequence[T],
    *,
    project: Callable[[T], object] | None = None,
) -> int | None:
    """Return the first index where two aligned temporal streams diverge."""

    projector = project or (lambda value: value)
    limit = min(len(left), len(right))

    def prefix_equal(length: int) -> bool:
        return all(projector(left[index]) == projector(right[index]) for index in range(length))

    if prefix_equal(limit):
        if len(left) == len(right):
            return None
        return limit

    low = 0
    high = limit
    while low < high:
        mid = (low + high) // 2
        if prefix_equal(mid + 1):
            low = mid + 1
        else:
            high = mid
    return low
