from __future__ import annotations

from collections.abc import Iterator
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


def iter_trace_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            yield json.loads(line)


def load_trace_records(path: Path) -> list[dict[str, Any]]:
    return list(iter_trace_records(path))


def _entity_count(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
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


def _record_frame(record: dict[str, Any]) -> int | None:
    frame = record.get("frame")
    if not isinstance(frame, int):
        frame = record.get("game_frame")
    if isinstance(frame, int):
        return frame
    return None


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
STAGE_VM_DRIFT_FIELDS = (
    ("loaded", "stage_vm.loaded"),
    ("script_time", "stage_vm.script_time"),
    ("instruction_index", "stage_vm.instruction_index"),
    ("unpause_flag", "stage_vm.unpause_flag"),
    ("spellcard_state", "stage_vm.spellcard_state"),
    ("spellcard_ticks", "stage_vm.spellcard_ticks"),
)
ECL_TIMELINE_DRIFT_FIELDS = (
    ("time", "ecl_timeline.time"),
    ("next_time", "ecl_timeline.next_time"),
)
BOSS_UI_DRIFT_FIELDS = (
    ("present", "boss_ui.present"),
    ("ecl_lives", "boss_ui.ecl_lives"),
    ("spell_seconds", "boss_ui.spell_seconds"),
    ("opacity", "boss_ui.opacity"),
)
SPELLCARD_DRIFT_FIELDS = (
    ("active", "spellcard.active"),
    ("capturing", "spellcard.capturing"),
    ("used_bomb", "spellcard.used_bomb"),
    ("idx", "spellcard.idx"),
    ("capture_score", "spellcard.capture_score"),
)
BOSS_HEALTH_DRIFT_FIELDS = (
    ("health1", "boss_ui.health1"),
    ("health2", "boss_ui.health2"),
)
ANM_LOAD_DRIFT_FIELDS = (
    ("load_anm_calls", "anm_metrics.load_anm_calls"),
    ("load_anm_failures", "anm_metrics.load_anm_failures"),
    ("texture_load_failures", "anm_metrics.texture_load_failures"),
    ("alpha_texture_load_failures", "anm_metrics.alpha_texture_load_failures"),
    ("texture_size_mismatches", "anm_metrics.texture_size_mismatches"),
    ("sprites_loaded", "anm_metrics.sprites_loaded"),
    ("suspicious_sprites_loaded", "anm_metrics.suspicious_sprites_loaded"),
    ("scripts_loaded", "anm_metrics.scripts_loaded"),
    ("set_active_sprite_failures", "anm_metrics.set_active_sprite_failures"),
)
ANM_SCRIPT_DRIFT_FIELDS = (
    ("execute_script_calls", "anm_metrics.execute_script_calls"),
    ("script_instruction_steps", "anm_metrics.script_instruction_steps"),
    ("vm_non_finite", "anm_metrics.vm_non_finite"),
)
ANM_RENDER_DRIFT_FIELDS = (
    ("draw_calls", "anm_metrics.draw_calls"),
    ("draw_skipped_invisible", "anm_metrics.draw_skipped_invisible"),
    ("draw_skipped_flag1", "anm_metrics.draw_skipped_flag1"),
    ("draw_skipped_color_zero", "anm_metrics.draw_skipped_color_zero"),
    ("backend_draw_calls", "anm_metrics.backend_draw_calls"),
    ("flushes", "anm_metrics.flushes"),
    ("sprites_queued", "anm_metrics.sprites_queued"),
    ("suspicious_sprite_draws", "anm_metrics.suspicious_sprite_draws"),
)

ANM_STANDALONE_FINDINGS = (
    ("load_anm_failures", "anm-load-failure"),
    ("texture_load_failures", "anm-texture-load-failure"),
    ("alpha_texture_load_failures", "anm-alpha-texture-load-failure"),
    ("texture_size_mismatches", "anm-texture-size-mismatch"),
    ("set_active_sprite_failures", "anm-set-active-sprite-failure"),
    ("vm_non_finite", "anm-non-finite"),
    ("suspicious_sprites_loaded", "anm-suspicious-sprite"),
    ("suspicious_sprite_draws", "anm-suspicious-draw"),
)


def _walk_numbers(value: Any, findings: list[Finding], path: str = "$") -> None:
    stack: list[tuple[str, Any]] = [(path, value)]
    while stack:
        current_path, current = stack.pop()
        if isinstance(current, float):
            if not math.isfinite(current):
                findings.append(Finding("non-finite", f"{current_path}={current!r}"))
            continue
        if isinstance(current, dict):
            for key, nested in current.items():
                if isinstance(nested, float):
                    if not math.isfinite(nested):
                        findings.append(Finding("non-finite", f"{current_path}.{key}={nested!r}"))
                elif isinstance(nested, (dict, list)):
                    stack.append((f"{current_path}.{key}", nested))
            continue
        if isinstance(current, list):
            for index, nested in enumerate(current):
                if isinstance(nested, float):
                    if not math.isfinite(nested):
                        findings.append(Finding("non-finite", f"{current_path}[{index}]={nested!r}"))
                elif isinstance(nested, (dict, list)):
                    stack.append((f"{current_path}[{index}]", nested))


def _report_compact_entity_non_finite(record: dict[str, Any], findings: list[Finding]) -> None:
    metrics = record.get("entity_metrics")
    if not isinstance(metrics, dict):
        return
    for field_name in ("items_non_finite", "bullets_non_finite", "lasers_non_finite"):
        value = metrics.get(field_name)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            findings.append(Finding("non-finite", f"$.entity_metrics.{field_name}={value}"))


def _report_anm_runtime_findings(
    record: dict[str, Any],
    findings: list[Finding],
    *,
    baseline_record: dict[str, Any] | None = None,
    reported_kinds: set[str],
) -> None:
    metrics = record.get("anm_metrics")
    if not isinstance(metrics, dict):
        return
    baseline_metrics = baseline_record.get("anm_metrics") if isinstance(baseline_record, dict) else None
    for field_name, finding_kind in ANM_STANDALONE_FINDINGS:
        value = metrics.get(field_name)
        baseline_value = baseline_metrics.get(field_name) if isinstance(baseline_metrics, dict) else None
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > (
                baseline_value
                if isinstance(baseline_value, int) and not isinstance(baseline_value, bool)
                else 0
            )
            and finding_kind not in reported_kinds
        ):
            findings.append(Finding(finding_kind, f"$.anm_metrics.{field_name}={value}"))
            reported_kinds.add(finding_kind)


