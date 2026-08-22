from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random

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
class Mutant:
    name: str
    path: tuple[int, int]
    ecl: EclFile
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


def _sample_values(
    values: list[int],
    *,
    current: int,
    minimum: int,
    maximum: int,
    budget: int,
    rng: random.Random,
) -> list[int]:
    candidates = _dedupe_ints(values, minimum=minimum, maximum=maximum, current=current)
    if budget <= 0 or len(candidates) <= budget:
        return candidates
    sampled = list(candidates)
    rng.shuffle(sampled)
    return sampled[:budget]


def _relative_values(current: int, deltas: tuple[int, ...]) -> list[int]:
    values = [current + delta for delta in deltas]
    values.append(-current)
    return values


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
    }[family]
    values = list(base)
    if context_limit is not None:
        values.extend([context_limit - 1, context_limit, context_limit + 1])
    values.extend(_relative_values(current, (-4096, -1024, -256, -64, -16, -4, -1, 1, 4, 16, 64, 256, 1024, 4096)))
    return _sample_values(
        values,
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
    }[family]
    values = list(base)
    values.extend(_relative_values(current, (-128, -64, -16, -4, -1, 1, 4, 16, 64, 128)))
    return _sample_values(
        values,
        current=current,
        minimum=-(1 << 15),
        maximum=(1 << 15) - 1,
        budget=budget,
        rng=rng,
    )


def _sample_site_mutants(
    ecl: EclFile,
    *,
    sub_index: int,
    instruction_index: int,
    instruction: RawInstruction,
    random_seed: int,
    samples_per_site: int,
) -> list[Mutant]:
    key = (sub_index, instruction_index)
    mutants: list[Mutant] = []

    def append_i32_samples(
        family: str,
        *,
        arg_offset: int,
        field: str,
        context_limit: int | None = None,
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
                        "family": family,
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
                        "family": family,
                        "field": field,
                        "arg_offset": arg_offset,
                        "value": value,
                        "random_seed": random_seed,
                    },
                )
            )

    sub_count = len(ecl.subs)
    if instruction.opcode in {OP_JUMP, OP_JUMPDEC} and len(instruction.args) >= 8:
        append_i32_samples("jump-offset", arg_offset=4, field="offset")
    if instruction.opcode == OP_CALL and len(instruction.args) >= 4:
        append_i32_samples("call-sub", arg_offset=0, field="index", context_limit=sub_count)
    if OP_MOVE_TIME_FIRST <= instruction.opcode <= OP_MOVE_TIME_LAST and len(instruction.args) >= 4:
        append_i32_samples("move-time", arg_offset=0, field="time")
    if instruction.opcode in {OP_SHOOTINTERVAL, OP_SHOOTINTERVALDELAYED} and len(instruction.args) >= 4:
        append_i32_samples("shoot-interval", arg_offset=0, field="time")
    if instruction.opcode in {OP_LASERROTATE, OP_LASERROTATEFROMPLAYER, OP_LASEROFFSET, OP_LASERTEST, OP_LASERCANCEL} and len(instruction.args) >= 4:
        append_i32_samples("laser-index", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_ENEMYINTERRUPTSET and len(instruction.args) >= 8:
        append_i32_samples("interrupt-id", arg_offset=4, field="small-positive")
    if instruction.opcode == OP_BOSSTIMERSET and len(instruction.args) >= 4:
        append_i32_samples("boss-timer", arg_offset=0, field="time")
    if instruction.opcode == OP_LIFECALLBACKTHRESHOLD and len(instruction.args) >= 4:
        append_i32_samples("life-callback-threshold", arg_offset=0, field="time")
    if instruction.opcode == OP_TIMERCALLBACKTHRESHOLD and len(instruction.args) >= 4:
        append_i32_samples("timer-callback-threshold", arg_offset=0, field="time")
    if instruction.opcode == OP_EXINSCALL and len(instruction.args) >= 4:
        append_i32_samples("exinscall", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_EXINSREPEAT and len(instruction.args) >= 4:
        append_i32_samples("exinsrepeat", arg_offset=0, field="count")
    if instruction.opcode == OP_SPELLCARDSTART and len(instruction.args) >= 4:
        append_i16_samples("spellcard-id", arg_offset=2, field="small-positive")
    if OP_BULLETFANAIMED <= instruction.opcode <= OP_BULLETRANDOM and len(instruction.args) >= 12:
        append_i32_samples("bullet-count1", arg_offset=4, field="count")
        append_i32_samples("bullet-count2", arg_offset=8, field="count")
        append_i16_samples("bullet-sprite", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_DROPITEMS and len(instruction.args) >= 4:
        append_i32_samples("drop-items", arg_offset=0, field="count")
    if instruction.opcode == OP_DROPITEMID and len(instruction.args) >= 4:
        append_i32_samples("drop-item-id", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_ANMSETSLOT and len(instruction.args) >= 4:
        append_i32_samples("anm-slot", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_ANMINTERRUPTSLOT and len(instruction.args) >= 4:
        append_i32_samples("anm-interrupt-slot", arg_offset=0, field="small-positive")
    if instruction.opcode == OP_TIMESET and len(instruction.args) >= 4:
        append_i32_samples("time-set", arg_offset=0, field="time")
    if instruction.opcode == OP_BOSSSETLIFECOUNT and len(instruction.args) >= 4:
        append_i32_samples("boss-life-count", arg_offset=0, field="count")
    return mutants


def generate_exploration_mutants(
    ecl: EclFile,
    *,
    random_seed: int,
    samples_per_site: int = 4,
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
