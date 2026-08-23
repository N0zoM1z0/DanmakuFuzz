from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ..ecl_ir.parser import parse_ecl
from ..ecl_ir.serializer import serialize_ecl
from ..headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from ..headless.prepare_worker_game_dir import prepare_worker_game_dir
from ..repo import ARTIFACTS_DIR, ensure_directory
from .ecl_campaign import LONG_ACTION_FILE, run_case
from .payload_mutants import PayloadMutant


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-site-basins" / stamp


def _load_trace(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"trace row must be an object: {path}")
            rows.append(value)
    return rows


def _trace_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _entity_count(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _tail_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("trace is empty")
    last_record = rows[-1]
    stage_vm = last_record.get("stage_vm")
    ecl_timeline = last_record.get("ecl_timeline")
    return {
        "tick": last_record.get("tick"),
        "game_frame": last_record.get("game_frame"),
        "score": last_record.get("score"),
        "lives": last_record.get("lives"),
        "bombs": last_record.get("bombs"),
        "power": last_record.get("power"),
        "enemy_count": last_record.get("enemy_count"),
        "item_count": _entity_count(last_record, "items"),
        "bullet_count": _entity_count(last_record, "bullets"),
        "stage_vm": {
            "loaded": stage_vm.get("loaded") if isinstance(stage_vm, dict) else None,
            "script_time": stage_vm.get("script_time") if isinstance(stage_vm, dict) else None,
            "instruction_index": stage_vm.get("instruction_index") if isinstance(stage_vm, dict) else None,
        },
        "ecl_timeline": {
            "time": ecl_timeline.get("time") if isinstance(ecl_timeline, dict) else None,
            "next_time": ecl_timeline.get("next_time") if isinstance(ecl_timeline, dict) else None,
        },
        "terminal_reason": last_record.get("terminal_reason"),
    }


def _freeze_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("trace is empty")
    last_record = rows[-1]
    frozen_frame = last_record.get("game_frame")
    first_index = len(rows) - 1
    while first_index > 0 and rows[first_index - 1].get("game_frame") == frozen_frame:
        first_index -= 1
    first_record = rows[first_index]
    return {
        "frozen_frame": frozen_frame,
        "first_frozen_tick": first_record.get("tick"),
        "last_tick": last_record.get("tick"),
        "frozen_ticks": len(rows) - first_index,
    }


def _first_diff(
    baseline_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, Any] | None:
    for baseline_row, case_row in zip(baseline_rows, case_rows):
        if baseline_row.get(key) != case_row.get(key):
            return {
                "tick": case_row.get("tick"),
                "baseline": baseline_row.get(key),
                "case": case_row.get(key),
            }
    return None


def _scheduler_snapshot(
    *,
    freeze_summary: dict[str, Any],
    first_stage_vm_diff: dict[str, Any] | None,
    first_timeline_diff: dict[str, Any] | None,
    tail: dict[str, Any],
) -> dict[str, Any]:
    return {
        "freeze_summary": freeze_summary,
        "first_stage_vm_diff_tick": first_stage_vm_diff.get("tick") if isinstance(first_stage_vm_diff, dict) else None,
        "first_timeline_diff_tick": first_timeline_diff.get("tick") if isinstance(first_timeline_diff, dict) else None,
        "tail": {
            "game_frame": tail.get("game_frame"),
            "stage_vm": tail.get("stage_vm"),
            "ecl_timeline": tail.get("ecl_timeline"),
            "terminal_reason": tail.get("terminal_reason"),
        },
    }


def _signature(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ordered_findings(findings: object) -> list[dict[str, str]]:
    if not isinstance(findings, list):
        return []
    ordered: list[dict[str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        detail = item.get("detail")
        if not isinstance(kind, str):
            continue
        row: dict[str, str] = {"kind": kind}
        if isinstance(detail, str):
            row["detail"] = detail
        ordered.append(row)
    return ordered


def _load_values_from_file(path: Path) -> list[int]:
    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        return []
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        tokens = [token for token in re.split(r"[\s,]+", stripped) if token]
        return [int(token, 0) for token in tokens]
    if isinstance(value, list):
        return [int(item) for item in value]
    raise ValueError(f"site basin mapper values file must be a JSON list or token list: {path}")


def _dedupe_preserve_order(values: list[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _exact_mutant(
    *,
    seed_payload: bytes,
    sub_index: int,
    instruction_index: int,
    field_offset: int,
    value: int,
    family: str,
    field_name: str,
    expected_opcode: int | None,
    expected_original_value: int | None,
) -> tuple[PayloadMutant, dict[str, Any]]:
    ecl = parse_ecl(seed_payload)
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if expected_opcode is not None and instruction.opcode != expected_opcode:
        raise RuntimeError(
            f"opcode drifted at ({sub_index}, {instruction_index}): expected {expected_opcode}, got {instruction.opcode}"
        )
    if field_offset == -1:
        if field_name != "time":
            raise RuntimeError(
                f"field offset -1 only supports instruction.time, got field_name={field_name!r} "
                f"at ({sub_index}, {instruction_index})"
            )
        original_value = int(instruction.time)
        if expected_original_value is not None and original_value != expected_original_value:
            raise RuntimeError(
                f"original time drifted at ({sub_index}, {instruction_index}): "
                f"expected {expected_original_value}, got {original_value}"
            )
        instruction.time = int(value)
    elif field_offset < 0 or field_offset + 4 > len(instruction.args):
        raise RuntimeError(
            f"field offset {field_offset} is outside instruction args length {len(instruction.args)} "
            f"at ({sub_index}, {instruction_index})"
        )
        original_value = int.from_bytes(instruction.args[field_offset:field_offset + 4], "little", signed=True)
        if expected_original_value is not None and original_value != expected_original_value:
            raise RuntimeError(
                f"original value drifted at ({sub_index}, {instruction_index}) offset {field_offset}: "
                f"expected {expected_original_value}, got {original_value}"
            )
        instruction.args = (
            instruction.args[:field_offset]
            + int(value).to_bytes(4, "little", signed=True)
            + instruction.args[field_offset + 4:]
        )
    payload = serialize_ecl(ecl)
    mutant = PayloadMutant(
        name=f"{family}-exact-{value}",
        payload=payload,
        source="ir-exact-site-basin",
        path=(sub_index, instruction_index),
        metadata={
            "family": family,
            "field_name": field_name,
            "field_offset": field_offset,
            "value": value,
            "original_value": original_value,
            "strategy": "exact-i32",
        },
    )
    target = {
        "opcode": instruction.opcode,
        "original_value": original_value,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }
    return mutant, target


def _group_by_trace(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        groups[str(case["trace_sha256"])].append(case)
    rows: list[dict[str, Any]] = []
    for trace_sha256, members in groups.items():
        members.sort(key=lambda row: int(row["value"]))
        rows.append(
            {
                "trace_sha256": trace_sha256,
                "cases": len(members),
                "interesting_cases": sum(1 for row in members if bool(row["interesting"])),
                "values": [int(row["value"]) for row in members],
                "scheduler_signatures": dict(
                    Counter(str(row["scheduler_signature"]) for row in members).most_common()
                ),
                "representative_result": members[0]["result"],
                "representative_tail": members[0]["tail"],
                "representative_findings": members[0]["findings"],
            }
        )
    rows.sort(key=lambda row: (-int(row["cases"]), str(row["trace_sha256"])))
    return rows


def _group_by_scheduler(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        groups[str(case["scheduler_signature"])].append(case)
    rows: list[dict[str, Any]] = []
    for scheduler_signature, members in groups.items():
        members.sort(key=lambda row: int(row["value"]))
        rows.append(
            {
                "scheduler_signature": scheduler_signature,
                "cases": len(members),
                "interesting_cases": sum(1 for row in members if bool(row["interesting"])),
                "values": [int(row["value"]) for row in members],
                "trace_sha256s": dict(Counter(str(row["trace_sha256"]) for row in members).most_common()),
                "representative_result": members[0]["result"],
                "snapshot": members[0]["scheduler_snapshot"],
                "representative_tail": members[0]["tail"],
                "representative_findings": members[0]["findings"],
            }
        )
    rows.sort(key=lambda row: (-int(row["cases"]), str(row["scheduler_signature"])))
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run exact i32 mutations for one ECL site and group the outcomes into trace and scheduler basins."
    )
    parser.add_argument("--seed-ecl", type=Path, required=True)
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--sub-index", type=int, required=True)
    parser.add_argument("--instruction-index", type=int, required=True)
    parser.add_argument("--field-offset", type=int, required=True)
    parser.add_argument("--family", type=str, required=True)
    parser.add_argument("--field-name", type=str, required=True)
    parser.add_argument("--expected-opcode", type=int)
    parser.add_argument("--expected-original-value", type=int)
    parser.add_argument("--value", dest="values", action="append", type=int, default=[])
    parser.add_argument("--values-file", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--action-file", type=Path, default=LONG_ACTION_FILE)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--max-ticks", type=int, default=1800)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", dest="continue_after_hit", action="store_true")
    parser.add_argument("--no-continue-after-hit", dest="continue_after_hit", action="store_false")
    parser.set_defaults(continue_after_hit=True)
    parser.add_argument("--no-reuse-worker-game-dir", action="store_true")
    return parser.parse_args()


def map_site_basins(
    *,
    seed_ecl: Path,
    stage: int,
    sub_index: int,
    instruction_index: int,
    field_offset: int,
    family: str,
    field_name: str,
    values: list[int],
    artifact_dir: Path,
    headless_bin: Path,
    game_dir: Path,
    action_file: Path,
    seed: int,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    timeout_seconds: float,
    auto_shoot: bool,
    continue_after_hit: bool,
    reuse_worker_game_dir: bool,
    expected_opcode: int | None = None,
    expected_original_value: int | None = None,
) -> dict[str, Any]:
    values = _dedupe_preserve_order(values)
    if not values:
        raise RuntimeError("site basin mapper requires at least one --value or a non-empty --values-file")

    seed_ecl = seed_ecl.resolve()
    if not seed_ecl.is_file():
        raise FileNotFoundError(f"missing seed ecl: {seed_ecl}")

    artifact_dir = artifact_dir.resolve()
    ensure_directory(artifact_dir)
    headless_bin = headless_bin.resolve()
    game_dir = game_dir.resolve()
    action_file = action_file.resolve()
    seed_payload = seed_ecl.read_bytes()

    first_mutant, first_target = _exact_mutant(
        seed_payload=seed_payload,
        sub_index=sub_index,
        instruction_index=instruction_index,
        field_offset=field_offset,
        value=values[0],
        family=family,
        field_name=field_name,
        expected_opcode=expected_opcode,
        expected_original_value=expected_original_value,
    )
    original_value = int(first_target["original_value"])
    opcode = int(first_target["opcode"])

    baseline_worker_game_dir = artifact_dir / "worker-baseline"
    baseline_worker_prepare = prepare_worker_game_dir(
        source_game_dir=game_dir,
        destination=baseline_worker_game_dir,
        worker_name=f"site-basin-baseline-s{stage}-{sub_index}-{instruction_index}",
        reuse=reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=headless_bin,
        game_dir=baseline_worker_game_dir.resolve(),
        resource_override_dir=None,
        stage=stage,
        seed=seed,
        action_file=action_file,
        artifact_dir=baseline_dir.resolve(),
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_rows = _load_trace(baseline_trace)
    baseline_tail = _tail_summary(baseline_rows)

    cases: list[dict[str, Any]] = []
    first_mutant_metadata = None
    for case_index, value in enumerate(values, start=1):
        mutant, target = _exact_mutant(
            seed_payload=seed_payload,
            sub_index=sub_index,
            instruction_index=instruction_index,
            field_offset=field_offset,
            value=value,
            family=family,
            field_name=field_name,
            expected_opcode=expected_opcode,
            expected_original_value=expected_original_value,
        )
        if first_mutant_metadata is None:
            first_mutant_metadata = dict(mutant.metadata)
        case_worker_game_dir = artifact_dir / f"worker-{case_index:02d}"
        case_worker_prepare = prepare_worker_game_dir(
            source_game_dir=game_dir,
            destination=case_worker_game_dir,
            worker_name=f"site-basin-{stage}-{sub_index}-{instruction_index}-{case_index}",
            reuse=reuse_worker_game_dir,
        )
        result = run_case(
            binary=headless_bin,
            game_dir=case_worker_game_dir.resolve(),
            stage=stage,
            seed=seed,
            action_file=action_file,
            difficulty=difficulty,
            character=character,
            shot_type=shot_type,
            max_ticks=max_ticks,
            auto_shoot=auto_shoot,
            continue_after_hit=continue_after_hit,
            timeout_seconds=timeout_seconds,
            campaign_dir=artifact_dir,
            seed_name=seed_ecl.name,
            mutant=mutant,
            case_index=case_index,
            baseline_trace=baseline_trace,
        )
        result_path = artifact_dir / result["case_name"] / "result.json"
        trace_path = Path(str(result["trace"]))
        case_rows = _load_trace(trace_path)
        trace_sha256 = _trace_sha256(trace_path)
        freeze_summary = _freeze_summary(case_rows)
        tail = _tail_summary(case_rows)
        first_score_diff = _first_diff(baseline_rows, case_rows, key="score")
        first_stage_vm_diff = _first_diff(baseline_rows, case_rows, key="stage_vm")
        first_timeline_diff = _first_diff(baseline_rows, case_rows, key="ecl_timeline")
        scheduler_snapshot = _scheduler_snapshot(
            freeze_summary=freeze_summary,
            first_stage_vm_diff=first_stage_vm_diff,
            first_timeline_diff=first_timeline_diff,
            tail=tail,
        )
        scheduler_signature = _signature(scheduler_snapshot)
        cases.append(
            {
                "value": value,
                "interesting": bool(result.get("interesting")),
                "result": str(result_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "scheduler_signature": scheduler_signature,
                "scheduler_snapshot": scheduler_snapshot,
                "payload_sha256": str(target["payload_sha256"]),
                "findings": _ordered_findings(result.get("findings")),
                "worker_game_dir": str(case_worker_game_dir.resolve()),
                "worker_game_prepare": case_worker_prepare,
                "freeze_summary": freeze_summary,
                "first_score_diff": first_score_diff,
                "first_stage_vm_diff": first_stage_vm_diff,
                "first_timeline_diff": first_timeline_diff,
                "tail": tail,
            }
        )

    summary = {
        "artifact_dir": str(artifact_dir),
        "seed_ecl": str(seed_ecl),
        "site": {
            "stage": stage,
            "path": {
                "sub_index": sub_index,
                "instruction_index": instruction_index,
            },
            "family": family,
            "field_name": field_name,
            "field_offset": field_offset,
            "opcode": opcode,
            "original_value": original_value,
        },
        "values_tested": values,
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "worker_game_dir": str(baseline_worker_game_dir.resolve()),
            "worker_game_prepare": baseline_worker_prepare,
            "command": baseline_metadata["command"],
            "tail": baseline_tail,
        },
        "cases": cases,
        "groups_by_trace": _group_by_trace(cases),
        "groups_by_scheduler": _group_by_scheduler(cases),
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    values = list(args.values)
    if args.values_file is not None:
        values.extend(_load_values_from_file(args.values_file.resolve()))
    summary = map_site_basins(
        seed_ecl=args.seed_ecl,
        stage=args.stage,
        sub_index=args.sub_index,
        instruction_index=args.instruction_index,
        field_offset=args.field_offset,
        family=args.family,
        field_name=args.field_name,
        expected_opcode=args.expected_opcode,
        expected_original_value=args.expected_original_value,
        values=values,
        artifact_dir=args.artifact_dir or _default_artifact_dir(),
        headless_bin=args.headless_bin,
        game_dir=args.game_dir,
        action_file=args.action_file,
        seed=args.seed,
        difficulty=args.difficulty,
        character=args.character,
        shot_type=args.shot_type,
        max_ticks=args.max_ticks,
        timeout_seconds=args.timeout_seconds,
        auto_shoot=args.auto_shoot,
        continue_after_hit=args.continue_after_hit,
        reuse_worker_game_dir=not args.no_reuse_worker_game_dir,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
