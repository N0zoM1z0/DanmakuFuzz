from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from collections.abc import Sequence

from .model import EclFile, EclSubroutine, RawInstruction


OP_JUMP = 2
OP_JUMPDEC = 3
OP_CALL = 35
OP_MOVE_TIME_FIRST = 52
OP_MOVE_TIME_LAST = 60
OP_BULLETFANAIMED = 67
OP_BULLETRANDOM = 75
OP_SHOOTINTERVAL = 76
OP_SHOOTINTERVALDELAYED = 77
OP_LASERROTATE = 88
OP_LASERROTATEFROMPLAYER = 89
OP_LASEROFFSET = 90
OP_LASERTEST = 91
OP_LASERCANCEL = 92
OP_SPELLCARDSTART = 93
OP_ANMSETSLOT = 99
OP_ENEMYINTERRUPTSET = 109
OP_BOSSTIMERSET = 112
OP_LIFECALLBACKTHRESHOLD = 113
OP_TIMERCALLBACKTHRESHOLD = 115
OP_DROPITEMS = 119
OP_EXINSCALL = 121
OP_EXINSREPEAT = 122
OP_TIMESET = 123
OP_DROPITEMID = 124
OP_BOSSSETLIFECOUNT = 126
OP_ANMINTERRUPTSLOT = 129


@dataclass(frozen=True)
class DeferredMutation:
    base_ecl: EclFile
    sub_index: int
    instruction_index: int
    instruction: RawInstruction


@dataclass(frozen=True)
class Mutant:
    name: str
    path: tuple[int, int]
    ecl: EclFile | DeferredMutation
    metadata: dict[str, int | str] | None = None


def _replace_i16(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    mutable[offset:offset + 2] = int(value).to_bytes(2, "little", signed=True)
    return bytes(mutable)


def _replace_i32(buffer: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(buffer)
    mutable[offset:offset + 4] = int(value).to_bytes(4, "little", signed=True)
    return bytes(mutable)


def _replace_string(buffer: bytes, offset: int, data: bytes) -> bytes:
    mutable = bytearray(buffer)
    mutable[offset:offset + len(data)] = data
    return bytes(mutable)


def _clone_with_mutated_instruction(
    ecl: EclFile,
    sub_index: int,
    instruction_index: int,
    instruction: RawInstruction,
) -> DeferredMutation:
    return DeferredMutation(
        base_ecl=ecl,
        sub_index=sub_index,
        instruction_index=instruction_index,
        instruction=instruction,
    )


def materialize_mutant_ecl(mutant: Mutant) -> EclFile:
    if isinstance(mutant.ecl, EclFile):
        return mutant.ecl
    deferred = mutant.ecl
    return _materialized_clone_with_mutated_instruction(
        deferred.base_ecl,
        deferred.sub_index,
        deferred.instruction_index,
        deferred.instruction,
    )


def _materialized_clone_with_mutated_instruction(
    ecl: EclFile,
    sub_index: int,
    instruction_index: int,
    instruction: RawInstruction,
) -> EclFile:
    subs = list(ecl.subs)
    selected_sub = subs[sub_index]
    instructions = list(selected_sub.instructions)
    instructions[instruction_index] = instruction
    subs[sub_index] = EclSubroutine(file_offset=selected_sub.file_offset, instructions=instructions)
    return EclFile(
        sub_count=ecl.sub_count,
        main_count=ecl.main_count,
        timeline_offsets=ecl.timeline_offsets,
        timeline=ecl.timeline,
        subs=subs,
    )


def generate_targeted_mutants(ecl: EclFile) -> list[Mutant]:
    mutants: list[Mutant] = []
    sub_count = len(ecl.subs)
    for sub_index, subroutine in enumerate(ecl.subs):
        for instruction_index, instruction in enumerate(subroutine.instructions):
            key = (sub_index, instruction_index)
            if instruction.opcode in {OP_JUMP, OP_JUMPDEC} and len(instruction.args) >= 8:
                mutants.append(Mutant("jump-offset-zero", key, _clone_with_mutated_instruction(
                    ecl, sub_index, instruction_index,
                    RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 4, 0)})
                )))
                mutants.append(Mutant("jump-offset-negative-12", key, _clone_with_mutated_instruction(
                    ecl, sub_index, instruction_index,
                    RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 4, -12)})
                )))
                mutants.append(Mutant("jump-offset-large-forward", key, _clone_with_mutated_instruction(
                    ecl, sub_index, instruction_index,
                    RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 4, 0x7FFF)})
                )))
            if instruction.opcode == OP_CALL and len(instruction.args) >= 4:
                for name, value in (
                    ("call-sub-negative-one", -1),
                    ("call-sub-past-end", sub_count),
                    ("call-sub-max-i32", 0x7FFFFFFF),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if OP_MOVE_TIME_FIRST <= instruction.opcode <= OP_MOVE_TIME_LAST and len(instruction.args) >= 4:
                for name, value in (
                    ("move-time-zero", 0),
                    ("move-time-negative-one", -1),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_ANMSETSLOT and len(instruction.args) >= 4:
                for name, value in (("anm-slot-8", 8), ("anm-slot-255", 255)):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode in {OP_SHOOTINTERVAL, OP_SHOOTINTERVALDELAYED} and len(instruction.args) >= 4:
                for name, value in (
                    ("shoot-interval-zero", 0),
                    ("shoot-interval-one", 1),
                    ("shoot-interval-negative-one", -1),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode in {OP_LASERROTATE, OP_LASERROTATEFROMPLAYER, OP_LASEROFFSET, OP_LASERTEST, OP_LASERCANCEL} and len(instruction.args) >= 4:
                for name, value in (("laser-index-32", 32), ("laser-index-255", 255)):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_ENEMYINTERRUPTSET and len(instruction.args) >= 8:
                for name, value in (("interrupt-id-8", 8), ("interrupt-id-255", 255)):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 4, value)})
                    )))
            if instruction.opcode == OP_BOSSTIMERSET and len(instruction.args) >= 4:
                for name, value in (
                    ("boss-timer-zero", 0),
                    ("boss-timer-one", 1),
                    ("boss-timer-large", 0x7FFF),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_LIFECALLBACKTHRESHOLD and len(instruction.args) >= 4:
                for name, value in (
                    ("life-callback-threshold-zero", 0),
                    ("life-callback-threshold-negative-one", -1),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_TIMERCALLBACKTHRESHOLD and len(instruction.args) >= 4:
                for name, value in (
                    ("timer-callback-threshold-zero", 0),
                    ("timer-callback-threshold-one", 1),
                    ("timer-callback-threshold-large", 0x7FFF),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_EXINSCALL and len(instruction.args) >= 4:
                for name, value in (("exinscall-17", 17), ("exinscall-255", 255)):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_EXINSREPEAT and len(instruction.args) >= 4:
                for name, value in (("exinsrepeat-negative-one", -1), ("exinsrepeat-17", 17)):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_SPELLCARDSTART and len(instruction.args) >= 4:
                mutants.append(Mutant("spellcard-id-64", key, _clone_with_mutated_instruction(
                    ecl, sub_index, instruction_index,
                    RawInstruction(**{**instruction.__dict__, "args": _replace_i16(instruction.args, 2, 64)})
                )))
                long_name = b"A" * 80
                new_args = _replace_string(instruction.args, 4, long_name)
                mutants.append(Mutant("spellcard-name-80-bytes", key, _clone_with_mutated_instruction(
                    ecl, sub_index, instruction_index,
                    RawInstruction(**{**instruction.__dict__, "offset_to_next": 12 + len(new_args), "args": new_args})
                )))
            if OP_BULLETFANAIMED <= instruction.opcode <= OP_BULLETRANDOM and len(instruction.args) >= 12:
                for name, offset, value in (
                    ("bullet-count1-zero", 4, 0),
                    ("bullet-count2-zero", 8, 0),
                    ("bullet-count1-negative-one", 4, -1),
                    ("bullet-sprite-16", 0, 16),
                ):
                    mutate = _replace_i32 if offset in {4, 8} else _replace_i16
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": mutate(instruction.args, offset, value)})
                    )))
            if instruction.opcode == OP_DROPITEMS and len(instruction.args) >= 4:
                for name, value in (
                    ("drop-items-zero", 0),
                    ("drop-items-one", 1),
                    ("drop-items-32", 32),
                    ("drop-items-negative-one", -1),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_DROPITEMID and len(instruction.args) >= 4:
                for name, value in (
                    ("drop-item-id-full-power", 4),
                    ("drop-item-id-life", 5),
                    ("drop-item-id-point-bullet", 6),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_ANMINTERRUPTSLOT and len(instruction.args) >= 4:
                mutants.append(Mutant("anm-interrupt-slot-255", key, _clone_with_mutated_instruction(
                    ecl, sub_index, instruction_index,
                    RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, 255)})
                )))
            if instruction.opcode == OP_TIMESET and len(instruction.args) >= 4:
                for name, value in (
                    ("time-set-zero", 0),
                    ("time-set-negative-one", -1),
                    ("time-set-large-forward", 0x7FFF),
                ):
                    mutants.append(Mutant(name, key, _clone_with_mutated_instruction(
                        ecl, sub_index, instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, value)})
                    )))
            if instruction.opcode == OP_BOSSSETLIFECOUNT and len(instruction.args) >= 4:
                mutants.append(Mutant("boss-life-count-negative-one", key, _clone_with_mutated_instruction(
                    ecl, sub_index, instruction_index,
                    RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, 0, -1)})
                )))
    deduped: list[Mutant] = []
    seen: set[tuple[str, tuple[int, int]]] = set()
    for mutant in mutants:
        dedupe_key = (mutant.name, mutant.path)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(mutant)
    return deduped


