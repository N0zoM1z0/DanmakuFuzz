from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from collections.abc import Sequence

from .model import EclFile, EclSubroutine, RawInstruction, TimelineInstruction


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
    path: tuple[int, int] | None
    ecl: EclFile | DeferredMutation
    metadata: dict[str, object] | None = None


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


def _materialized_clone_with_mutated_timeline_instruction(
    ecl: EclFile,
    instruction_index: int,
    instruction: TimelineInstruction,
) -> EclFile:
    timeline = list(ecl.timeline)
    timeline[instruction_index] = instruction
    return EclFile(
        sub_count=ecl.sub_count,
        main_count=ecl.main_count,
        timeline_offsets=ecl.timeline_offsets,
        timeline=timeline,
        subs=ecl.subs,
    )


def _materialized_clone_with_mutated_timeline_instructions(
    ecl: EclFile,
    replacements: dict[int, TimelineInstruction],
) -> EclFile:
    timeline = list(ecl.timeline)
    for instruction_index, instruction in replacements.items():
        timeline[instruction_index] = instruction
    return EclFile(
        sub_count=ecl.sub_count,
        main_count=ecl.main_count,
        timeline_offsets=ecl.timeline_offsets,
        timeline=timeline,
        subs=ecl.subs,
    )


def _materialized_clone_with_mutated_instructions(
    ecl: EclFile,
    replacements: dict[tuple[int, int], RawInstruction],
) -> EclFile:
    subs = list(ecl.subs)
    instructions_by_sub: dict[int, list[RawInstruction]] = {}
    for (sub_index, instruction_index), instruction in replacements.items():
        instructions = instructions_by_sub.get(sub_index)
        if instructions is None:
            instructions = list(subs[sub_index].instructions)
            instructions_by_sub[sub_index] = instructions
        instructions[instruction_index] = instruction
    for sub_index, instructions in instructions_by_sub.items():
        selected_sub = subs[sub_index]
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


def _coerce_signed(value: int, *, bit_width: int) -> int:
    mask = (1 << bit_width) - 1
    coerced = int(value) & mask
    sign_bit = 1 << (bit_width - 1)
    if coerced & sign_bit:
        coerced -= 1 << bit_width
    return coerced


def _coerce_i32(value: int) -> int:
    return _coerce_signed(value, bit_width=32)


def _coerce_i16(value: int) -> int:
    return _coerce_signed(value, bit_width=16)


def _rotate_signed(value: int, *, shift: int, bit_width: int) -> int:
    mask = (1 << bit_width) - 1
    unsigned = int(value) & mask
    normalized_shift = shift % bit_width
    if normalized_shift == 0:
        return _coerce_signed(unsigned, bit_width=bit_width)
    rotated = ((unsigned << normalized_shift) | (unsigned >> (bit_width - normalized_shift))) & mask
    return _coerce_signed(rotated, bit_width=bit_width)


def _repeat_byte_pattern(byte_value: int, *, width_bytes: int) -> int:
    return _coerce_signed(
        int.from_bytes(bytes([byte_value & 0xFF]) * width_bytes, "little", signed=False),
        bit_width=width_bytes * 8,
    )


def _reverse_signed_bytes(value: int, *, width_bytes: int) -> int:
    bit_width = width_bytes * 8
    mask = (1 << bit_width) - 1
    data = (int(value) & mask).to_bytes(width_bytes, "little", signed=False)
    reversed_data = data[::-1]
    return _coerce_signed(int.from_bytes(reversed_data, "little", signed=False), bit_width=bit_width)


def _swap_i32_halves(value: int) -> int:
    unsigned = int(value) & 0xFFFFFFFF
    swapped = ((unsigned & 0xFFFF) << 16) | ((unsigned >> 16) & 0xFFFF)
    return _coerce_i32(swapped)


