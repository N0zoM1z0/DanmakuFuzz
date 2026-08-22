from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from ..repo import ARTIFACTS_DIR, ensure_directory


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-trace-basins" / stamp


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"trace basin input is not an object: {path}")
    return value


def _result_paths_from_summary_jsonl(path: Path) -> list[Path]:
    discovered: list[Path] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"summary.jsonl entry is not an object: {path}:{line_number}")
            case_name = value.get("case_name")
            if not isinstance(case_name, str):
                raise ValueError(f"summary.jsonl entry is missing case_name: {path}:{line_number}")
            result_path = (path.parent / case_name / "result.json").resolve()
            if not result_path.is_file():
                raise FileNotFoundError(f"summary.jsonl entry points to a missing result.json: {result_path}")
            discovered.append(result_path)
    return discovered


def _discover_results(inputs: list[Path]) -> list[Path]:
    discovered: list[Path] = []
    for item in inputs:
        resolved = item.resolve()
        if resolved.is_file():
            if resolved.name == "result.json":
                discovered.append(resolved)
                continue
            if resolved.name == "summary.jsonl":
                discovered.extend(_result_paths_from_summary_jsonl(resolved))
                continue
            if resolved.name == "campaign.json":
                campaign = _load_json_object(resolved)
                summary_path = campaign.get("summary")
                if not isinstance(summary_path, str):
                    raise ValueError(f"campaign.json is missing summary path: {resolved}")
                discovered.extend(_result_paths_from_summary_jsonl(Path(summary_path).resolve()))
                continue
            raise ValueError(f"unsupported trace basin input file: {resolved}")
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("result.json")))
            continue
        raise FileNotFoundError(f"trace basin input does not exist: {resolved}")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _infer_baseline_trace(result_path: Path) -> Path | None:
    candidates = (
        result_path.parent.parent / "_baseline" / "trace.jsonl",
        result_path.parent.parent / "baseline" / "trace.jsonl",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _normalize_enemy(enemy: dict[str, Any], *, pos_round: int) -> dict[str, Any]:
    return {
        "x": round(float(enemy.get("x", 0.0)), pos_round),
        "y": round(float(enemy.get("y", 0.0)), pos_round),
        "life": int(enemy.get("life", 0)),
        "max_life": int(enemy.get("max_life", 0)),
        "boss": bool(enemy.get("boss")),
        "boss_id": int(enemy.get("boss_id", 0)),
        "boss_timer": int(enemy.get("boss_timer", 0)),
        "life_callback_threshold": int(enemy.get("life_callback_threshold", 0)),
        "timer_callback_threshold": int(enemy.get("timer_callback_threshold", 0)),
        "stack_depth": int(enemy.get("stack_depth", 0)),
        "run_interrupt": int(enemy.get("run_interrupt", 0)),
        "ecl_sub": int(enemy.get("ecl_sub", 0)),
        "ecl_time": int(enemy.get("ecl_time", 0)),
    }


def _normalize_record(record: dict[str, Any], *, pos_round: int) -> dict[str, Any]:
    enemies = record.get("enemies")
    normalized_enemies = []
    if isinstance(enemies, list):
        normalized_enemies = [
            _normalize_enemy(enemy, pos_round=pos_round)
            for enemy in enemies
            if isinstance(enemy, dict)
        ]
    items = record.get("items")
    item_count = len(items) if isinstance(items, list) else 0
    bullets = record.get("bullets")
    bullet_count = len(bullets) if isinstance(bullets, list) else 0
    return {
        "tick": int(record.get("tick", 0)),
        "game_frame": int(record.get("game_frame", 0)),
        "score": int(record.get("score", 0)),
        "lives": int(record.get("lives", 0)),
        "bombs": int(record.get("bombs", 0)),
        "power": int(record.get("power", 0)),
        "enemy_count": int(record.get("enemy_count", 0)),
        "item_count": item_count,
        "bullet_count": bullet_count,
        "point_items_stage": int(record.get("point_items_stage", 0)),
        "point_items_total": int(record.get("point_items_total", 0)),
        "stage_vm": record.get("stage_vm"),
        "ecl_timeline": record.get("ecl_timeline"),
        "boss_ui": record.get("boss_ui"),
        "spellcard": record.get("spellcard"),
        "enemies": normalized_enemies,
    }


def _load_normalized_trace(path: Path, *, pos_round: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"trace row is not an object: {path}:{line_number}")
            rows.append(_normalize_record(value, pos_round=pos_round))
    return rows


def _record_diff_keys(lhs: dict[str, Any], rhs: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key in (
        "game_frame",
        "score",
        "lives",
        "bombs",
        "power",
        "enemy_count",
        "item_count",
        "bullet_count",
        "point_items_stage",
        "point_items_total",
        "stage_vm",
        "ecl_timeline",
        "boss_ui",
        "spellcard",
        "enemies",
    ):
        if lhs.get(key) != rhs.get(key):
            keys.append(key)
    return keys


def _first_divergence(
    baseline_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str] | None]:
    for baseline_record, case_record in zip(baseline_rows, case_rows):
        diff_keys = _record_diff_keys(baseline_record, case_record)
        if diff_keys:
            return case_record, diff_keys
    if len(case_rows) != len(baseline_rows):
        longer = case_rows if len(case_rows) > len(baseline_rows) else baseline_rows
        if len(baseline_rows) < len(case_rows):
            return case_rows[len(baseline_rows)], ["trace-length"]
        return longer[len(case_rows)], ["trace-length"]
    return None, None


def _first_negative_next_time(case_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for record in case_rows:
        timeline = record.get("ecl_timeline")
        if not isinstance(timeline, dict):
            continue
        next_time = timeline.get("next_time")
        if isinstance(next_time, int) and next_time < -1:
            return record
    return None


def _sink_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_frame": record["game_frame"],
        "score": record["score"],
        "lives": record["lives"],
        "bombs": record["bombs"],
        "power": record["power"],
        "enemy_count": record["enemy_count"],
        "item_count": record["item_count"],
        "bullet_count": record["bullet_count"],
        "point_items_stage": record["point_items_stage"],
        "point_items_total": record["point_items_total"],
        "stage_vm": record["stage_vm"],
        "ecl_timeline": record["ecl_timeline"],
        "boss_ui": record["boss_ui"],
        "spellcard": record["spellcard"],
        "enemies": record["enemies"],
    }


def _signature(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class BasinAccumulator:
    signature: str
    sink_snapshot: dict[str, Any]
    sink_tick: int
    sink_next_time: int | None
    sink_time: int | None
    case_names: list[str]
    results: list[str]
    first_divergence_ticks: Counter[int]
    first_divergence_keys: Counter[str]
    mutation_families: Counter[str]

    def __init__(
        self,
        *,
        signature: str,
        sink_snapshot: dict[str, Any],
        sink_tick: int,
        sink_next_time: int | None,
        sink_time: int | None,
    ) -> None:
        self.signature = signature
        self.sink_snapshot = sink_snapshot
        self.sink_tick = sink_tick
        self.sink_next_time = sink_next_time
        self.sink_time = sink_time
        self.case_names = []
        self.results = []
        self.first_divergence_ticks = Counter()
        self.first_divergence_keys = Counter()
        self.mutation_families = Counter()

    def add(
        self,
        *,
        case_name: str,
        result_path: Path,
        first_divergence_tick: int | None,
        first_divergence_keys: list[str] | None,
        family: str,
    ) -> None:
        self.case_names.append(case_name)
        if len(self.results) < 12:
            self.results.append(str(result_path.resolve()))
        if first_divergence_tick is not None:
            self.first_divergence_ticks[first_divergence_tick] += 1
        if first_divergence_keys:
            for key in first_divergence_keys:
                self.first_divergence_keys[key] += 1
        self.mutation_families[family] += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "cases": len(self.case_names),
            "case_names": list(self.case_names),
            "results": list(self.results),
            "sink_tick": self.sink_tick,
            "sink_time": self.sink_time,
            "sink_next_time": self.sink_next_time,
            "first_divergence_ticks": dict(self.first_divergence_ticks.most_common()),
            "first_divergence_keys": dict(self.first_divergence_keys.most_common()),
            "mutation_families": dict(self.mutation_families.most_common()),
            "sink_snapshot": self.sink_snapshot,
        }


def _family_name(result: dict[str, Any]) -> str:
    mutation_metadata = result.get("mutation_metadata")
    if isinstance(mutation_metadata, dict):
        family = mutation_metadata.get("family")
        if isinstance(family, str) and family:
            return family
    mutant_name = result.get("mutant_name")
    if not isinstance(mutant_name, str):
        return "unknown"
    if "-sampled-" in mutant_name:
        return mutant_name.split("-sampled-", 1)[0]
    parts = [part for part in mutant_name.split("-") if part]
    if len(parts) >= 2:
        return "-".join(parts[:2])
    return mutant_name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Group semantic cases by common differential sink states against a baseline trace."
    )
    parser.add_argument("input", nargs="+", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--min-cases", type=int, default=1)
    parser.add_argument("--baseline-trace", type=Path)
    parser.add_argument("--include-non-interesting", action="store_true")
    parser.add_argument("--position-round", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_paths = _discover_results(args.input)
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    explicit_baseline = args.baseline_trace.resolve() if args.baseline_trace is not None else None
    baseline_cache: dict[Path, list[dict[str, Any]]] = {}
    basins: dict[str, BasinAccumulator] = {}
    case_rows: list[dict[str, Any]] = []
    totals = {
        "results": 0,
        "interesting": 0,
        "basins": 0,
        "cases_with_divergence": 0,
        "cases_with_negative_next_time": 0,
    }

    for result_path in result_paths:
        result = _load_json_object(result_path)
        interesting = bool(result.get("interesting"))
        if not interesting and not args.include_non_interesting:
            continue
        totals["results"] += 1
        totals["interesting"] += int(interesting)

        baseline_trace = explicit_baseline or _infer_baseline_trace(result_path)
        if baseline_trace is None or not baseline_trace.is_file():
            raise FileNotFoundError(f"could not infer baseline trace for {result_path}")
        baseline_rows = baseline_cache.get(baseline_trace)
        if baseline_rows is None:
            baseline_rows = _load_normalized_trace(baseline_trace, pos_round=args.position_round)
            baseline_cache[baseline_trace] = baseline_rows

        trace_path = Path(str(result.get("trace", ""))).resolve()
        if not trace_path.is_file():
            raise FileNotFoundError(f"result trace is missing: {trace_path}")
        case_trace_rows = _load_normalized_trace(trace_path, pos_round=args.position_round)
        first_divergence_record, first_divergence_keys = _first_divergence(baseline_rows, case_trace_rows)
        if first_divergence_record is not None:
            totals["cases_with_divergence"] += 1
        sink_record = _first_negative_next_time(case_trace_rows)
        if sink_record is not None:
            totals["cases_with_negative_next_time"] += 1
        if sink_record is None:
            sink_record = first_divergence_record
        if sink_record is None:
            sink_snapshot = None
            sink_signature = None
            sink_tick = None
            sink_time = None
            sink_next_time = None
        else:
            sink_snapshot = _sink_snapshot(sink_record)
            sink_signature = _signature(sink_snapshot)
            sink_tick = sink_record["tick"]
            timeline = sink_record.get("ecl_timeline")
            sink_time = timeline.get("time") if isinstance(timeline, dict) and isinstance(timeline.get("time"), int) else None
            sink_next_time = (
                timeline.get("next_time")
                if isinstance(timeline, dict) and isinstance(timeline.get("next_time"), int)
                else None
            )

        case_name = result.get("case_name")
        if not isinstance(case_name, str):
            raise ValueError(f"result is missing case_name: {result_path}")
        family = _family_name(result)
        case_row = {
            "case_name": case_name,
            "result": str(result_path.resolve()),
            "interesting": interesting,
            "family": family,
            "stage": result.get("stage"),
            "seed_name": result.get("seed_name"),
            "first_divergence_tick": (
                first_divergence_record["tick"] if first_divergence_record is not None else None
            ),
            "first_divergence_keys": list(first_divergence_keys or []),
            "sink_signature": sink_signature,
            "sink_tick": sink_tick,
            "sink_time": sink_time,
            "sink_next_time": sink_next_time,
            "baseline_trace": str(baseline_trace),
            "trace": str(trace_path),
        }
        case_rows.append(case_row)

        if sink_signature is None or sink_snapshot is None or sink_tick is None:
            continue
        accumulator = basins.get(sink_signature)
        if accumulator is None:
            accumulator = BasinAccumulator(
                signature=sink_signature,
                sink_snapshot=sink_snapshot,
                sink_tick=sink_tick,
                sink_next_time=sink_next_time,
                sink_time=sink_time,
            )
            basins[sink_signature] = accumulator
        accumulator.add(
            case_name=case_name,
            result_path=result_path,
            first_divergence_tick=case_row["first_divergence_tick"],
            first_divergence_keys=first_divergence_keys,
            family=family,
        )

    basin_rows = [acc.to_dict() for acc in basins.values() if len(acc.case_names) >= args.min_cases]
    basin_rows.sort(
        key=lambda row: (
            -int(row["cases"]),
            -int(row["first_divergence_ticks"].get(str(row["sink_tick"]), 0))
            if isinstance(row["first_divergence_ticks"], dict)
            else 0,
            int(row["sink_tick"]) if isinstance(row["sink_tick"], int) else 2**31 - 1,
            str(row["signature"]),
        )
    )
    totals["basins"] = len(basin_rows)
    case_rows.sort(
        key=lambda row: (
            -(1 if row["interesting"] else 0),
            int(row["sink_tick"]) if isinstance(row["sink_tick"], int) else 2**31 - 1,
            int(row["first_divergence_tick"]) if isinstance(row["first_divergence_tick"], int) else 2**31 - 1,
            str(row["case_name"]),
        )
    )
    summary = {
        "artifact_dir": str(artifact_dir),
        "inputs": [str(path.resolve()) for path in args.input],
        "explicit_baseline_trace": str(explicit_baseline) if explicit_baseline is not None else None,
        "totals": totals,
        "basins": basin_rows[: args.limit],
        "cases": case_rows[: max(args.limit * 4, args.limit)],
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