def _read_i16(buffer: bytes, offset: int) -> int:
    return int.from_bytes(buffer[offset:offset + 2], "little", signed=True)


def _read_i32(buffer: bytes, offset: int) -> int:
    return int.from_bytes(buffer[offset:offset + 4], "little", signed=True)


def _value_slug(value: int) -> str:
    if value < 0:
        return f"neg{-value}"
    return str(value)


def _site_rng(
    random_seed: int,
    *,
    opcode: int,
    sub_index: int,
    instruction_index: int,
    family: str,
) -> random.Random:
    material = f"{random_seed}:{opcode}:{sub_index}:{instruction_index}:{family}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest[:8], "little", signed=False))


def _mutant_family_key(mutant: Mutant) -> str:
    metadata = mutant.metadata or {}
    family = metadata.get("family")
    if isinstance(family, str) and family:
        return family
    parts = [part for part in mutant.name.split("-") if part]
    if len(parts) >= 2:
        return "-".join(parts[:2])
    return mutant.name


def _normalize_family_filters(family_filters: Sequence[str] | None) -> tuple[str, ...]:
    if not family_filters:
        return ()
    normalized: list[str] = []
    for family_filter in family_filters:
        token = family_filter.strip().rstrip("-")
        if token:
            normalized.append(token)
    return tuple(dict.fromkeys(normalized))


def _family_requested(family: str, family_filters: Sequence[str] | None) -> bool:
    normalized_filters = _normalize_family_filters(family_filters)
    if not normalized_filters:
        return True
    return any(
        family == token
        or family.startswith(f"{token}-")
        or token.startswith(f"{family}-")
        for token in normalized_filters
    )


