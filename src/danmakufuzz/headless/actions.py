from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VALID_ACTIONS = {
    "stay",
    "up",
    "down",
    "left",
    "right",
    "up_left",
    "up_right",
    "down_left",
    "down_right",
    "stay_fast",
    "up_fast",
    "down_fast",
    "left_fast",
    "right_fast",
    "up_left_fast",
    "up_right_fast",
    "down_left_fast",
    "down_right_fast",
}
RAW_MASK_PREFIXES = ("mask:", "raw:")
FOCUS_MASK = 1 << 2
SHOOT_MASK = 1 << 0
_NAMED_ACTION_MASKS = {
    "stay": 0,
    "up": 1 << 4,
    "down": 1 << 5,
    "left": 1 << 6,
    "right": 1 << 7,
}
_NAMED_ACTION_MASKS.update(
    {
        "up_left": _NAMED_ACTION_MASKS["up"] | _NAMED_ACTION_MASKS["left"],
        "up_right": _NAMED_ACTION_MASKS["up"] | _NAMED_ACTION_MASKS["right"],
        "down_left": _NAMED_ACTION_MASKS["down"] | _NAMED_ACTION_MASKS["left"],
        "down_right": _NAMED_ACTION_MASKS["down"] | _NAMED_ACTION_MASKS["right"],
    }
)


@dataclass(frozen=True)
class ActionStream:
    actions: tuple[str, ...]

    @property
    def length(self) -> int:
        return len(self.actions)


def format_input_mask_token(mask: int) -> str:
    value = int(mask)
    if not (0 <= value <= 0xFFFF):
        raise ValueError(f"input mask is outside uint16 range: {mask}")
    return f"mask:0x{value:04x}"


def parse_input_mask_token(token: str) -> int | None:
    candidate = token.strip()
    if not candidate:
        return None
    raw_value = candidate
    for prefix in RAW_MASK_PREFIXES:
        if candidate.startswith(prefix):
            raw_value = candidate[len(prefix):]
            break
    else:
        if not candidate.lower().startswith("0x"):
            return None
    try:
        parsed = int(raw_value, 0)
    except ValueError:
        raise ValueError(f"invalid raw input mask token: {token!r}") from None
    if not (0 <= parsed <= 0xFFFF):
        raise ValueError(f"raw input mask is outside uint16 range: {token!r}")
    return parsed


def normalize_action_token(token: str) -> str:
    candidate = token.strip()
    if candidate in VALID_ACTIONS:
        return candidate
    parsed_mask = parse_input_mask_token(candidate)
    if parsed_mask is not None:
        return format_input_mask_token(parsed_mask)
    raise ValueError(f"unknown action {token!r}")


def action_token_to_input_mask(token: str, *, auto_shoot: bool = False) -> int:
    normalized = normalize_action_token(token)
    parsed_mask = parse_input_mask_token(normalized)
    if parsed_mask is not None:
        return parsed_mask | (SHOOT_MASK if auto_shoot else 0)
    if normalized.endswith("_fast"):
        direction_name = normalized.removesuffix("_fast")
        if direction_name not in _NAMED_ACTION_MASKS:
            raise ValueError(f"unknown fast action token: {token!r}")
        return _NAMED_ACTION_MASKS[direction_name] | (SHOOT_MASK if auto_shoot else 0)
    if normalized not in _NAMED_ACTION_MASKS:
        raise ValueError(f"unknown named action token: {token!r}")
    return _NAMED_ACTION_MASKS[normalized] | FOCUS_MASK | (SHOOT_MASK if auto_shoot else 0)


def serialize_actions_text(actions: list[str] | tuple[str, ...]) -> str:
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


def parse_actions_text(text: str) -> ActionStream:
    actions: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 1:
            repeat = 1
            action = parts[0]
        elif len(parts) == 2:
            repeat = int(parts[0])
            action = parts[1]
        else:
            raise ValueError(f"invalid action line {line_number}: {raw_line!r}")
        if repeat <= 0:
            raise ValueError(f"repeat count must be positive on line {line_number}")
        normalized_action = normalize_action_token(action)
        actions.extend([normalized_action] * repeat)
    return ActionStream(tuple(actions))


def parse_actions_file(path: Path) -> ActionStream:
    return parse_actions_text(path.read_text(encoding="utf-8"))


def serialize_mask_actions(masks: list[int] | tuple[int, ...]) -> str:
    return serialize_actions_text([format_input_mask_token(mask) for mask in masks])
