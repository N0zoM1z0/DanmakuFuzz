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


def _load_trace_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records.append(json.loads(line))
    return records


def _entity_count(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, list):
        return len(value)
    return 0


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


def score_trace_differential(
    path: Path,
    baseline_path: Path,
    *,
    sustained_window: int = 16,
    bullet_drift_threshold: int = 8,
    enemy_drift_threshold: int = 2,
    laser_drift_threshold: int = 1,
    score_drift_threshold: int = 100,
    shortfall_threshold: int = 32,
) -> list[Finding]:
    baseline_records = _load_trace_records(baseline_path)
    case_records = _load_trace_records(path)
    if not baseline_records or not case_records:
        return []

    findings: list[Finding] = []
    bullet_streak = 0
    enemy_streak = 0
    laser_streak = 0
    score_streak = 0
    saw_bullet_drift = False
    saw_enemy_drift = False
    saw_laser_drift = False
    saw_score_drift = False
    saw_life_drift = False
    saw_bomb_drift = False

    for line_number, (baseline_record, case_record) in enumerate(zip(baseline_records, case_records), start=1):
        tick = case_record.get("tick")
        tick_label = tick if isinstance(tick, int) else line_number

        baseline_bullets = _entity_count(baseline_record, "bullets")
        case_bullets = _entity_count(case_record, "bullets")
        bullet_streak = bullet_streak + 1 if abs(baseline_bullets - case_bullets) >= bullet_drift_threshold else 0
        if bullet_streak >= sustained_window and not saw_bullet_drift:
            findings.append(Finding("bullet-count-drift", f"tick {tick_label} baseline={baseline_bullets} case={case_bullets}"))
            saw_bullet_drift = True

        baseline_enemies = _entity_count(baseline_record, "enemies")
        case_enemies = _entity_count(case_record, "enemies")
        enemy_streak = enemy_streak + 1 if abs(baseline_enemies - case_enemies) >= enemy_drift_threshold else 0
        if enemy_streak >= sustained_window and not saw_enemy_drift:
            findings.append(Finding("enemy-count-drift", f"tick {tick_label} baseline={baseline_enemies} case={case_enemies}"))
            saw_enemy_drift = True

        baseline_lasers = _entity_count(baseline_record, "lasers")
        case_lasers = _entity_count(case_record, "lasers")
        laser_streak = laser_streak + 1 if abs(baseline_lasers - case_lasers) >= laser_drift_threshold else 0
        if laser_streak >= sustained_window and not saw_laser_drift:
            findings.append(Finding("laser-count-drift", f"tick {tick_label} baseline={baseline_lasers} case={case_lasers}"))
            saw_laser_drift = True

        baseline_score = baseline_record.get("score")
        case_score = case_record.get("score")
        if isinstance(baseline_score, int) and isinstance(case_score, int):
            score_streak = score_streak + 1 if abs(baseline_score - case_score) >= score_drift_threshold else 0
            if score_streak >= sustained_window and not saw_score_drift:
                findings.append(Finding("score-drift", f"tick {tick_label} baseline={baseline_score} case={case_score}"))
                saw_score_drift = True

        baseline_lives = baseline_record.get("lives")
        case_lives = case_record.get("lives")
        if isinstance(baseline_lives, int) and isinstance(case_lives, int) and baseline_lives != case_lives and not saw_life_drift:
            findings.append(Finding("life-drift", f"tick {tick_label} baseline={baseline_lives} case={case_lives}"))
            saw_life_drift = True

        baseline_bombs = baseline_record.get("bombs")
        case_bombs = case_record.get("bombs")
        if isinstance(baseline_bombs, int) and isinstance(case_bombs, int) and baseline_bombs != case_bombs and not saw_bomb_drift:
            findings.append(Finding("bomb-drift", f"tick {tick_label} baseline={baseline_bombs} case={case_bombs}"))
            saw_bomb_drift = True

    if len(case_records) + shortfall_threshold <= len(baseline_records):
        terminal_reason = case_records[-1].get("terminal_reason")
        if terminal_reason is None:
            findings.append(Finding("trace-shortfall", f"tick_count={len(case_records)} baseline_tick_count={len(baseline_records)}"))

    return findings
