from __future__ import annotations

from dataclasses import dataclass

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