def _byte_pattern_values(current: int, *, width_bytes: int) -> list[int]:
    bit_width = width_bytes * 8
    mask = (1 << bit_width) - 1
    data = (int(current) & mask).to_bytes(width_bytes, "little", signed=False)
    byte_pool = {0x00, 0x01, 0x7F, 0x80, 0xFF, *data}
    return [
        _repeat_byte_pattern(byte_value, width_bytes=width_bytes)
        for byte_value in sorted(byte_pool)
    ]


def _havoc_signed_i32(current: int, *, rng: random.Random, count: int) -> list[int]:
    if count <= 0:
        return []

    delta_pool = (-0x10000, -0x1000, -0x100, -0x40, -0x10, -4, -1, 1, 4, 0x10, 0x40, 0x100, 0x1000, 0x10000)
    multiplier_pool = (-8, -4, -2, 2, 4, 8, 16)
    shift_pool = (1, 3, 7, 8, 11, 15, 16, 23, 24, 31)
    mask_pool = (
        0x000000FF,
        0x0000FFFF,
        0x00FF00FF,
        0x0F0F0F0F,
        0x33333333,
        0x55555555,
        0xAAAAAAAA,
        0xCCCCCCCC,
        0xF0F0F0F0,
        0xFF00FF00,
        0x7FFFFFFF,
        0x80000000,
        0xFFFFFFFF,
    )
    extreme_pool = (
        -(1 << 31),
        -(1 << 31) + 1,
        -0x1000000,
        -0x10000,
        -0x100,
        -1,
        0,
        1,
        0xFF,
        0x100,
        0x10000,
        (1 << 31) - 2,
        (1 << 31) - 1,
    )
    current_bytes = list((int(current) & 0xFFFFFFFF).to_bytes(4, "little", signed=False))
    seed_pool = [
        _coerce_i32(current),
        _coerce_i32(~current),
        _reverse_signed_bytes(current, width_bytes=4),
        _swap_i32_halves(current),
        _coerce_i32(rng.getrandbits(32)),
        _coerce_i32(rng.getrandbits(32) ^ (int(current) & 0xFFFFFFFF)),
        _repeat_byte_pattern(current_bytes[0], width_bytes=4),
        rng.choice(extreme_pool),
    ]
    values: list[int] = []
    for _ in range(max(8, count)):
        value = seed_pool[rng.randrange(len(seed_pool))]
        step_count = 1 + rng.randrange(4)
        for _ in range(step_count):
            operation = rng.choice((
                "add",
                "mul",
                "xor",
                "rotate",
                "mask",
                "byte-set",
                "byte-shuffle",
                "negate",
                "extreme",
            ))
            if operation == "add":
                delta = rng.choice(delta_pool) * rng.choice((1, 2, 4, 8, 16, 64))
                value = _coerce_i32(value + delta)
            elif operation == "mul":
                value = _coerce_i32(value * rng.choice(multiplier_pool))
            elif operation == "xor":
                value = _coerce_i32((value & 0xFFFFFFFF) ^ rng.choice(mask_pool))
            elif operation == "rotate":
                shift = rng.choice(shift_pool)
                if rng.getrandbits(1):
                    value = _rotate_signed(value, shift=shift, bit_width=32)
                else:
                    value = _rotate_signed(value, shift=32 - shift, bit_width=32)
            elif operation == "mask":
                mask = rng.choice(mask_pool)
                if rng.getrandbits(1):
                    value = _coerce_i32((value & 0xFFFFFFFF) & mask)
                else:
                    value = _coerce_i32((value & 0xFFFFFFFF) | mask)
            elif operation == "byte-set":
                data = bytearray((value & 0xFFFFFFFF).to_bytes(4, "little", signed=False))
                byte_index = rng.randrange(4)
                if rng.getrandbits(1):
                    data[byte_index] = rng.randrange(256)
                else:
                    data[byte_index] = current_bytes[rng.randrange(len(current_bytes))]
                value = _coerce_i32(int.from_bytes(data, "little", signed=False))
            elif operation == "byte-shuffle":
                data = bytearray((value & 0xFFFFFFFF).to_bytes(4, "little", signed=False))
                if rng.getrandbits(1):
                    data.reverse()
                else:
                    data = data[2:4] + data[0:2]
                value = _coerce_i32(int.from_bytes(data, "little", signed=False))
            elif operation == "negate":
                value = _coerce_i32(-value if rng.getrandbits(1) else ~value)
            else:
                edge = rng.choice(extreme_pool)
                value = _coerce_i32(edge + rng.choice((-7, -3, -1, 0, 1, 3, 7)))
        values.append(_coerce_i32(value))
    return values