def _reorder_site_mutants(
    mutants: list[Mutant],
    *,
    random_seed: int,
    opcode: int,
    sub_index: int,
    instruction_index: int,
    family_order_hint: Sequence[str] | None = None,
) -> list[Mutant]:
    if len(mutants) <= 1:
        return mutants

    rng = _site_rng(
        random_seed,
        opcode=opcode,
        sub_index=sub_index,
        instruction_index=instruction_index,
        family="site-order",
    )
    family_buckets: dict[str, list[Mutant]] = {}
    family_order: list[str] = []
    for mutant in mutants:
        family_key = _mutant_family_key(mutant)
        if family_key not in family_buckets:
            family_buckets[family_key] = []
        family_buckets[family_key].append(mutant)

    if family_order_hint:
        seen_families: set[str] = set()
        for family_key in family_order_hint:
            if family_key in seen_families:
                continue
            seen_families.add(family_key)
            family_order.append(family_key)
        for family_key in family_buckets:
            if family_key not in seen_families:
                family_order.append(family_key)
    else:
        family_order = list(family_buckets)

    rng.shuffle(family_order)
    for family_key in family_order:
        bucket = family_buckets.get(family_key)
        if bucket is None:
            continue
        rng.shuffle(bucket)

    reordered: list[Mutant] = []
    while True:
        progressed = False
        for family_key in family_order:
            bucket = family_buckets.get(family_key)
            if bucket is None:
                continue
            if not bucket:
                continue
            reordered.append(bucket.pop())
            progressed = True
        if not progressed:
            break
    return reordered


def _dedupe_ints(values: list[int], *, minimum: int, maximum: int, current: int) -> list[int]:
    seen: set[int] = set()
    deduped: list[int] = []
    for value in values:
        if value == current:
            continue
        if value < minimum or value > maximum:
            continue
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _shuffle_filtered_values(
    values: list[int],
    *,
    current: int,
    minimum: int,
    maximum: int,
    rng: random.Random,
) -> list[int]:
    candidates = _dedupe_ints(values, minimum=minimum, maximum=maximum, current=current)
    rng.shuffle(candidates)
    return candidates


def _sample_value_groups(
    groups: list[list[int]],
    *,
    current: int,
    minimum: int,
    maximum: int,
    budget: int,
    rng: random.Random,
) -> list[int]:
    if budget <= 0:
        return []

    pending = [
        _shuffle_filtered_values(
            group,
            current=current,
            minimum=minimum,
            maximum=maximum,
            rng=rng,
        )
        for group in groups
    ]
    selected: list[int] = []
    seen: set[int] = set()
    while len(selected) < budget:
        group_indices = [index for index, group in enumerate(pending) if group]
        if not group_indices:
            break
        rng.shuffle(group_indices)
        progressed = False
        for group_index in group_indices:
            group = pending[group_index]
            while group and group[-1] in seen:
                group.pop()
            if not group:
                continue
            value = group.pop()
            if value in seen:
                continue
            selected.append(value)
            seen.add(value)
            progressed = True
            if len(selected) >= budget:
                break
        if not progressed:
            break
    return selected


def _dedupe_pairs(
    values: list[tuple[int, int]],
    *,
    minimum: int,
    maximum: int,
    current: tuple[int, int],
) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    deduped: list[tuple[int, int]] = []
    for left, right in values:
        pair = (int(left), int(right))
        if pair == current:
            continue
        if left < minimum or left > maximum or right < minimum or right > maximum:
            continue
        if pair in seen:
            continue
        seen.add(pair)
        deduped.append(pair)
    return deduped


def _shuffle_filtered_pairs(
    values: list[tuple[int, int]],
    *,
    current: tuple[int, int],
    minimum: int,
    maximum: int,
    rng: random.Random,
) -> list[tuple[int, int]]:
    candidates = _dedupe_pairs(values, minimum=minimum, maximum=maximum, current=current)
    rng.shuffle(candidates)
    return candidates


def _sample_pair_groups(
    groups: list[list[tuple[int, int]]],
    *,
    current: tuple[int, int],
    minimum: int,
    maximum: int,
    budget: int,
    rng: random.Random,
) -> list[tuple[int, int]]:
    if budget <= 0:
        return []

    pending = [
        _shuffle_filtered_pairs(
            group,
            current=current,
            minimum=minimum,
            maximum=maximum,
            rng=rng,
        )
        for group in groups
    ]
    selected: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    while len(selected) < budget:
        group_indices = [index for index, group in enumerate(pending) if group]
        if not group_indices:
            break
        rng.shuffle(group_indices)
        progressed = False
        for group_index in group_indices:
            group = pending[group_index]
            while group and group[-1] in seen:
                group.pop()
            if not group:
                continue
            pair = group.pop()
            if pair in seen:
                continue
            selected.append(pair)
            seen.add(pair)
            progressed = True
            if len(selected) >= budget:
                break
        if not progressed:
            break
    return selected


def _relative_values(current: int, deltas: tuple[int, ...]) -> list[int]:
    values = [current + delta for delta in deltas]
    values.append(-current)
    return values


def _scaled_values(current: int, *, multipliers: tuple[int, ...], divisors: tuple[int, ...]) -> list[int]:
    values = [current * factor for factor in multipliers]
    for divisor in divisors:
        if divisor == 0:
            continue
        values.append(int(current / divisor))
    return values


def _bitflip_values(current: int, *, bits: tuple[int, ...]) -> list[int]:
    return [current ^ (1 << bit) for bit in bits]


def _power_of_two_neighbors(*, bits: tuple[int, ...], signed: bool) -> list[int]:
    values: list[int] = []
    for bit in bits:
        if bit < 0:
            continue
        base = 1 << bit
        values.extend([base - 1, base, base + 1])
        if signed:
            values.extend([-(base + 1), -base, -(base - 1)])
    return values