def _mapping_drift_detail(
    baseline_mapping: Any,
    case_mapping: Any,
    fields: tuple[tuple[str, str], ...],
    *,
    numeric_threshold: float | None = None,
) -> str | None:
    if not isinstance(baseline_mapping, dict) or not isinstance(case_mapping, dict):
        return None
    for field_name, label in fields:
        baseline_value = baseline_mapping.get(field_name)
        case_value = case_mapping.get(field_name)
        if baseline_value is None or case_value is None:
            continue
        if numeric_threshold is None:
            if baseline_value != case_value:
                return f"{label} baseline={baseline_value} case={case_value}"
            continue
        if (
            isinstance(baseline_value, (int, float))
            and not isinstance(baseline_value, bool)
            and isinstance(case_value, (int, float))
            and not isinstance(case_value, bool)
            and abs(float(baseline_value) - float(case_value)) >= numeric_threshold
        ):
            return f"{label} baseline={baseline_value} case={case_value}"
    return None


def _is_significant_bullet_count_drift(
    *,
    baseline_count: int,
    case_count: int,
    strong_threshold: int,
    collapse_anchor: int,
    collapse_divisor: int,
) -> bool:
    difference = abs(baseline_count - case_count)
    if difference >= strong_threshold:
        return True
    if collapse_divisor <= 0:
        raise ValueError("collapse_divisor must be positive")
    if baseline_count >= collapse_anchor and case_count <= baseline_count // collapse_divisor:
        return True
    return False


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


def first_stall_event_records(records: list[dict[str, Any]], *, stall_window: int = 240) -> StallEvent | None:
    last_frame: int | None = None
    repeated_frames = 0
    for record in records:
        frame = _record_frame(record)
        if frame is None:
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


def first_stall_event(path: Path, *, stall_window: int = 240) -> StallEvent | None:
    return first_stall_event_records(load_trace_records(path), stall_window=stall_window)


