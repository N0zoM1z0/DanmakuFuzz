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


@dataclass(frozen=True)
class ActionStream:
    actions: tuple[str, ...]

    @property
    def length(self) -> int:
        return len(self.actions)


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
        if action not in VALID_ACTIONS:
            raise ValueError(f"unknown action {action!r} on line {line_number}")
        actions.extend([action] * repeat)
    return ActionStream(tuple(actions))


def parse_actions_file(path: Path) -> ActionStream:
    return parse_actions_text(path.read_text(encoding="utf-8"))