def _magnitude_neighbor_values(current: int, *, signed: bool) -> list[int]:
    absolute = abs(current)
    if absolute == 0:
        return []
    low_bit = max(0, absolute.bit_length() - 1)
    high_bit = absolute.bit_length()
    values = _power_of_two_neighbors(bits=(low_bit, high_bit), signed=False)
    if signed:
        signed_values: list[int] = []
        for value in values:
            signed_values.extend([value, -value])
        return signed_values
    return values


def _random_signed_bits(rng: random.Random, bit_width: int) -> int:
    value = rng.getrandbits(bit_width)
    return -value if rng.getrandbits(1) else value


def _sample_u8(
    *,
    current: int,
    budget: int,
    rng: random.Random,
    family: str,
) -> list[int]:
    base = {
        "bitmask": [
            0,
            1,
            2,
            3,
            4,
            7,
            8,
            15,
            16,
            31,
            32,
            63,
            64,
            127,
            128,
            255,
        ],
    }[family]
    relative_values = _relative_values(current, (-64, -32, -16, -8, -4, -2, -1, 1, 2, 4, 8, 16, 32, 64))
    bitflip_values = _bitflip_values(current, bits=(0, 1, 2, 3, 4, 5, 6, 7))
    random_local_values = [
        current + rng.randint(-span, span)
        for span in (3, 7, 15, 31, 63, 127)
    ]
    power_values = _power_of_two_neighbors(bits=(0, 1, 2, 3, 4, 5, 6, 7), signed=False)
    random_values = [rng.randint(0, 255) for _ in range(max(8, budget * 4))]
    return _sample_value_groups(
        [
            list(base),
            relative_values,
            bitflip_values,
            random_local_values,
            power_values,
            random_values,
        ],
        current=current,
        minimum=0,
        maximum=255,
        budget=budget,
        rng=rng,
    )


def _sample_signed_i32(
    *,
    current: int,
    budget: int,
    rng: random.Random,
    family: str,
    context_limit: int | None = None,
) -> list[int]:
    base = {
        "offset": [
            -0x7FFF,
            -4096,
            -2048,
            -1024,
            -512,
            -256,
            -128,
            -64,
            -32,
            -16,
            -12,
            -8,
            -4,
            -2,
            -1,
            0,
            1,
            2,
            4,
            8,
            12,
            16,
            32,
            64,
            128,
            256,
            512,
            1024,
            2048,
            4096,
            0x7FFF,
            0x7FFFFFFF,
        ],
        "index": [
            -1,
            0,
            1,
            2,
            3,
            4,
            7,
            8,
            15,
            16,
            31,
            32,
            63,
            64,
            127,
            128,
            255,
            256,
            511,
            512,
            1024,
            0x7FFF,
            0x7FFFFFFF,
        ],
        "time": [
            -1,
            0,
            1,
            2,
            3,
            4,
            7,
            8,
            12,
            16,
            24,
            32,
            48,
            64,
            96,
            127,
            128,
            255,
            256,
            512,
            1024,
            2048,
            4096,
            0x7FFF,
        ],
        "count": [
            -1,
            0,
            1,
            2,
            3,
            4,
            5,
            7,
            8,
            12,
            16,
            24,
            32,
            48,
            64,
            96,
            127,
            128,
            255,
            256,
            511,
            512,
            1024,
        ],
        "small-positive": [
            0,
            1,
            2,
            3,
            4,
            5,
            7,
            8,
            12,
            16,
            31,
            32,
            63,
            64,
            127,
            128,
            255,
        ],
        "generic": [
            -0x8000,
            -4096,
            -2048,
            -1024,
            -512,
            -256,
            -128,
            -64,
            -32,
            -16,
            -8,
            -4,
            -2,
            -1,
            0,
            1,
            2,
            4,
            8,
            16,
            32,
            64,
            127,
            128,
            255,
            256,
            511,
            512,
            1024,
            2048,
            4096,
            0x7FFF,
            0x10000,
            0x7FFFFFFF,
        ],
    }[family]
    anchor_values = list(base)
    if context_limit is not None:
        anchor_values.extend([context_limit - 2, context_limit - 1, context_limit, context_limit + 1, context_limit + 2])
    relative_values = _relative_values(
        current,
        (-4096, -2048, -1024, -256, -64, -16, -4, -1, 1, 4, 16, 64, 256, 1024, 2048, 4096),
    )
    scaled_values = _scaled_values(
        current,
        multipliers=(-8, -4, -2, 2, 4, 8),
        divisors=(2, 4, 8),
    )
    available_bits = (0, 1, 2, 3, 4, 5, 7, 8, 11, 15, 16, 23, 30)
    selected_bits = tuple(rng.sample(available_bits, k=min(8, len(available_bits))))
    bitflip_values = _bitflip_values(current, bits=selected_bits)
    power_values = _power_of_two_neighbors(bits=selected_bits, signed=True)
    magnitude_values = _magnitude_neighbor_values(current, signed=True)
    random_local_values = [
        current + rng.randint(-span, span)
        for span in (3, 7, 15, 31, 63, 127, 255, 1023, 4095, 16383)
    ]
    random_stride_values = [
        current + (rng.choice((-1, 1)) * rng.randint(1, 4096) * rng.choice((1, 2, 4, 8, 16, 32)))
        for _ in range(max(6, budget * 2))
    ]
    random_extreme_values = [
        rng.randint(-32, 32),
        rng.randint(-512, 512),
        _random_signed_bits(rng, 8),
        _random_signed_bits(rng, 12),
        _random_signed_bits(rng, 16),
        _random_signed_bits(rng, 24),
        _random_signed_bits(rng, 31),
        ((1 << 31) - 1) - rng.randint(0, 255),
        -(1 << 31) + rng.randint(0, 255),
    ]
    mirrored_values = [current, -current, current - 1, current + 1, -current - 1, -current + 1]
    context_values: list[int] = []
    if context_limit is not None and context_limit >= 0:
        upper = max(context_limit + 4, 4)
        context_values.extend(rng.randint(-2, upper) for _ in range(8))
        context_values.extend([
            context_limit // 2,
            context_limit * 2,
            current + context_limit,
            current - context_limit,
            context_limit + 1,
            context_limit - 1,
            -(context_limit + 1),
        ])
    return _sample_value_groups(
        [
            anchor_values,
            context_values,
            relative_values,
            scaled_values,
            bitflip_values,
            power_values,
            magnitude_values,
            mirrored_values,
            random_local_values,
            random_stride_values,
            random_extreme_values,
        ],
        current=current,
        minimum=-(1 << 31),
        maximum=(1 << 31) - 1,
        budget=budget,
        rng=rng,
    )