def score_trace_records(
    records: list[dict[str, Any]],
    *,
    stall_window: int = 240,
    bullet_limit: int = 1024,
    item_limit: int = 256,
) -> list[Finding]:
    findings: list[Finding] = []
    reported_anm_kinds: set[str] = set()
    stall: StallEvent | None = None
    last_frame: int | None = None
    repeated_frames = 0
    negative_timeline_next_reported = False
    for line_number, record in enumerate(records, start=1):
        frame = _record_frame(record)
        if frame is not None:
            if last_frame == frame:
                repeated_frames += 1
            else:
                repeated_frames = 0
            last_frame = frame
            if stall is None and repeated_frames >= stall_window:
                tick = record.get("tick")
                game_frame = record.get("game_frame")
                stall = StallEvent(
                    frame=frame,
                    tick=tick if isinstance(tick, int) else None,
                    game_frame=game_frame if isinstance(game_frame, int) else None,
                    detail=_stall_detail(record, frame=frame, stall_window=stall_window),
                )
        _walk_numbers(record, findings)
        _report_compact_entity_non_finite(record, findings)
        _report_anm_runtime_findings(record, findings, reported_kinds=reported_anm_kinds)
        timeline_next_finding = None
        if not negative_timeline_next_reported:
            timeline_next_finding = _timeline_next_time_finding(record, line_number=line_number)
        if timeline_next_finding is not None:
            findings.append(timeline_next_finding)
            negative_timeline_next_reported = True
        bullet_count = _entity_count(record, "bullets")
        if bullet_count > bullet_limit:
            findings.append(Finding("bullet-explosion", f"line {line_number} bullet_count={bullet_count}"))
        laser_count = _entity_count(record, "lasers")
        if laser_count > bullet_limit:
            findings.append(Finding("laser-explosion", f"line {line_number} laser_count={laser_count}"))
        enemy_count = _entity_count(record, "enemies")
        if enemy_count > 512:
            findings.append(Finding("enemy-explosion", f"line {line_number} enemy_count={enemy_count}"))
        item_count = _entity_count(record, "items")
        if item_count > item_limit:
            findings.append(Finding("item-explosion", f"line {line_number} item_count={item_count}"))
        terminal_reason = record.get("terminal_reason")
        if terminal_reason and terminal_reason not in {"physical-hit", "tick-limit", "input-error"}:
            findings.append(Finding("unexpected-terminal", str(terminal_reason)))
    if stall is not None:
        findings.append(Finding("stalled-progress", stall.detail))
        findings.append(Finding("stalled-frame", f"frame {stall.frame} repeated >= {stall_window} times"))
    return findings


def _should_keep_stall_findings(
    *,
    case_stall: StallEvent | None,
    baseline_stall: StallEvent | None,
    earlier_tick_margin: int,
    earlier_frame_margin: int,
) -> bool:
    if baseline_stall is None or case_stall is None:
        return True
    if (
        baseline_stall.tick is not None
        and case_stall.tick is not None
        and case_stall.tick + earlier_tick_margin < baseline_stall.tick
    ):
        return True
    if case_stall.frame + earlier_frame_margin < baseline_stall.frame:
        return True
    return False


def _terminal_reason_drift_finding(
    *,
    baseline_records: list[dict[str, Any]],
    case_last_record: dict[str, Any] | None,
) -> Finding | None:
    if not baseline_records or case_last_record is None:
        return None
    baseline_last_record = baseline_records[-1]
    baseline_reason = baseline_last_record.get("terminal_reason")
    case_reason = case_last_record.get("terminal_reason")
    if baseline_reason == case_reason:
        return None
    if baseline_reason is None and case_reason is None:
        return None
    baseline_tick = baseline_last_record.get("tick")
    case_tick = case_last_record.get("tick")
    return Finding(
        "terminal-reason-drift",
        " ".join(
            [
                f"baseline={baseline_reason}",
                f"case={case_reason}",
                f"baseline_tick={baseline_tick}",
                f"case_tick={case_tick}",
            ]
        ),
    )


