from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path

from ..repo import REFERENCE_DIR


GAME_VERSION = 0x102
MUSIC_MODE_OFF = 0
MUSIC_MODE_WAV = 1
MUSIC_MODE_MIDI = 2

OPTION_BITS = {
    0: "use_d3d_hw_texture_blending",
    1: "dont_use_vertex_buf",
    2: "force_16bit_color_mode",
    3: "clear_backbuffer_on_refresh",
    4: "display_minimum_graphics",
    5: "suppress_use_of_gouraud_shading",
    6: "turn_off_depth_test",
    7: "force_60fps",
    8: "no_color_comp",
    9: "reference_rasterizer_mode",
    10: "dont_use_fog",
    11: "no_directinput_pad",
}

DEFAULT_CONTROLLER_MAPPING = (0, 1, 2, 4, -1, -1, -1, -1, 3)
DEFAULT_CFG_PATH = REFERENCE_DIR / "retail" / "game" / "th06" / "東方紅魔郷.cfg"


class ControllerMapping(ctypes.LittleEndianStructure):
    _fields_ = [
        ("shootButton", ctypes.c_int16),
        ("bombButton", ctypes.c_int16),
        ("focusButton", ctypes.c_int16),
        ("menuButton", ctypes.c_int16),
        ("upButton", ctypes.c_int16),
        ("downButton", ctypes.c_int16),
        ("leftButton", ctypes.c_int16),
        ("rightButton", ctypes.c_int16),
        ("skipButton", ctypes.c_int16),
    ]


class GameConfiguration(ctypes.LittleEndianStructure):
    _fields_ = [
        ("controllerMapping", ControllerMapping),
        ("version", ctypes.c_int32),
        ("lifeCount", ctypes.c_uint8),
        ("bombCount", ctypes.c_uint8),
        ("colorMode16bit", ctypes.c_uint8),
        ("musicMode", ctypes.c_uint8),
        ("playSounds", ctypes.c_uint8),
        ("defaultDifficulty", ctypes.c_uint8),
        ("windowed", ctypes.c_uint8),
        ("frameskipConfig", ctypes.c_uint8),
        ("padXAxis", ctypes.c_int16),
        ("padYAxis", ctypes.c_int16),
        ("unk", ctypes.c_int8 * 16),
        ("opts", ctypes.c_uint32),
    ]


def _enabled_option_names(opts: int) -> list[str]:
    return [name for bit, name in OPTION_BITS.items() if (int(opts) >> bit) & 1]


def _controller_mapping(cfg: GameConfiguration) -> list[int]:
    mapping = cfg.controllerMapping
    return [
        int(mapping.shootButton),
        int(mapping.bombButton),
        int(mapping.focusButton),
        int(mapping.menuButton),
        int(mapping.upButton),
        int(mapping.downButton),
        int(mapping.leftButton),
        int(mapping.rightButton),
        int(mapping.skipButton),
    ]


def default_game_cfg(*, has_wav_bgm: bool = True) -> GameConfiguration:
    cfg = GameConfiguration()
    cfg.version = GAME_VERSION
    cfg.lifeCount = 2
    cfg.bombCount = 3
    cfg.colorMode16bit = 0xFF
    cfg.musicMode = MUSIC_MODE_WAV if has_wav_bgm else MUSIC_MODE_MIDI
    cfg.playSounds = 1
    cfg.defaultDifficulty = 1
    cfg.windowed = 0
    cfg.frameskipConfig = 0
    cfg.padXAxis = 600
    cfg.padYAxis = 600
    cfg.opts = 1
    mapping = ControllerMapping()
    (
        mapping.shootButton,
        mapping.bombButton,
        mapping.focusButton,
        mapping.menuButton,
        mapping.upButton,
        mapping.downButton,
        mapping.leftButton,
        mapping.rightButton,
        mapping.skipButton,
    ) = DEFAULT_CONTROLLER_MAPPING
    cfg.controllerMapping = mapping
    return cfg


def _cfg_summary(cfg: GameConfiguration) -> dict[str, object]:
    return {
        "version": int(cfg.version),
        "life_count": int(cfg.lifeCount),
        "bomb_count": int(cfg.bombCount),
        "color_mode_16bit": int(cfg.colorMode16bit),
        "music_mode": int(cfg.musicMode),
        "play_sounds": int(cfg.playSounds),
        "default_difficulty": int(cfg.defaultDifficulty),
        "windowed": int(cfg.windowed),
        "frameskip_config": int(cfg.frameskipConfig),
        "pad_x_axis": int(cfg.padXAxis),
        "pad_y_axis": int(cfg.padYAxis),
        "opts": int(cfg.opts),
        "enabled_option_names": _enabled_option_names(int(cfg.opts)),
        "controller_mapping": _controller_mapping(cfg),
    }


def load_game_cfg(data: bytes, *, has_wav_bgm: bool = True) -> dict[str, object]:
    expected_size = ctypes.sizeof(GameConfiguration)
    fallback_reasons: list[str] = []

    parsed_cfg: GameConfiguration | None = None
    if len(data) >= expected_size:
        parsed_cfg = GameConfiguration.from_buffer_copy(data[:expected_size])
    else:
        fallback_reasons.append("truncated")

    if len(data) != expected_size:
        fallback_reasons.append("size-mismatch")

    if parsed_cfg is not None:
        if int(parsed_cfg.lifeCount) >= 5:
            fallback_reasons.append("life-count-out-of-range")
        if int(parsed_cfg.bombCount) >= 4:
            fallback_reasons.append("bomb-count-out-of-range")
        if int(parsed_cfg.colorMode16bit) >= 2:
            fallback_reasons.append("color-mode-out-of-range")
        if int(parsed_cfg.musicMode) >= 3:
            fallback_reasons.append("music-mode-out-of-range")
        if int(parsed_cfg.defaultDifficulty) >= 5:
            fallback_reasons.append("default-difficulty-out-of-range")
        if int(parsed_cfg.playSounds) >= 2:
            fallback_reasons.append("play-sounds-out-of-range")
        if int(parsed_cfg.windowed) >= 2:
            fallback_reasons.append("windowed-out-of-range")
        if int(parsed_cfg.frameskipConfig) >= 3:
            fallback_reasons.append("frameskip-out-of-range")
        if int(parsed_cfg.version) != GAME_VERSION:
            fallback_reasons.append("version-mismatch")

    effective_cfg = parsed_cfg if parsed_cfg is not None and not fallback_reasons else default_game_cfg(has_wav_bgm=has_wav_bgm)
    classification = "loaded" if parsed_cfg is not None and not fallback_reasons else "fallback-defaults"
    return {
        "input_size": len(data),
        "expected_size": expected_size,
        "classification": classification,
        "fallback_reasons": fallback_reasons,
        "raw_summary": _cfg_summary(parsed_cfg) if parsed_cfg is not None else None,
        "effective_summary": _cfg_summary(effective_cfg),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and classify Touhou game cfg payloads.")
    parser.add_argument("--input", type=Path, default=DEFAULT_CFG_PATH)
    parser.add_argument("--no-wav-bgm", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"missing cfg file: {input_path}")
    result = {
        "input": str(input_path),
        **load_game_cfg(input_path.read_bytes(), has_wav_bgm=not args.no_wav_bgm),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
