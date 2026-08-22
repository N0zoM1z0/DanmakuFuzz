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


@dataclass(frozen=True)
class StallEvent:
    frame: int
    tick: int | None
    game_frame: int | None
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


def _nested_value(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for component in path:
        if not isinstance(value, dict):
            return None
        value = value.get(component)
    return value


def _path_label(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _timeline_next_time_finding(record: dict[str, Any], *, line_number: int) -> Finding | None:
    timeline = record.get("ecl_timeline")
    if not isinstance(timeline, dict):
        return None
    next_time = timeline.get("next_time")
    if not isinstance(next_time, int):
        return None
    if next_time >= -1:
        return None
    tick = record.get("tick")
    game_frame = record.get("game_frame")
    timeline_time = timeline.get("time")
    detail = [f"line {line_number}", f"ecl_timeline.next_time={next_time}"]
    if isinstance(tick, int):
        detail.append(f"tick={tick}")
    if isinstance(game_frame, int):
        detail.append(f"game_frame={game_frame}")
    if isinstance(timeline_time, int):
        detail.append(f"ecl_timeline.time={timeline_time}")
    return Finding("timeline-next-time-negative", " ".join(detail))


def _scalar_drift_detail(
    baseline_record: dict[str, Any],
    case_record: dict[str, Any],
    paths: tuple[tuple[str, ...], ...],
    *,
    numeric_threshold: float | None = None,
) -> str | None:
    for path in paths:
        baseline_value = _nested_value(baseline_record, path)
        case_value = _nested_value(case_record, path)
        if baseline_value is None or case_value is None:
            continue
        if numeric_threshold is None:
            if baseline_value != case_value:
                return f"{_path_label(path)} baseline={baseline_value} case={case_value}"
            continue
        if (
            isinstance(baseline_value, (int, float))
            and not isinstance(baseline_value, bool)
            and isinstance(case_value, (int, float))
            and not isinstance(case_value, bool)
            and abs(float(baseline_value) - float(case_value)) >= numeric_threshold
        ):
            return f"{_path_label(path)} baseline={baseline_value} case={case_value}"
    return None


STAGE_VM_DRIFT_PATHS = (
    ("stage_vm", "loaded"),
    ("stage_vm", "script_time"),
    ("stage_vm", "instruction_index"),
    ("stage_vm", "unpause_flag"),
    ("stage_vm", "spellcard_state"),
    ("stage_vm", "spellcard_ticks"),
)
ECL_TIMELINE_DRIFT_PATHS = (
    ("ecl_timeline", "time"),
    ("ecl_timeline", "next_time"),
)
BOSS_UI_DRIFT_PATHS = (
    ("boss_ui", "present"),
    ("boss_ui", "ecl_lives"),
    ("boss_ui", "spell_seconds"),
    ("boss_ui", "opacity"),
)
SPELLCARD_DRIFT_PATHS = (
    ("spellcard", "active"),
    ("spellcard", "capturing"),
    ("spellcard", "used_bomb"),
    ("spellcard", "idx"),
    ("spellcard", "capture_score"),
)
BOSS_HEALTH_DRIFT_PATHS = (
    ("boss_ui", "health1"),
    ("boss_ui", "health2"),
)


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


def _stall_detail(record: dict[str, Any], *, frame: int, stall_window: int) -> str:
    fields = [f"frame={frame}", f"window>={stall_window}"]
    tick = record.get("tick")
    if isinstance(tick, int):
        fields.append(f"tick={tick}")
    game_frame = record.get("game_frame")
    if isinstance(game_frame, int):
        fields.append(f"game_frame={game_frame}")
    rng_generation = record.get("rng_generation")
    if isinstance(rng_generation, int):
        fields.append(f"rng_generation={rng_generation}")
    for path in (
        ("stage_vm", "loaded"),
        ("stage_vm", "script_time"),
        ("stage_vm", "instruction_index"),
        ("ecl_timeline", "time"),
        ("ecl_timeline", "next_time"),
    ):
        value = _nested_value(record, path)
        if value is None:
            continue
        fields.append(f"{_path_label(path)}={value}")
    return " ".join(fields)


def first_stall_event(path: Path, *, stall_window: int = 240) -> StallEvent | None:
    last_frame: int | None = None
    repeated_frames = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            frame = record.get("frame")
            if not isinstance(frame, int):
                frame = record.get("game_frame")
            if not isinstance(frame, int):
                continue
            if last_frame == frame:
                repeated_frames += 1
            else:
                repeated_frames = 0
            last_frame = frame
            if repeated_frames >= stall_window:
                tick = record.get("tick")
                game_frame = record.get("game_frame")
                return StallEvent(
                    frame=frame,
                    tick=tick if isinstance(tick, int) else None,
                    game_frame=game_frame if isinstance(game_frame, int) else None,
                    detail=_stall_detail(record, frame=frame, stall_window=stall_window),
                )
    return None


def score_trace(path: Path, *, stall_window: int = 240, bullet_limit: int = 1024, item_limit: int = 256) -> list[Finding]:
    findings: list[Finding] = []
    stall = first_stall_event(path, stall_window=stall_window)
    negative_timeline_next_reported = False
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            _walk_numbers(record, findings)
            timeline_next_finding = None
            if not negative_timeline_next_reported:
                timeline_next_finding = _timeline_next_time_finding(record, line_number=line_number)
            if timeline_next_finding is not None:
                findings.append(timeline_next_finding)
                negative_timeline_next_reported = True
            bullets = record.get("bullets")
            if isinstance(bullets, list) and len(bullets) > bullet_limit:
                findings.append(Finding("bullet-explosion", f"line {line_number} bullet_count={len(bullets)}"))
            lasers = record.get("lasers")
            if isinstance(lasers, list) and len(lasers) > bullet_limit:
                findings.append(Finding("laser-explosion", f"line {line_number} laser_count={len(lasers)}"))
            enemies = record.get("enemies")
            if isinstance(enemies, list) and len(enemies) > 512:
                findings.append(Finding("enemy-explosion", f"line {line_number} enemy_count={len(enemies)}"))
            items = record.get("items")
            if isinstance(items, list) and len(items) > item_limit:
                findings.append(Finding("item-explosion", f"line {line_number} item_count={len(items)}"))
            terminal_reason = record.get("terminal_reason")
            if terminal_reason and terminal_reason not in {"physical-hit", "tick-limit", "input-error"}:
                findings.append(Finding("unexpected-terminal", str(terminal_reason)))
    if stall is not None:
        findings.append(Finding("stalled-progress", stall.detail))
        findings.append(Finding("stalled-frame", f"frame {stall.frame} repeated >= {stall_window} times"))
    return findings


def suppress_baseline_stall_findings(
    case_findings: list[Finding],
    *,
    case_trace: Path,
    baseline_trace: Path,
    stall_window: int = 240,
    earlier_tick_margin: int = 32,
    earlier_frame_margin: int = 32,
) -> list[Finding]:
    baseline_stall = first_stall_event(baseline_trace, stall_window=stall_window)
    case_stall = first_stall_event(case_trace, stall_window=stall_window)
    if baseline_stall is None or case_stall is None:
        return list(case_findings)

    if (
        baseline_stall.tick is not None
        and case_stall.tick is not None
        and case_stall.tick + earlier_tick_margin < baseline_stall.tick
    ):
        return list(case_findings)
    if case_stall.frame + earlier_frame_margin < baseline_stall.frame:
        return list(case_findings)
    return [finding for finding in case_findings if finding.kind not in {"stalled-progress", "stalled-frame"}]


def score_trace_differential(
    path: Path,
    baseline_path: Path,
    *,
    sustained_window: int = 16,
    bullet_drift_threshold: int = 8,
    enemy_drift_threshold: int = 2,
    laser_drift_threshold: int = 1,
    item_drift_threshold: int = 4,
    score_drift_threshold: int = 100,
    power_drift_threshold: int = 8,
    point_item_drift_threshold: int = 1,
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
    item_streak = 0
    score_streak = 0
    power_streak = 0
    point_item_streak = 0
    stage_vm_streak = 0
    timeline_streak = 0
    boss_ui_streak = 0
    spellcard_streak = 0
    boss_health_streak = 0
    saw_bullet_drift = False
    saw_enemy_drift = False
    saw_laser_drift = False
    saw_item_drift = False
    saw_score_drift = False
    saw_power_drift = False
    saw_point_item_drift = False
    saw_stage_vm_drift = False
    saw_timeline_drift = False
    saw_boss_ui_drift = False
    saw_spellcard_drift = False
    saw_boss_health_drift = False
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

        baseline_items = _entity_count(baseline_record, "items")
        case_items = _entity_count(case_record, "items")
        item_streak = item_streak + 1 if abs(baseline_items - case_items) >= item_drift_threshold else 0
        if item_streak >= sustained_window and not saw_item_drift:
            findings.append(Finding("item-count-drift", f"tick {tick_label} baseline={baseline_items} case={case_items}"))
            saw_item_drift = True

        baseline_score = baseline_record.get("score")
        case_score = case_record.get("score")
        if isinstance(baseline_score, int) and isinstance(case_score, int):
            score_streak = score_streak + 1 if abs(baseline_score - case_score) >= score_drift_threshold else 0
            if score_streak >= sustained_window and not saw_score_drift:
                findings.append(Finding("score-drift", f"tick {tick_label} baseline={baseline_score} case={case_score}"))
                saw_score_drift = True

        baseline_power = baseline_record.get("power")
        case_power = case_record.get("power")
        if isinstance(baseline_power, int) and isinstance(case_power, int):
            power_streak = power_streak + 1 if abs(baseline_power - case_power) >= power_drift_threshold else 0
            if power_streak >= sustained_window and not saw_power_drift:
                findings.append(Finding("power-drift", f"tick {tick_label} baseline={baseline_power} case={case_power}"))
                saw_power_drift = True

        baseline_point_items = baseline_record.get("point_items_stage")
        case_point_items = case_record.get("point_items_stage")
        if isinstance(baseline_point_items, int) and isinstance(case_point_items, int):
            point_item_streak = (
                point_item_streak + 1
                if abs(baseline_point_items - case_point_items) >= point_item_drift_threshold
                else 0
            )
            if point_item_streak >= sustained_window and not saw_point_item_drift:
                findings.append(
                    Finding(
                        "point-item-drift",
                        f"tick {tick_label} baseline={baseline_point_items} case={case_point_items}",
                    )
                )
                saw_point_item_drift = True

        stage_vm_detail = _scalar_drift_detail(baseline_record, case_record, STAGE_VM_DRIFT_PATHS)
        stage_vm_streak = stage_vm_streak + 1 if stage_vm_detail is not None else 0
        if stage_vm_streak >= sustained_window and not saw_stage_vm_drift:
            findings.append(Finding("stage-script-drift", f"tick {tick_label} {stage_vm_detail}"))
            saw_stage_vm_drift = True

        timeline_detail = _scalar_drift_detail(baseline_record, case_record, ECL_TIMELINE_DRIFT_PATHS)
        timeline_streak = timeline_streak + 1 if timeline_detail is not None else 0
        if timeline_streak >= sustained_window and not saw_timeline_drift:
            findings.append(Finding("ecl-timeline-drift", f"tick {tick_label} {timeline_detail}"))
            saw_timeline_drift = True

        boss_ui_detail = _scalar_drift_detail(baseline_record, case_record, BOSS_UI_DRIFT_PATHS)
        boss_ui_streak = boss_ui_streak + 1 if boss_ui_detail is not None else 0
        if boss_ui_streak >= sustained_window and not saw_boss_ui_drift:
            findings.append(Finding("boss-ui-drift", f"tick {tick_label} {boss_ui_detail}"))
            saw_boss_ui_drift = True

        spellcard_detail = _scalar_drift_detail(baseline_record, case_record, SPELLCARD_DRIFT_PATHS)
        spellcard_streak = spellcard_streak + 1 if spellcard_detail is not None else 0
        if spellcard_streak >= sustained_window and not saw_spellcard_drift:
            findings.append(Finding("spellcard-drift", f"tick {tick_label} {spellcard_detail}"))
            saw_spellcard_drift = True

        boss_health_detail = _scalar_drift_detail(
            baseline_record,
            case_record,
            BOSS_HEALTH_DRIFT_PATHS,
            numeric_threshold=0.01,
        )
        boss_health_streak = boss_health_streak + 1 if boss_health_detail is not None else 0
        if boss_health_streak >= sustained_window and not saw_boss_health_drift:
            findings.append(Finding("boss-health-drift", f"tick {tick_label} {boss_health_detail}"))
            saw_boss_health_drift = True

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