def score_trace_path_with_baseline(
    path: Path,
    *,
    baseline_records: list[dict[str, Any]] | None = None,
    stall_window: int = 240,
    bullet_limit: int = 1024,
    item_limit: int = 256,
    sustained_window: int = 16,
    bullet_drift_threshold: int = 8,
    bullet_strong_drift_threshold: int = 64,
    bullet_collapse_anchor: int = 20,
    bullet_collapse_divisor: int = 3,
    enemy_drift_threshold: int = 2,
    laser_drift_threshold: int = 1,
    item_drift_threshold: int = 4,
    score_drift_threshold: int = 100,
    power_drift_threshold: int = 8,
    point_item_drift_threshold: int = 1,
    shortfall_threshold: int = 32,
    earlier_tick_margin: int = 32,
    earlier_frame_margin: int = 32,
) -> list[Finding]:
    standalone_findings: list[Finding] = []
    differential_findings: list[Finding] = []
    reported_anm_kinds: set[str] = set()
    case_stall: StallEvent | None = None
    last_frame: int | None = None
    repeated_frames = 0
    negative_timeline_next_reported = False

    baseline_length = len(baseline_records) if baseline_records is not None else 0
    baseline_stall = (
        first_stall_event_records(baseline_records, stall_window=stall_window)
        if baseline_records is not None
        else None
    )

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
    anm_load_streak = 0
    anm_script_streak = 0
    anm_render_streak = 0
    anm_load_streak = 0
    anm_script_streak = 0
    anm_render_streak = 0
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
    saw_anm_load_drift = False
    saw_anm_script_drift = False
    saw_anm_render_drift = False
    saw_life_drift = False
    saw_bomb_drift = False

    record_count = 0
    last_record: dict[str, Any] | None = None
    for line_number, case_record in enumerate(iter_trace_records(path), start=1):
        record_count = line_number
        last_record = case_record

        frame = _record_frame(case_record)
        if frame is not None:
            if last_frame == frame:
                repeated_frames += 1
            else:
                repeated_frames = 0
            last_frame = frame
            if case_stall is None and repeated_frames >= stall_window:
                tick = case_record.get("tick")
                game_frame = case_record.get("game_frame")
                case_stall = StallEvent(
                    frame=frame,
                    tick=tick if isinstance(tick, int) else None,
                    game_frame=game_frame if isinstance(game_frame, int) else None,
                    detail=_stall_detail(case_record, frame=frame, stall_window=stall_window),
                )

        _walk_numbers(case_record, standalone_findings)
        _report_compact_entity_non_finite(case_record, standalone_findings)
        baseline_record_for_standalone = (
            baseline_records[line_number - 1]
            if baseline_records is not None and line_number <= baseline_length
            else None
        )
        _report_anm_runtime_findings(
            case_record,
            standalone_findings,
            baseline_record=baseline_record_for_standalone,
            reported_kinds=reported_anm_kinds,
        )
        if not negative_timeline_next_reported:
            timeline_next_finding = _timeline_next_time_finding(case_record, line_number=line_number)
            if timeline_next_finding is not None:
                standalone_findings.append(timeline_next_finding)
                negative_timeline_next_reported = True
        bullet_count = _entity_count(case_record, "bullets")
        if bullet_count > bullet_limit:
            standalone_findings.append(Finding("bullet-explosion", f"line {line_number} bullet_count={bullet_count}"))
        laser_count = _entity_count(case_record, "lasers")
        if laser_count > bullet_limit:
            standalone_findings.append(Finding("laser-explosion", f"line {line_number} laser_count={laser_count}"))
        enemy_count = _entity_count(case_record, "enemies")
        if enemy_count > 512:
            standalone_findings.append(Finding("enemy-explosion", f"line {line_number} enemy_count={enemy_count}"))
        item_count = _entity_count(case_record, "items")
        if item_count > item_limit:
            standalone_findings.append(Finding("item-explosion", f"line {line_number} item_count={item_count}"))
        terminal_reason = case_record.get("terminal_reason")
        if terminal_reason and terminal_reason not in {"physical-hit", "tick-limit", "input-error"}:
            standalone_findings.append(Finding("unexpected-terminal", str(terminal_reason)))

        if baseline_records is None or line_number > baseline_length:
            continue
        baseline_record = baseline_records[line_number - 1]
        tick = case_record.get("tick")
        tick_label = tick if isinstance(tick, int) else line_number

        baseline_bullets = _entity_count(baseline_record, "bullets")
        case_bullets = _entity_count(case_record, "bullets")
        bullet_streak = bullet_streak + 1 if abs(baseline_bullets - case_bullets) >= bullet_drift_threshold else 0
        if (
            bullet_streak >= sustained_window
            and not saw_bullet_drift
            and _is_significant_bullet_count_drift(
                baseline_count=baseline_bullets,
                case_count=case_bullets,
                strong_threshold=bullet_strong_drift_threshold,
                collapse_anchor=bullet_collapse_anchor,
                collapse_divisor=bullet_collapse_divisor,
            )
        ):
            differential_findings.append(
                Finding("bullet-count-drift", f"tick {tick_label} baseline={baseline_bullets} case={case_bullets}")
            )
            saw_bullet_drift = True

        baseline_enemies = _entity_count(baseline_record, "enemies")
        case_enemies = _entity_count(case_record, "enemies")
        enemy_streak = enemy_streak + 1 if abs(baseline_enemies - case_enemies) >= enemy_drift_threshold else 0
        if enemy_streak >= sustained_window and not saw_enemy_drift:
            differential_findings.append(
                Finding("enemy-count-drift", f"tick {tick_label} baseline={baseline_enemies} case={case_enemies}")
            )
            saw_enemy_drift = True

        baseline_lasers = _entity_count(baseline_record, "lasers")
        case_lasers = _entity_count(case_record, "lasers")
        laser_streak = laser_streak + 1 if abs(baseline_lasers - case_lasers) >= laser_drift_threshold else 0
        if laser_streak >= sustained_window and not saw_laser_drift:
            differential_findings.append(
                Finding("laser-count-drift", f"tick {tick_label} baseline={baseline_lasers} case={case_lasers}")
            )
            saw_laser_drift = True

        baseline_items = _entity_count(baseline_record, "items")
        case_items = _entity_count(case_record, "items")
        item_streak = item_streak + 1 if abs(baseline_items - case_items) >= item_drift_threshold else 0
        if item_streak >= sustained_window and not saw_item_drift:
            differential_findings.append(
                Finding("item-count-drift", f"tick {tick_label} baseline={baseline_items} case={case_items}")
            )
            saw_item_drift = True

        baseline_score = baseline_record.get("score")
        case_score = case_record.get("score")
        if isinstance(baseline_score, int) and isinstance(case_score, int):
            score_streak = score_streak + 1 if abs(baseline_score - case_score) >= score_drift_threshold else 0
            if score_streak >= sustained_window and not saw_score_drift:
                differential_findings.append(
                    Finding("score-drift", f"tick {tick_label} baseline={baseline_score} case={case_score}")
                )
                saw_score_drift = True

        baseline_power = baseline_record.get("power")
        case_power = case_record.get("power")
        if isinstance(baseline_power, int) and isinstance(case_power, int):
            power_streak = power_streak + 1 if abs(baseline_power - case_power) >= power_drift_threshold else 0
            if power_streak >= sustained_window and not saw_power_drift:
                differential_findings.append(
                    Finding("power-drift", f"tick {tick_label} baseline={baseline_power} case={case_power}")
                )
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
                differential_findings.append(
                    Finding(
                        "point-item-drift",
                        f"tick {tick_label} baseline={baseline_point_items} case={case_point_items}",
                    )
                )
                saw_point_item_drift = True

        baseline_stage_vm = baseline_record.get("stage_vm")
        case_stage_vm = case_record.get("stage_vm")
        stage_vm_detail = _mapping_drift_detail(
            baseline_stage_vm,
            case_stage_vm,
            STAGE_VM_DRIFT_FIELDS,
        )
        stage_vm_streak = stage_vm_streak + 1 if stage_vm_detail is not None else 0
        if stage_vm_streak >= sustained_window and not saw_stage_vm_drift:
            differential_findings.append(Finding("stage-script-drift", f"tick {tick_label} {stage_vm_detail}"))
            saw_stage_vm_drift = True

        baseline_timeline = baseline_record.get("ecl_timeline")
        case_timeline = case_record.get("ecl_timeline")
        timeline_detail = _mapping_drift_detail(
            baseline_timeline,
            case_timeline,
            ECL_TIMELINE_DRIFT_FIELDS,
        )
        timeline_streak = timeline_streak + 1 if timeline_detail is not None else 0
        if timeline_streak >= sustained_window and not saw_timeline_drift:
            differential_findings.append(Finding("ecl-timeline-drift", f"tick {tick_label} {timeline_detail}"))
            saw_timeline_drift = True

        baseline_boss_ui = baseline_record.get("boss_ui")
        case_boss_ui = case_record.get("boss_ui")
        boss_ui_detail = _mapping_drift_detail(
            baseline_boss_ui,
            case_boss_ui,
            BOSS_UI_DRIFT_FIELDS,
        )
        boss_ui_streak = boss_ui_streak + 1 if boss_ui_detail is not None else 0
        if boss_ui_streak >= sustained_window and not saw_boss_ui_drift:
            differential_findings.append(Finding("boss-ui-drift", f"tick {tick_label} {boss_ui_detail}"))
            saw_boss_ui_drift = True

        baseline_spellcard = baseline_record.get("spellcard")
        case_spellcard = case_record.get("spellcard")
        spellcard_detail = _mapping_drift_detail(
            baseline_spellcard,
            case_spellcard,
            SPELLCARD_DRIFT_FIELDS,
        )
        spellcard_streak = spellcard_streak + 1 if spellcard_detail is not None else 0
        if spellcard_streak >= sustained_window and not saw_spellcard_drift:
            differential_findings.append(Finding("spellcard-drift", f"tick {tick_label} {spellcard_detail}"))
            saw_spellcard_drift = True

        boss_health_detail = _mapping_drift_detail(
            baseline_boss_ui,
            case_boss_ui,
            BOSS_HEALTH_DRIFT_FIELDS,
            numeric_threshold=0.01,
        )
        boss_health_streak = boss_health_streak + 1 if boss_health_detail is not None else 0
        if boss_health_streak >= sustained_window and not saw_boss_health_drift:
            differential_findings.append(Finding("boss-health-drift", f"tick {tick_label} {boss_health_detail}"))
            saw_boss_health_drift = True

        baseline_anm_metrics = baseline_record.get("anm_metrics")
        case_anm_metrics = case_record.get("anm_metrics")
        anm_load_detail = _mapping_drift_detail(
            baseline_anm_metrics,
            case_anm_metrics,
            ANM_LOAD_DRIFT_FIELDS,
        )
        anm_load_streak = anm_load_streak + 1 if anm_load_detail is not None else 0
        if anm_load_streak >= sustained_window and not saw_anm_load_drift:
            differential_findings.append(Finding("anm-load-drift", f"tick {tick_label} {anm_load_detail}"))
            saw_anm_load_drift = True

        anm_script_detail = _mapping_drift_detail(
            baseline_anm_metrics,
            case_anm_metrics,
            ANM_SCRIPT_DRIFT_FIELDS,
        )
        anm_script_streak = anm_script_streak + 1 if anm_script_detail is not None else 0
        if anm_script_streak >= sustained_window and not saw_anm_script_drift:
            differential_findings.append(Finding("anm-script-drift", f"tick {tick_label} {anm_script_detail}"))
            saw_anm_script_drift = True

        anm_render_detail = _mapping_drift_detail(
            baseline_anm_metrics,
            case_anm_metrics,
            ANM_RENDER_DRIFT_FIELDS,
        )
        anm_render_streak = anm_render_streak + 1 if anm_render_detail is not None else 0
        if anm_render_streak >= sustained_window and not saw_anm_render_drift:
            differential_findings.append(Finding("anm-render-drift", f"tick {tick_label} {anm_render_detail}"))
            saw_anm_render_drift = True

        baseline_lives = baseline_record.get("lives")
        case_lives = case_record.get("lives")
        if isinstance(baseline_lives, int) and isinstance(case_lives, int) and baseline_lives != case_lives and not saw_life_drift:
            differential_findings.append(Finding("life-drift", f"tick {tick_label} baseline={baseline_lives} case={case_lives}"))
            saw_life_drift = True

        baseline_bombs = baseline_record.get("bombs")
        case_bombs = case_record.get("bombs")
        if isinstance(baseline_bombs, int) and isinstance(case_bombs, int) and baseline_bombs != case_bombs and not saw_bomb_drift:
            differential_findings.append(Finding("bomb-drift", f"tick {tick_label} baseline={baseline_bombs} case={case_bombs}"))
            saw_bomb_drift = True

    if case_stall is not None and _should_keep_stall_findings(
        case_stall=case_stall,
        baseline_stall=baseline_stall,
        earlier_tick_margin=earlier_tick_margin,
        earlier_frame_margin=earlier_frame_margin,
    ):
        standalone_findings.append(Finding("stalled-progress", case_stall.detail))
        standalone_findings.append(Finding("stalled-frame", f"frame {case_stall.frame} repeated >= {stall_window} times"))

    if baseline_records is not None and record_count + shortfall_threshold <= baseline_length:
        terminal_reason = last_record.get("terminal_reason") if last_record is not None else None
        if terminal_reason is None:
            differential_findings.append(
                Finding("trace-shortfall", f"tick_count={record_count} baseline_tick_count={baseline_length}")
            )

    terminal_reason_drift = (
        _terminal_reason_drift_finding(
            baseline_records=baseline_records,
            case_last_record=last_record,
        )
        if baseline_records is not None
        else None
    )
    if terminal_reason_drift is not None:
        differential_findings.append(terminal_reason_drift)

    return standalone_findings + differential_findings


