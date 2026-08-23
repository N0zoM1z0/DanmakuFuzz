from __future__ import annotations

from dataclasses import dataclass
import struct

from ..corpus.pbg3 import sha256_bytes
from .game_cfg import GameConfiguration


@dataclass(frozen=True)
class GameCfgMutant:
    name: str
    payload: bytes
    source: str
    sha256: str


def _replace_u8(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    mutable[offset] = value & 0xFF
    return bytes(mutable)


def _replace_i16(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<h", mutable, offset, value)
    return bytes(mutable)


def _replace_i32(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<i", mutable, offset, value)
    return bytes(mutable)


def _replace_u32(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<I", mutable, offset, value & 0xFFFFFFFF)
    return bytes(mutable)


def _replace_bytes(payload: bytes, offset: int, data: bytes) -> bytes:
    mutable = bytearray(payload)
    mutable[offset:offset + len(data)] = data
    return bytes(mutable)


def generate_game_cfg_mutants(seed_payload: bytes) -> list[GameCfgMutant]:
    if len(seed_payload) < GameConfiguration.opts.offset + 4:
        raise ValueError("cfg seed payload is smaller than GameConfiguration")

    mutants: list[GameCfgMutant] = []

    def add(name: str, payload: bytes, source: str) -> None:
        mutants.append(
            GameCfgMutant(
                name=name,
                payload=payload,
                source=source,
                sha256=sha256_bytes(payload),
            )
        )

    add("truncate-header-8", seed_payload[:8], "header")
    add("append-garbage-4", seed_payload + b"FUZZ", "header")
    add("version-zero", _replace_i32(seed_payload, GameConfiguration.version.offset, 0), "header")
    add("version-max-i32", _replace_i32(seed_payload, GameConfiguration.version.offset, 0x7FFFFFFF), "header")
    add("life-five", _replace_u8(seed_payload, GameConfiguration.lifeCount.offset, 5), "scalar")
    add("bomb-four", _replace_u8(seed_payload, GameConfiguration.bombCount.offset, 4), "scalar")
    add("color-two", _replace_u8(seed_payload, GameConfiguration.colorMode16bit.offset, 2), "scalar")
    add("music-three", _replace_u8(seed_payload, GameConfiguration.musicMode.offset, 3), "scalar")
    add("play-sounds-two", _replace_u8(seed_payload, GameConfiguration.playSounds.offset, 2), "scalar")
    add("difficulty-five", _replace_u8(seed_payload, GameConfiguration.defaultDifficulty.offset, 5), "scalar")
    add("windowed-two", _replace_u8(seed_payload, GameConfiguration.windowed.offset, 2), "scalar")
    add("frameskip-three", _replace_u8(seed_payload, GameConfiguration.frameskipConfig.offset, 3), "scalar")
    add("pad-x-zero", _replace_i16(seed_payload, GameConfiguration.padXAxis.offset, 0), "scalar")
    add("pad-y-neg1", _replace_i16(seed_payload, GameConfiguration.padYAxis.offset, -1), "scalar")
    add("opts-all-ones", _replace_u32(seed_payload, GameConfiguration.opts.offset, 0xFFFFFFFF), "scalar")
    add(
        "controller-all-zero",
        _replace_bytes(seed_payload, GameConfiguration.controllerMapping.offset, b"\x00" * 18),
        "controller-mapping",
    )

    deduped: list[GameCfgMutant] = []
    seen: set[str] = set()
    for mutant in mutants:
        if mutant.sha256 in seen:
            continue
        seen.add(mutant.sha256)
        deduped.append(mutant)
    return deduped