def _sample_signed_i16(
    *,
    current: int,
    budget: int,
    rng: random.Random,
    family: str,
) -> list[int]:
    base = {
        "small-positive": [
            0,
            1,
            2,
            3,
            4,
            5,
            7,
            8,
            12,
            16,
            31,
            32,
            63,
            64,
            127,
            128,
            255,
            511,
            1023,
        ],
        "generic": [
            -0x4000,
            -2048,
            -1024,
            -512,
            -256,
            -128,
            -64,
            -32,
            -16,
            -8,
            -4,
            -2,
            -1,
            0,
            1,
            2,
            4,
            8,
            16,
            32,
            64,
            127,
            128,
            255,
            511,
            1023,
            0x7FFF,
        ],
    }[family]
    relative_values = _relative_values(current, (-256, -128, -64, -16, -4, -1, 1, 4, 16, 64, 128, 256))
    scaled_values = _scaled_values(
        current,
        multipliers=(-8, -4, -2, 2, 4, 8),
        divisors=(2, 4, 8),
    )
    available_bits = (0, 1, 2, 3, 4, 5, 7, 8, 11, 14)
    selected_bits = tuple(rng.sample(available_bits, k=min(6, len(available_bits))))
    bitflip_values = _bitflip_values(current, bits=selected_bits)
    power_values = _power_of_two_neighbors(bits=selected_bits, signed=True)
    magnitude_values = _magnitude_neighbor_values(current, signed=True)
    random_local_values = [
        current + rng.randint(-span, span)
        for span in (3, 7, 15, 31, 63, 127, 255, 511)
    ]
    random_stride_values = [
        current + (rng.choice((-1, 1)) * rng.randint(1, 128) * rng.choice((1, 2, 4, 8, 16)))
        for _ in range(max(4, budget * 2))
    ]
    random_extreme_values = [
        rng.randint(-32, 32),
        rng.randint(-512, 512),
        _random_signed_bits(rng, 8),
        _random_signed_bits(rng, 12),
        _random_signed_bits(rng, 15),
        ((1 << 15) - 1) - rng.randint(0, 63),
        -(1 << 15) + rng.randint(0, 63),
    ]
    mirrored_values = [current, -current, current - 1, current + 1, -current - 1, -current + 1]
    return _sample_value_groups(
        [
            list(base),
            relative_values,
            scaled_values,
            bitflip_values,
            power_values,
            magnitude_values,
            mirrored_values,
            random_local_values,
            random_stride_values,
            random_extreme_values,
        ],
        current=current,
        minimum=-(1 << 15),
        maximum=(1 << 15) - 1,
        budget=budget,
        rng=rng,
    )


def _sample_paired_signed_i32(
    *,
    current_left: int,
    current_right: int,
    budget: int,
    rng: random.Random,
    field_left: str,
    field_right: str,
) -> list[tuple[int, int]]:
    if budget <= 0:
        return []

    left_rng = random.Random(rng.getrandbits(64))
    right_rng = random.Random(rng.getrandbits(64))
    left_values = _sample_signed_i32(
        current=current_left,
        budget=max(8, budget * 2),
        rng=left_rng,
        family=field_left,
    )
    right_values = _sample_signed_i32(
        current=current_right,
        budget=max(8, budget * 2),
        rng=right_rng,
        family=field_right,
    )
    anchor_pairs = [
        (-1, -1),
        (0, 0),
        (1, 1),
        (2, 2),
        (4, 4),
        (8, 8),
        (16, 16),
        (32, 32),
        (64, 64),
        (127, 127),
        (128, 128),
        (255, 255),
        (256, 256),
        (511, 511),
        (1024, 1024),
        (0, 1),
        (1, 0),
        (1, 2),
        (2, 1),
        (1, 4),
        (4, 1),
        (8, 1),
        (1, 8),
        (16, 1),
        (1, 16),
        (0, -1),
        (-1, 0),
    ]
    relative_pairs = [
        (current_left + delta, current_right + delta)
        for delta in (-256, -64, -16, -4, -1, 1, 4, 16, 64, 256)
    ]
    scaled_pairs = [
        (current_left * factor, current_right * factor)
        for factor in (-4, -2, 2, 4, 8)
    ]
    diagonal_pairs = list(zip(left_values, right_values, strict=False))
    crossed_pairs = [
        (left_values[index], right_values[-(index + 1)])
        for index in range(min(len(left_values), len(right_values)))
    ]
    mixed_pairs = [
        (
            left_values[left_rng.randrange(len(left_values))],
            right_values[right_rng.randrange(len(right_values))],
        )
        for _ in range(max(8, budget * 4))
    ]
    one_sided_pairs = (
        [(value, current_right) for value in left_values[: max(4, budget * 2)]]
        + [(current_left, value) for value in right_values[: max(4, budget * 2)]]
    )
    biased_pairs = []
    for value in list(dict.fromkeys(left_values + right_values))[: max(6, budget * 2)]:
        biased_pairs.extend([
            (0, value),
            (value, 0),
            (1, value),
            (value, 1),
            (-1, value),
            (value, -1),
            (value, -value),
            (-value, value),
        ])
    same_value_pairs = [
        (value, value)
        for value in list(dict.fromkeys(left_values + right_values))
    ]
    swapped_pair = [(current_right, current_left)] if current_left != current_right else []
    return _sample_pair_groups(
        [
            anchor_pairs,
            relative_pairs,
            scaled_pairs,
            diagonal_pairs,
            crossed_pairs,
            mixed_pairs,
            one_sided_pairs,
            biased_pairs,
            same_value_pairs,
            swapped_pair,
        ],
        current=(current_left, current_right),
        minimum=-(1 << 31),
        maximum=(1 << 31) - 1,
        budget=budget,
        rng=rng,
    )