def score_trace(path: Path, *, stall_window: int = 240, bullet_limit: int = 1024, item_limit: int = 256) -> list[Finding]:
    return score_trace_records(
        load_trace_records(path),
        stall_window=stall_window,
        bullet_limit=bullet_limit,
        item_limit=item_limit,
    )


def suppress_baseline_stall_findings_records(
    case_findings: list[Finding],
    *,
    case_records: list[dict[str, Any]],
    baseline_records: list[dict[str, Any]],
    stall_window: int = 240,
    earlier_tick_margin: int = 32,
    earlier_frame_margin: int = 32,
) -> list[Finding]:
    baseline_stall = first_stall_event_records(baseline_records, stall_window=stall_window)
    case_stall = first_stall_event_records(case_records, stall_window=stall_window)
    if _should_keep_stall_findings(
        case_stall=case_stall,
        baseline_stall=baseline_stall,
        earlier_tick_margin=earlier_tick_margin,
        earlier_frame_margin=earlier_frame_margin,
    ):
        return list(case_findings)
    return [finding for finding in case_findings if finding.kind not in {"stalled-progress", "stalled-frame"}]


def suppress_baseline_stall_findings(
    case_findings: list[Finding],
    *,
    case_trace: Path,
    baseline_trace: Path,
    stall_window: int = 240,
    earlier_tick_margin: int = 32,
    earlier_frame_margin: int = 32,
) -> list[Finding]:
    return suppress_baseline_stall_findings_records(
        case_findings,
        case_records=load_trace_records(case_trace),
        baseline_records=load_trace_records(baseline_trace),
        stall_window=stall_window,
        earlier_tick_margin=earlier_tick_margin,
        earlier_frame_margin=earlier_frame_margin,
    )