def _havoc_signed_i16(current: int, *, rng: random.Random, count: int) -> list[int]:
    if count <= 0:
        return []

    delta_pool = (-0x100, -0x40, -0x10, -4, -1, 1, 4, 0x10, 0x40, 0x100)
    multiplier_pool = (-8, -4, -2, 2, 4, 8)
    shift_pool = (1, 3, 7, 8, 11, 15)
    mask_pool = (0x00FF, 0x0F0F, 0x3333, 0x5555, 0xAAAA, 0xF0F0, 0xFF00, 0x7FFF, 0x8000, 0xFFFF)
    extreme_pool = (-(1 << 15), -(1 << 15) + 1, -0x100, -1, 0, 1, 0x7F, 0x80, 0xFF, (1 << 15) - 2, (1 << 15) - 1)
    current_bytes = list((int(current) & 0xFFFF).to_bytes(2, "little", signed=False))
    seed_pool = [
        _coerce_i16(current),
        _coerce_i16(~current),
        _reverse_signed_bytes(current, width_bytes=2),
        _coerce_i16(rng.getrandbits(16)),
        _coerce_i16(rng.getrandbits(16) ^ (int(current) & 0xFFFF)),
        _repeat_byte_pattern(current_bytes[0], width_bytes=2),
        rng.choice(extreme_pool),
    ]
    values: list[int] = []
    for _ in range(max(6, count)):
        value = seed_pool[rng.randrange(len(seed_pool))]
        step_count = 1 + rng.randrange(3)
        for _ in range(step_count):
            operation = rng.choice(("add", "mul", "xor", "rotate", "mask", "byte-set", "byte-shuffle", "negate", "extreme"))
            if operation == "add":
                delta = rng.choice(delta_pool) * rng.choice((1, 2, 4, 8, 16))
                value = _coerce_i16(value + delta)
            elif operation == "mul":
                value = _coerce_i16(value * rng.choice(multiplier_pool))
            elif operation == "xor":
                value = _coerce_i16((value & 0xFFFF) ^ rng.choice(mask_pool))
            elif operation == "rotate":
                shift = rng.choice(shift_pool)
                if rng.getrandbits(1):
                    value = _rotate_signed(value, shift=shift, bit_width=16)
                else:
                    value = _rotate_signed(value, shift=16 - shift, bit_width=16)
            elif operation == "mask":
                mask = rng.choice(mask_pool)
                if rng.getrandbits(1):
                    value = _coerce_i16((value & 0xFFFF) & mask)
                else:
                    value = _coerce_i16((value & 0xFFFF) | mask)
            elif operation == "byte-set":
                data = bytearray((value & 0xFFFF).to_bytes(2, "little", signed=False))
                byte_index = rng.randrange(2)
                if rng.getrandbits(1):
                    data[byte_index] = rng.randrange(256)
                else:
                    data[byte_index] = current_bytes[rng.randrange(len(current_bytes))]
                value = _coerce_i16(int.from_bytes(data, "little", signed=False))
            elif operation == "byte-shuffle":
                data = bytearray((value & 0xFFFF).to_bytes(2, "little", signed=False))
                data.reverse()
                value = _coerce_i16(int.from_bytes(data, "little", signed=False))
            elif operation == "negate":
                value = _coerce_i16(-value if rng.getrandbits(1) else ~value)
            else:
                edge = rng.choice(extreme_pool)
                value = _coerce_i16(edge + rng.choice((-3, -1, 0, 1, 3)))
        values.append(_coerce_i16(value))
    return values


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
    byte_pattern_values = _byte_pattern_values(current, width_bytes=4)
    structured_values = [
        _reverse_signed_bytes(current, width_bytes=4),
        _swap_i32_halves(current),
        _coerce_i32(~current),
        _rotate_signed(current, shift=8, bit_width=32),
        _rotate_signed(current, shift=16, bit_width=32),
    ]
    havoc_values = _havoc_signed_i32(current, rng=rng, count=max(8, budget * 4))
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
            byte_pattern_values,
            structured_values,
            random_local_values,
            random_stride_values,
            random_extreme_values,
            havoc_values,
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
    byte_pattern_values = _byte_pattern_values(current, width_bytes=2)
    structured_values = [
        _reverse_signed_bytes(current, width_bytes=2),
        _coerce_i16(~current),
        _rotate_signed(current, shift=8, bit_width=16),
    ]
    havoc_values = _havoc_signed_i16(current, rng=rng, count=max(6, budget * 4))
    return _sample_value_groups(
        [
            list(base),
            relative_values,
            scaled_values,
            bitflip_values,
            power_values,
            magnitude_values,
            mirrored_values,
            byte_pattern_values,
            structured_values,
            random_local_values,
            random_stride_values,
            random_extreme_values,
            havoc_values,
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


def _select_slot_indices(
    *,
    slot_count: int,
    rng: random.Random,
    target_count: int,
) -> list[int]:
    if slot_count <= 0 or target_count <= 0:
        return []
    if slot_count <= target_count:
        return list(range(slot_count))

    anchors = [0, 1, slot_count // 2, slot_count - 2, slot_count - 1]
    selected: list[int] = []
    for index in anchors:
        if index < 0 or index >= slot_count:
            continue
        if index in selected:
            continue
        selected.append(index)
        if len(selected) >= target_count:
            return selected

    remaining = [index for index in range(slot_count) if index not in selected]
    rng.shuffle(remaining)
    selected.extend(remaining[: max(0, target_count - len(selected))])
    return selected


def _select_generic_i32_slots(
    *,
    slot_count: int,
    rng: random.Random,
    target_count: int,
) -> list[int]:
    return _select_slot_indices(
        slot_count=slot_count,
        rng=rng,
        target_count=target_count,
    )


def _select_generic_i16_slots(
    *,
    slot_count: int,
    rng: random.Random,
    target_count: int,
) -> list[int]:
    return _select_slot_indices(
        slot_count=slot_count,
        rng=rng,
        target_count=target_count,
    )


def _timeline_site_key(instruction_index: int) -> str:
    return f"tl{instruction_index:04d}"


def _timeline_pair_key(instruction_indices: Sequence[int]) -> str:
    return "__".join(_timeline_site_key(instruction_index) for instruction_index in instruction_indices)


def _timeline_site_records(instruction_indices: Sequence[int]) -> list[dict[str, object]]:
    return [
        {
            "site_kind": "timeline",
            "instruction_index": instruction_index,
        }
        for instruction_index in instruction_indices
    ]


def _site_key_from_pairs(sites: Sequence[tuple[int, int]]) -> str:
    return "__".join(f"s{sub_index:02d}:i{instruction_index:04d}" for sub_index, instruction_index in sites)


def _site_slug_from_pairs(sites: Sequence[tuple[int, int]]) -> str:
    return "__".join(f"s{sub_index:02d}-i{instruction_index:04d}" for sub_index, instruction_index in sites)


def _site_records_from_pairs(sites: Sequence[tuple[int, int]]) -> list[dict[str, int]]:
    return [
        {"sub_index": sub_index, "instruction_index": instruction_index}
        for sub_index, instruction_index in sites
    ]


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

    def append_instruction_i16_samples(
        family: str,
        *,
        field_name: str,
        field: str,
        metadata_family: str | None = None,
    ) -> None:
        current = int(getattr(instruction, field_name))
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
                        RawInstruction(**{**instruction.__dict__, field_name: value}),
                    ),
                    metadata={
                        "strategy": "sampled-instruction-i16",
                        "family": metadata_family or family,
                        "field_name": field_name,
                        "field": field,
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
        metadata_family: str | None = None,
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
                        "family": metadata_family or family,
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
        metadata_family: str | None = None,
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
                        "family": metadata_family or family,
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
    note_family("generic-opcode")
    if _family_requested("generic-opcode", family_filters):
        append_instruction_i16_samples("generic-opcode", field_name="opcode", field="generic")
    note_family("difficulty-mask")
    if _family_requested("difficulty-mask", family_filters):
        append_instruction_u8_samples("difficulty-mask", field_name="skip_for_difficulty", field="bitmask")
    note_family("instruction-aux-byte")
    if _family_requested("instruction-aux-byte", family_filters):
        aux_rng = _site_rng(
            random_seed,
            opcode=instruction.opcode,
            sub_index=sub_index,
            instruction_index=instruction_index,
            family="instruction-aux-byte-fields",
        )
        selected_aux_fields = ["unk8", "unk_a", "unk_b"]
        if len(selected_aux_fields) > 2:
            aux_rng.shuffle(selected_aux_fields)
            selected_aux_fields = selected_aux_fields[:2]
        for field_name in selected_aux_fields:
            append_instruction_u8_samples(
                f"instruction-aux-byte-{field_name}",
                field_name=field_name,
                field="bitmask",
                metadata_family="instruction-aux-byte",
            )
    if len(instruction.args) >= 2:
        note_family("generic-arg16")
        if _family_requested("generic-arg16", family_filters):
            slot_rng = _site_rng(
                random_seed,
                opcode=instruction.opcode,
                sub_index=sub_index,
                instruction_index=instruction_index,
                family="generic-arg16-slots",
            )
            slot_indices = _select_generic_i16_slots(
                slot_count=len(instruction.args) // 2,
                rng=slot_rng,
                target_count=min(len(instruction.args) // 2, max(2, samples_per_site)),
            )
            for slot_index in slot_indices:
                append_i16_samples(
                    f"generic-arg16-o{slot_index}",
                    arg_offset=slot_index * 2,
                    field="generic",
                    metadata_family="generic-arg16",
                )
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
                target_count=min(len(instruction.args) // 4, max(2, samples_per_site)),
            )
            for slot_index in slot_indices:
                append_i32_samples(
                    f"generic-arg32-o{slot_index}",
                    arg_offset=slot_index * 4,
                    field="generic",
                    metadata_family="generic-arg32",
                )
    if len(instruction.args) >= 8:
        note_family("generic-arg32-cross")
        if _family_requested("generic-arg32-cross", family_filters):
            pair_rng = _site_rng(
                random_seed,
                opcode=instruction.opcode,
                sub_index=sub_index,
                instruction_index=instruction_index,
                family="generic-arg32-cross-slots",
            )
            slot_indices = _select_generic_i32_slots(
                slot_count=len(instruction.args) // 4,
                rng=pair_rng,
                target_count=min(len(instruction.args) // 4, max(3, samples_per_site + 1)),
            )
            slot_pairs: list[tuple[int, int]] = []
            if len(slot_indices) >= 2:
                slot_pairs.append((slot_indices[0], slot_indices[1]))
            if len(slot_indices) >= 4:
                slot_pairs.append((slot_indices[2], slot_indices[3]))
            elif len(slot_indices) >= 3:
                slot_pairs.append((slot_indices[0], slot_indices[2]))
            for left_slot, right_slot in slot_pairs:
                append_i32_pair_samples(
                    f"generic-arg32-cross-o{left_slot}-o{right_slot}",
                    left_offset=left_slot * 4,
                    right_offset=right_slot * 4,
                    field_left="generic",
                    field_right="generic",
                    metadata_family="generic-arg32-cross",
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


def _sample_timeline_mutants(
    ecl: EclFile,
    *,
    random_seed: int,
    samples_per_site: int,
    family_filters: Sequence[str] | None,
) -> list[Mutant]:
    mutants: list[Mutant] = []
    for instruction_index, instruction in enumerate(ecl.timeline):
        site_family_order: list[str] = []
        site_key = _timeline_site_key(instruction_index)
        site_records = _timeline_site_records((instruction_index,))

        def note_family(family: str) -> None:
            site_family_order.append(family)

        def append_timeline_i16_samples(
            family: str,
            *,
            field_name: str,
            field: str,
        ) -> None:
            current = int(getattr(instruction, field_name))
            rng = _site_rng(
                random_seed,
                opcode=instruction.opcode,
                sub_index=-1,
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
                        None,
                        _materialized_clone_with_mutated_timeline_instruction(
                            ecl,
                            instruction_index,
                            TimelineInstruction(**{**instruction.__dict__, field_name: value}),
                        ),
                        metadata={
                            "strategy": "sampled-timeline-i16",
                            "family": family,
                            "field_name": field_name,
                            "field": field,
                            "value": value,
                            "random_seed": random_seed,
                            "site_key": site_key,
                            "site_slug": site_key,
                            "sites": site_records,
                        },
                    )
                )

        note_family("timeline-time")
        if _family_requested("timeline-time", family_filters):
            append_timeline_i16_samples("timeline-time", field_name="time", field="generic")
        note_family("timeline-arg0")
        if _family_requested("timeline-arg0", family_filters):
            append_timeline_i16_samples("timeline-arg0", field_name="arg0", field="generic")
        note_family("timeline-opcode")
        if _family_requested("timeline-opcode", family_filters):
            append_timeline_i16_samples("timeline-opcode", field_name="opcode", field="generic")

        site_mutants = [mutant for mutant in mutants if mutant.metadata and mutant.metadata.get("site_key") == site_key]
        if not site_mutants:
            continue
        reordered = _reorder_site_mutants(
            site_mutants,
            random_seed=random_seed,
            opcode=instruction.opcode,
            sub_index=-1,
            instruction_index=instruction_index,
            family_order_hint=site_family_order,
        )
        if reordered != site_mutants:
            survivors = [mutant for mutant in mutants if mutant not in site_mutants]
            survivors.extend(reordered)
            mutants = survivors
    return mutants


def _sample_adjacent_time_pair_mutants(
    ecl: EclFile,
    *,
    random_seed: int,
    samples_per_site: int,
    family_filters: Sequence[str] | None,
) -> list[Mutant]:
    family = "adjacent-instruction-time-cross"
    if not _family_requested(family, family_filters):
        return []

    mutants: list[Mutant] = []
    for sub_index, subroutine in enumerate(ecl.subs):
        instructions = subroutine.instructions
        for instruction_index in range(len(instructions) - 1):
            left_instruction = instructions[instruction_index]
            right_instruction = instructions[instruction_index + 1]
            if abs(int(left_instruction.time) - int(right_instruction.time)) > 32:
                continue
            left_site = (sub_index, instruction_index)
            right_site = (sub_index, instruction_index + 1)
            sites = (left_site, right_site)
            rng = _site_rng(
                random_seed,
                opcode=((left_instruction.opcode & 0xFFFF) << 16) | (right_instruction.opcode & 0xFFFF),
                sub_index=sub_index,
                instruction_index=instruction_index,
                family=family,
            )
            for left_value, right_value in _sample_paired_signed_i32(
                current_left=int(left_instruction.time),
                current_right=int(right_instruction.time),
                budget=max(2, samples_per_site),
                rng=rng,
                field_left="time",
                field_right="time",
            ):
                mutants.append(
                    Mutant(
                        f"{family}-sampled-{_value_slug(left_value)}-{_value_slug(right_value)}",
                        left_site,
                        _materialized_clone_with_mutated_instructions(
                            ecl,
                            {
                                left_site: RawInstruction(
                                    **{**left_instruction.__dict__, "time": left_value}
                                ),
                                right_site: RawInstruction(
                                    **{**right_instruction.__dict__, "time": right_value}
                                ),
                            },
                        ),
                        metadata={
                            "strategy": "sampled-adjacent-instruction-time-i32-pair",
                            "family": family,
                            "field_left": "time",
                            "field_right": "time",
                            "left_value": left_value,
                            "right_value": right_value,
                            "random_seed": random_seed,
                            "site_key": _site_key_from_pairs(sites),
                            "site_slug": _site_slug_from_pairs(sites),
                            "sites": _site_records_from_pairs(sites),
                        },
                    )
                )
    return mutants


def _sample_adjacent_timeline_time_pair_mutants(
    ecl: EclFile,
    *,
    random_seed: int,
    samples_per_site: int,
    family_filters: Sequence[str] | None,
) -> list[Mutant]:
    family = "adjacent-timeline-time-cross"
    if not _family_requested(family, family_filters):
        return []

    mutants: list[Mutant] = []
    for instruction_index in range(len(ecl.timeline) - 1):
        left_instruction = ecl.timeline[instruction_index]
        right_instruction = ecl.timeline[instruction_index + 1]
        if abs(int(left_instruction.time) - int(right_instruction.time)) > 32:
            continue
        site_indices = (instruction_index, instruction_index + 1)
        rng = _site_rng(
            random_seed,
            opcode=((left_instruction.opcode & 0xFFFF) << 16) | (right_instruction.opcode & 0xFFFF),
            sub_index=-1,
            instruction_index=instruction_index,
            family=family,
        )
        for left_value, right_value in _sample_paired_signed_i32(
            current_left=int(left_instruction.time),
            current_right=int(right_instruction.time),
            budget=max(2, samples_per_site),
            rng=rng,
            field_left="time",
            field_right="time",
        ):
            mutants.append(
                Mutant(
                    f"{family}-sampled-{_value_slug(left_value)}-{_value_slug(right_value)}",
                    None,
                    _materialized_clone_with_mutated_timeline_instructions(
                        ecl,
                        {
                            instruction_index: TimelineInstruction(
                                **{**left_instruction.__dict__, "time": _coerce_i16(left_value)}
                            ),
                            instruction_index + 1: TimelineInstruction(
                                **{**right_instruction.__dict__, "time": _coerce_i16(right_value)}
                            ),
                        },
                    ),
                    metadata={
                        "strategy": "sampled-adjacent-timeline-time-i16-pair",
                        "family": family,
                        "field_left": "time",
                        "field_right": "time",
                        "left_value": _coerce_i16(left_value),
                        "right_value": _coerce_i16(right_value),
                        "random_seed": random_seed,
                        "site_key": _timeline_pair_key(site_indices),
                        "site_slug": _timeline_pair_key(site_indices),
                        "sites": _timeline_site_records(site_indices),
                    },
                )
            )
    return mutants


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
    mutants.extend(
        _sample_timeline_mutants(
            ecl,
            random_seed=random_seed,
            samples_per_site=samples_per_site,
            family_filters=family_filters,
        )
    )
    mutants.extend(
        _sample_adjacent_time_pair_mutants(
            ecl,
            random_seed=random_seed,
            samples_per_site=samples_per_site,
            family_filters=family_filters,
        )
    )
    mutants.extend(
        _sample_adjacent_timeline_time_pair_mutants(
            ecl,
            random_seed=random_seed,
            samples_per_site=samples_per_site,
            family_filters=family_filters,
        )
    )

    deduped: list[Mutant] = []
    seen: set[tuple[str, tuple[int, int] | None]] = set()
    for mutant in mutants:
        dedupe_key = (mutant.name, mutant.path)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(mutant)
    return deduped