def _select_generic_i32_slots(
    *,
    slot_count: int,
    rng: random.Random,
) -> list[int]:
    if slot_count <= 0:
        return []
    if slot_count <= 2:
        return list(range(slot_count))
    anchor_pool = sorted({0, 1, slot_count - 2, slot_count - 1})
    first = anchor_pool[rng.randrange(len(anchor_pool))]
    remaining = [index for index in range(slot_count) if index != first]
    second = remaining[rng.randrange(len(remaining))]
    return [first, second]


def _sample_site_mutants(
    ecl: EclFile,
    *,
    sub_index: int,
    instruction_index: int,
    instruction: RawInstruction,
    random_seed: int,
    samples_per_site: int,
    family_filters: Sequence[str] | None = None,
) -> list[Mutant]:
    key = (sub_index, instruction_index)
    mutants: list[Mutant] = []
    site_family_order: list[str] = []

    def note_family(family: str) -> None:
        site_family_order.append(family)

    def append_i32_samples(
        family: str,
        *,
        arg_offset: int,
        field: str,
        context_limit: int | None = None,
        metadata_family: str | None = None,
    ) -> None:
        current = _read_i32(instruction.args, arg_offset)
        rng = _site_rng(
            random_seed,
            opcode=instruction.opcode,
            sub_index=sub_index,
            instruction_index=instruction_index,
            family=family,
        )
        for value in _sample_signed_i32(
            current=current,
            budget=samples_per_site,
            rng=rng,
            family=field,
            context_limit=context_limit,
        ):
            mutants.append(
                Mutant(
                    f"{family}-sampled-{_value_slug(value)}",
                    key,
                    _clone_with_mutated_instruction(
                        ecl,
                        sub_index,
                        instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i32(instruction.args, arg_offset, value)}),
                    ),
                    metadata={
                        "strategy": "sampled-i32",
                        "family": metadata_family or family,
                        "field": field,
                        "arg_offset": arg_offset,
                        "value": value,
                        "random_seed": random_seed,
                    },
                )
            )

    def append_i16_samples(
        family: str,
        *,
        arg_offset: int,
        field: str,
        metadata_family: str | None = None,
    ) -> None:
        current = _read_i16(instruction.args, arg_offset)
        rng = _site_rng(
            random_seed,
            opcode=instruction.opcode,
            sub_index=sub_index,
            instruction_index=instruction_index,
            family=family,
        )
        for value in _sample_signed_i16(
            current=current,
            budget=samples_per_site,
            rng=rng,
            family=field,
        ):
            mutants.append(
                Mutant(
                    f"{family}-sampled-{_value_slug(value)}",
                    key,
                    _clone_with_mutated_instruction(
                        ecl,
                        sub_index,
                        instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": _replace_i16(instruction.args, arg_offset, value)}),
                    ),
                    metadata={
                        "strategy": "sampled-i16",
                        "family": metadata_family or family,
                        "field": field,
                        "arg_offset": arg_offset,
                        "value": value,
                        "random_seed": random_seed,
                    },
                )
            )

    def append_instruction_i32_samples(
        family: str,
        *,
        field_name: str,
        field: str,
    ) -> None:
        current = int(getattr(instruction, field_name))
        rng = _site_rng(
            random_seed,
            opcode=instruction.opcode,
            sub_index=sub_index,
            instruction_index=instruction_index,
            family=family,
        )
        for value in _sample_signed_i32(
            current=current,
            budget=samples_per_site,
            rng=rng,
            family=field,
        ):
            mutants.append(
                Mutant(
                    f"{family}-sampled-{_value_slug(value)}",
                    key,
                    _clone_with_mutated_instruction(
                        ecl,
                        sub_index,
                        instruction_index,
                        RawInstruction(**{**instruction.__dict__, field_name: value}),
                    ),
                    metadata={
                        "strategy": "sampled-instruction-i32",
                        "family": family,
                        "field_name": field_name,
                        "field": field,
                        "value": value,
                        "random_seed": random_seed,
                    },
                )
            )

    def append_instruction_u8_samples(
        family: str,
        *,
        field_name: str,
        field: str,
    ) -> None:
        current = int(getattr(instruction, field_name)) & 0xFF
        rng = _site_rng(
            random_seed,
            opcode=instruction.opcode,
            sub_index=sub_index,
            instruction_index=instruction_index,
            family=family,
        )
        for value in _sample_u8(
            current=current,
            budget=samples_per_site,
            rng=rng,
            family=field,
        ):
            mutants.append(
                Mutant(
                    f"{family}-sampled-{_value_slug(value)}",
                    key,
                    _clone_with_mutated_instruction(
                        ecl,
                        sub_index,
                        instruction_index,
                        RawInstruction(**{**instruction.__dict__, field_name: value}),
                    ),
                    metadata={
                        "strategy": "sampled-instruction-u8",
                        "family": family,
                        "field_name": field_name,
                        "field": field,
                        "value": value,
                        "random_seed": random_seed,
                    },
                )
            )

    def append_instruction_time_i32_pair_samples(
        family: str,
        *,
        arg_offset: int,
        field_right: str,
    ) -> None:
        current_left = int(instruction.time)
        current_right = _read_i32(instruction.args, arg_offset)
        rng = _site_rng(
            random_seed,
            opcode=instruction.opcode,
            sub_index=sub_index,
            instruction_index=instruction_index,
            family=family,
        )
        for left_value, right_value in _sample_paired_signed_i32(
            current_left=current_left,
            current_right=current_right,
            budget=max(2, samples_per_site),
            rng=rng,
            field_left="time",
            field_right=field_right,
        ):
            mutated_args = _replace_i32(instruction.args, arg_offset, right_value)
            mutants.append(
                Mutant(
                    f"{family}-sampled-{_value_slug(left_value)}-{_value_slug(right_value)}",
                    key,
                    _clone_with_mutated_instruction(
                        ecl,
                        sub_index,
                        instruction_index,
                        RawInstruction(**{**instruction.__dict__, "time": left_value, "args": mutated_args}),
                    ),
                    metadata={
                        "strategy": "sampled-instruction-time-i32-pair",
                        "family": family,
                        "field_left": "time",
                        "field_right": field_right,
                        "field_name_left": "time",
                        "right_offset": arg_offset,
                        "left_value": left_value,
                        "right_value": right_value,
                        "random_seed": random_seed,
                    },
                )
            )

    def append_i32_pair_samples(
        family: str,
        *,
        left_offset: int,
        right_offset: int,
        field_left: str,
        field_right: str,
    ) -> None:
        current_left = _read_i32(instruction.args, left_offset)
        current_right = _read_i32(instruction.args, right_offset)
        rng = _site_rng(
            random_seed,
            opcode=instruction.opcode,
            sub_index=sub_index,
            instruction_index=instruction_index,
            family=family,
        )
        for left_value, right_value in _sample_paired_signed_i32(
            current_left=current_left,
            current_right=current_right,
            budget=max(2, samples_per_site),
            rng=rng,
            field_left=field_left,
            field_right=field_right,
        ):
            mutated_args = _replace_i32(instruction.args, left_offset, left_value)
            mutated_args = _replace_i32(mutated_args, right_offset, right_value)
            mutants.append(
                Mutant(
                    f"{family}-sampled-{_value_slug(left_value)}-{_value_slug(right_value)}",
                    key,
                    _clone_with_mutated_instruction(
                        ecl,
                        sub_index,
                        instruction_index,
                        RawInstruction(**{**instruction.__dict__, "args": mutated_args}),
                    ),
                    metadata={
                        "strategy": "sampled-i32-pair",
                        "family": family,
                        "field_left": field_left,
                        "field_right": field_right,
                        "left_offset": left_offset,
                        "right_offset": right_offset,
                        "left_value": left_value,
                        "right_value": right_value,
                        "random_seed": random_seed,
                    },
                )
            )

    note_family("instruction-time")
    if _family_requested("instruction-time", family_filters):
        append_instruction_i32_samples("instruction-time", field_name="time", field="time")
    note_family("difficulty-mask")
    if _family_requested("difficulty-mask", family_filters):
        append_instruction_u8_samples("difficulty-mask", field_name="skip_for_difficulty", field="bitmask")
    if len(instruction.args) >= 4:
        note_family("generic-arg32")
        if _family_requested("generic-arg32", family_filters):
            slot_rng = _site_rng(
                random_seed,
                opcode=instruction.opcode,
                sub_index=sub_index,
                instruction_index=instruction_index,
                family="generic-arg32-slots",
            )
            slot_indices = _select_generic_i32_slots(
                slot_count=len(instruction.args) // 4,
                rng=slot_rng,
            )
            for slot_index in slot_indices:
                append_i32_samples(
                    f"generic-arg32-o{slot_index}",
                    arg_offset=slot_index * 4,
                    field="generic",
                    metadata_family="generic-arg32",
                )

    sub_count = len(ecl.subs)
    if instruction.opcode in {OP_JUMP, OP_JUMPDEC} and len(instruction.args) >= 8:
        note_family("jump-offset")
        if _family_requested("jump-offset", family_filters):
            append_i32_samples("jump-offset", arg_offset=4, field="offset")
    if instruction.opcode == OP_CALL and len(instruction.args) >= 4:
        note_family("call-sub")
        if _family_requested("call-sub", family_filters):
            append_i32_samples("call-sub", arg_offset=0, field="index", context_limit=sub_count)
    if OP_MOVE_TIME_FIRST <= instruction.opcode <= OP_MOVE_TIME_LAST and len(instruction.args) >= 4:
        note_family("move-time")
        if _family_requested("move-time", family_filters):
            append_i32_samples("move-time", arg_offset=0, field="time")
        note_family("move-time-cross")
        if _family_requested("move-time-cross", family_filters):
            append_instruction_time_i32_pair_samples("move-time-cross", arg_offset=0, field_right="time")
    if instruction.opcode in {OP_SHOOTINTERVAL, OP_SHOOTINTERVALDELAYED} and len(instruction.args) >= 4:
        note_family("shoot-interval")
        if _family_requested("shoot-interval", family_filters):
            append_i32_samples("shoot-interval", arg_offset=0, field="time")
        note_family("shoot-interval-cross")
        if _family_requested("shoot-interval-cross", family_filters):
            append_instruction_time_i32_pair_samples("shoot-interval-cross", arg_offset=0, field_right="time")
    if instruction.opcode in {OP_LASERROTATE, OP_LASERROTATEFROMPLAYER, OP_LASEROFFSET, OP_LASERTEST, OP_LASERCANCEL} and len(instruction.args) >= 4:
        note_family("laser-index")
        if _family_requested("laser-index", family_filters):
            append_i32_samples("laser-index", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_ENEMYINTERRUPTSET and len(instruction.args) >= 8:
        note_family("interrupt-id")
        if _family_requested("interrupt-id", family_filters):
            append_i32_samples("interrupt-id", arg_offset=4, field="small-positive")
    if instruction.opcode == OP_BOSSTIMERSET and len(instruction.args) >= 4:
        note_family("boss-timer")
        if _family_requested("boss-timer", family_filters):
            append_i32_samples("boss-timer", arg_offset=0, field="time")
        note_family("boss-timer-cross")
        if _family_requested("boss-timer-cross", family_filters):
            append_instruction_time_i32_pair_samples("boss-timer-cross", arg_offset=0, field_right="time")
    if instruction.opcode == OP_LIFECALLBACKTHRESHOLD and len(instruction.args) >= 4:
        note_family("life-callback-threshold")
        if _family_requested("life-callback-threshold", family_filters):
            append_i32_samples("life-callback-threshold", arg_offset=0, field="time")
        note_family("life-callback-threshold-cross")
        if _family_requested("life-callback-threshold-cross", family_filters):
            append_instruction_time_i32_pair_samples("life-callback-threshold-cross", arg_offset=0, field_right="time")
    if instruction.opcode == OP_TIMERCALLBACKTHRESHOLD and len(instruction.args) >= 4:
        note_family("timer-callback-threshold")
        if _family_requested("timer-callback-threshold", family_filters):
            append_i32_samples("timer-callback-threshold", arg_offset=0, field="time")
        note_family("timer-callback-threshold-cross")
        if _family_requested("timer-callback-threshold-cross", family_filters):
            append_instruction_time_i32_pair_samples("timer-callback-threshold-cross", arg_offset=0, field_right="time")
    if instruction.opcode == OP_EXINSCALL and len(instruction.args) >= 4:
        note_family("exinscall")
        if _family_requested("exinscall", family_filters):
            append_i32_samples("exinscall", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_EXINSREPEAT and len(instruction.args) >= 4:
        note_family("exinsrepeat")
        if _family_requested("exinsrepeat", family_filters):
            append_i32_samples("exinsrepeat", arg_offset=0, field="count")
    if instruction.opcode == OP_SPELLCARDSTART and len(instruction.args) >= 4:
        note_family("spellcard-id")
        if _family_requested("spellcard-id", family_filters):
            append_i16_samples("spellcard-id", arg_offset=2, field="small-positive")
    if OP_BULLETFANAIMED <= instruction.opcode <= OP_BULLETRANDOM and len(instruction.args) >= 12:
        note_family("bullet-count1")
        if _family_requested("bullet-count1", family_filters):
            append_i32_samples("bullet-count1", arg_offset=4, field="count")
        note_family("bullet-count2")
        if _family_requested("bullet-count2", family_filters):
            append_i32_samples("bullet-count2", arg_offset=8, field="count")
        note_family("bullet-count-cross")
        if _family_requested("bullet-count-cross", family_filters):
            append_i32_pair_samples(
                "bullet-count-cross",
                left_offset=4,
                right_offset=8,
                field_left="count",
                field_right="count",
            )
        note_family("bullet-sprite")
        if _family_requested("bullet-sprite", family_filters):
            append_i16_samples("bullet-sprite", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_DROPITEMS and len(instruction.args) >= 4:
        note_family("drop-items")
        if _family_requested("drop-items", family_filters):
            append_i32_samples("drop-items", arg_offset=0, field="count")
    if instruction.opcode == OP_DROPITEMID and len(instruction.args) >= 4:
        note_family("drop-item-id")
        if _family_requested("drop-item-id", family_filters):
            append_i32_samples("drop-item-id", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_ANMSETSLOT and len(instruction.args) >= 4:
        note_family("anm-slot")
        if _family_requested("anm-slot", family_filters):
            append_i32_samples("anm-slot", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_ANMINTERRUPTSLOT and len(instruction.args) >= 4:
        note_family("anm-interrupt-slot")
        if _family_requested("anm-interrupt-slot", family_filters):
            append_i32_samples("anm-interrupt-slot", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_TIMESET and len(instruction.args) >= 4:
        note_family("time-set")
        if _family_requested("time-set", family_filters):
            append_i32_samples("time-set", arg_offset=0, field="time")
        note_family("time-set-cross")
        if _family_requested("time-set-cross", family_filters):
            append_instruction_time_i32_pair_samples("time-set-cross", arg_offset=0, field_right="time")
    if instruction.opcode == OP_BOSSSETLIFECOUNT and len(instruction.args) >= 4:
        note_family("boss-life-count")
        if _family_requested("boss-life-count", family_filters):
            append_i32_samples("boss-life-count", arg_offset=0, field="count")
    return _reorder_site_mutants(
        mutants,
        random_seed=random_seed,
        opcode=instruction.opcode,
        sub_index=sub_index,
        instruction_index=instruction_index,
        family_order_hint=site_family_order,
    )


def generate_exploration_mutants(
    ecl: EclFile,
    *,
    random_seed: int,
    samples_per_site: int = 4,
    family_filters: Sequence[str] | None = None,
) -> list[Mutant]:
    mutants: list[Mutant] = []
    for sub_index, subroutine in enumerate(ecl.subs):
        for instruction_index, instruction in enumerate(subroutine.instructions):
            mutants.extend(
                _sample_site_mutants(
                    ecl,
                    sub_index=sub_index,
                    instruction_index=instruction_index,
                    instruction=instruction,
                    random_seed=random_seed,
                    samples_per_site=samples_per_site,
                    family_filters=family_filters,
                )
            )

    deduped: list[Mutant] = []
    seen: set[tuple[str, tuple[int, int]]] = set()
    for mutant in mutants:
        dedupe_key = (mutant.name, mutant.path)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(mutant)
    return deduped