def score_trace_differential_records(
    case_records: list[dict[str, Any]],
    baseline_records: list[dict[str, Any]],
    *,
    sustained_window: int = 16,
    bullet_drift_threshold: int = 8,
    bullet_strong_drift_threshold: int = 64,
    bullet_collapse_anchor: int = 20,
    bullet_collapse_divisor: int = 3,
    enemy_drift_threshold: int = 2,
    laser_drift_threshold: int = 1,
    item_drift_threshold: int = 4,
    score_drift_threshold: int = 100,
    power_drift_threshold: int = 8,
    point_item_drift_threshold: int = 1,
    shortfall_threshold: int = 32,
) -> list[Finding]:
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
    saw_anm_load_drift = False
    saw_anm_script_drift = False
    saw_anm_render_drift = False
    saw_life_drift = False
    saw_bomb_drift = False

    for line_number, (baseline_record, case_record) in enumerate(zip(baseline_records, case_records), start=1):
        tick = case_record.get("tick")
        tick_label = tick if isinstance(tick, int) else line_number

        baseline_bullets = _entity_count(baseline_record, "bullets")
        case_bullets = _entity_count(case_record, "bullets")
        bullet_streak = bullet_streak + 1 if abs(baseline_bullets - case_bullets) >= bullet_drift_threshold else 0
        if (
            bullet_streak >= sustained_window
            and not saw_bullet_drift
            and _is_significant_bullet_count_drift(
                baseline_count=baseline_bullets,
                case_count=case_bullets,
                strong_threshold=bullet_strong_drift_threshold,
                collapse_anchor=bullet_collapse_anchor,
                collapse_divisor=bullet_collapse_divisor,
            )
        ):
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

        baseline_stage_vm = baseline_record.get("stage_vm")
        case_stage_vm = case_record.get("stage_vm")
        stage_vm_detail = _mapping_drift_detail(
            baseline_stage_vm,
            case_stage_vm,
            STAGE_VM_DRIFT_FIELDS,
        )
        stage_vm_streak = stage_vm_streak + 1 if stage_vm_detail is not None else 0
        if stage_vm_streak >= sustained_window and not saw_stage_vm_drift:
            findings.append(Finding("stage-script-drift", f"tick {tick_label} {stage_vm_detail}"))
            saw_stage_vm_drift = True

        baseline_timeline = baseline_record.get("ecl_timeline")
        case_timeline = case_record.get("ecl_timeline")
        timeline_detail = _mapping_drift_detail(
            baseline_timeline,
            case_timeline,
            ECL_TIMELINE_DRIFT_FIELDS,
        )
        timeline_streak = timeline_streak + 1 if timeline_detail is not None else 0
        if timeline_streak >= sustained_window and not saw_timeline_drift:
            findings.append(Finding("ecl-timeline-drift", f"tick {tick_label} {timeline_detail}"))
            saw_timeline_drift = True

        baseline_boss_ui = baseline_record.get("boss_ui")
        case_boss_ui = case_record.get("boss_ui")
        boss_ui_detail = _mapping_drift_detail(
            baseline_boss_ui,
            case_boss_ui,
            BOSS_UI_DRIFT_FIELDS,
        )
        boss_ui_streak = boss_ui_streak + 1 if boss_ui_detail is not None else 0
        if boss_ui_streak >= sustained_window and not saw_boss_ui_drift:
            findings.append(Finding("boss-ui-drift", f"tick {tick_label} {boss_ui_detail}"))
            saw_boss_ui_drift = True

        baseline_spellcard = baseline_record.get("spellcard")
        case_spellcard = case_record.get("spellcard")
        spellcard_detail = _mapping_drift_detail(
            baseline_spellcard,
            case_spellcard,
            SPELLCARD_DRIFT_FIELDS,
        )
        spellcard_streak = spellcard_streak + 1 if spellcard_detail is not None else 0
        if spellcard_streak >= sustained_window and not saw_spellcard_drift:
            findings.append(Finding("spellcard-drift", f"tick {tick_label} {spellcard_detail}"))
            saw_spellcard_drift = True

        boss_health_detail = _mapping_drift_detail(
            baseline_boss_ui,
            case_boss_ui,
            BOSS_HEALTH_DRIFT_FIELDS,
            numeric_threshold=0.01,
        )
        boss_health_streak = boss_health_streak + 1 if boss_health_detail is not None else 0
        if boss_health_streak >= sustained_window and not saw_boss_health_drift:
            findings.append(Finding("boss-health-drift", f"tick {tick_label} {boss_health_detail}"))
            saw_boss_health_drift = True

        baseline_anm_metrics = baseline_record.get("anm_metrics")
        case_anm_metrics = case_record.get("anm_metrics")
        anm_load_detail = _mapping_drift_detail(
            baseline_anm_metrics,
            case_anm_metrics,
            ANM_LOAD_DRIFT_FIELDS,
        )
        anm_load_streak = anm_load_streak + 1 if anm_load_detail is not None else 0
        if anm_load_streak >= sustained_window and not saw_anm_load_drift:
            findings.append(Finding("anm-load-drift", f"tick {tick_label} {anm_load_detail}"))
            saw_anm_load_drift = True

        anm_script_detail = _mapping_drift_detail(
            baseline_anm_metrics,
            case_anm_metrics,
            ANM_SCRIPT_DRIFT_FIELDS,
        )
        anm_script_streak = anm_script_streak + 1 if anm_script_detail is not None else 0
        if anm_script_streak >= sustained_window and not saw_anm_script_drift:
            findings.append(Finding("anm-script-drift", f"tick {tick_label} {anm_script_detail}"))
            saw_anm_script_drift = True

        anm_render_detail = _mapping_drift_detail(
            baseline_anm_metrics,
            case_anm_metrics,
            ANM_RENDER_DRIFT_FIELDS,
        )
        anm_render_streak = anm_render_streak + 1 if anm_render_detail is not None else 0
        if anm_render_streak >= sustained_window and not saw_anm_render_drift:
            findings.append(Finding("anm-render-drift", f"tick {tick_label} {anm_render_detail}"))
            saw_anm_render_drift = True

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

    terminal_reason_drift = _terminal_reason_drift_finding(
        baseline_records=baseline_records,
        case_last_record=case_records[-1] if case_records else None,
    )
    if terminal_reason_drift is not None:
        findings.append(terminal_reason_drift)

    return findings


