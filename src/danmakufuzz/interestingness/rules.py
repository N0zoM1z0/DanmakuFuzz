from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finding:
    kind: str
    detail: str


def _walk_numbers(value: Any, findings: list[Finding], path: str = "$") -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            findings.append(Finding("non-finite", f"{path}={value!r}"))
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            _walk_numbers(nested, findings, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_numbers(nested, findings, f"{path}[{index}]")


def score_trace(path: Path, *, stall_window: int = 240, bullet_limit: int = 1024) -> list[Finding]:
    findings: list[Finding] = []
    last_frame: int | None = None
    repeated_frames = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            _walk_numbers(record, findings)
            frame = record.get("frame")
            if isinstance(frame, int):
                if last_frame == frame:
                    repeated_frames += 1
                else:
                    repeated_frames = 0
                last_frame = frame
                if repeated_frames >= stall_window:
                    findings.append(Finding("stalled-frame", f"frame {frame} repeated >= {stall_window} times"))
                    break
            bullets = record.get("bullets")
            if isinstance(bullets, list) and len(bullets) > bullet_limit:
                findings.append(Finding("bullet-explosion", f"line {line_number} bullet_count={len(bullets)}"))
            lasers = record.get("lasers")
            if isinstance(lasers, list) and len(lasers) > bullet_limit:
                findings.append(Finding("laser-explosion", f"line {line_number} laser_count={len(lasers)}"))
            enemies = record.get("enemies")
            if isinstance(enemies, list) and len(enemies) > 512:
                findings.append(Finding("enemy-explosion", f"line {line_number} enemy_count={len(enemies)}"))
            terminal_reason = record.get("terminal_reason")
            if terminal_reason and terminal_reason not in {"physical-hit", "tick-limit", "input-error"}:
                findings.append(Finding("unexpected-terminal", str(terminal_reason)))
    return findings