def score_trace_differential(
    path: Path,
    baseline_path: Path,
    *,
    sustained_window: int = 16,
    bullet_drift_threshold: int = 8,
    bullet_strong_drift_threshold: int = 64,
    bullet_collapse_anchor: int = 20,
    bullet_collapse_divisor: int = 3,
    enemy_drift_threshold: int = 2,
    laser_drift_threshold: int = 1,
    item_drift_threshold: int = 4,
    score_drift_threshold: int = 100,
    power_drift_threshold: int = 8,
    point_item_drift_threshold: int = 1,
    shortfall_threshold: int = 32,
) -> list[Finding]:
    return score_trace_differential_records(
        load_trace_records(path),
        load_trace_records(baseline_path),
        sustained_window=sustained_window,
        bullet_drift_threshold=bullet_drift_threshold,
        bullet_strong_drift_threshold=bullet_strong_drift_threshold,
        bullet_collapse_anchor=bullet_collapse_anchor,
        bullet_collapse_divisor=bullet_collapse_divisor,
        enemy_drift_threshold=enemy_drift_threshold,
        laser_drift_threshold=laser_drift_threshold,
        item_drift_threshold=item_drift_threshold,
        score_drift_threshold=score_drift_threshold,
        power_drift_threshold=power_drift_threshold,
        point_item_drift_threshold=point_item_drift_threshold,
        shortfall_threshold=shortfall_threshold,
    )
