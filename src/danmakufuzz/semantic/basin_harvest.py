from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ..ecl_ir.parser import parse_ecl
from ..headless.baseline import DEFAULT_GAME_DIR, default_headless_binary
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .ecl_campaign import LONG_ACTION_FILE
from .hotspots import _discover_results, _family_name, _load_result, _mutation_value, _site_key
from .site_basin_mapper import map_site_basins


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-basin-harvest" / stamp


def _seed_corpus_path(seed_name: str) -> Path:
    return REFERENCE_DIR / "corpus" / "ecl" / "original" / seed_name


def _metadata_field_offset(data: dict[str, object]) -> int | None:
    metadata = data.get("mutation_metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("arg_offset")
    return value if isinstance(value, int) else None


def _metadata_field_name(data: dict[str, object]) -> str | None:
    metadata = data.get("mutation_metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("field")
    return value if isinstance(value, str) and value else None


def _finding_kinds(data: dict[str, object]) -> tuple[str, ...]:
    findings = data.get("findings")
    if not isinstance(findings, list):
        return ()
    ordered: list[str] = []
    seen: set[str] = set()
    for item in findings:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if not isinstance(kind, str) or kind in seen:
            continue
        seen.add(kind)
        ordered.append(kind)
    return tuple(ordered)


def _result_sort_key(path: Path) -> tuple[str, ...]:
    return (str(path.resolve()),)


def _spread_sample(values: list[int], limit: int) -> list[int]:
    if limit <= 0 or not values:
        return []
    if len(values) <= limit:
        return list(values)
    if limit == 1:
        return [values[len(values) // 2]]
    indexes = {round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)}
    sampled = [values[index] for index in sorted(indexes)]
    if len(sampled) >= limit:
        return sampled[:limit]
    for value in values:
        if value in sampled:
            continue
        sampled.append(value)
        if len(sampled) >= limit:
            break
    return sampled


def _neighbor_values(interesting_values: list[int], noninteresting_values: list[int], limit: int) -> list[int]:
    if limit <= 0 or not interesting_values or not noninteresting_values:
        return []
    candidates: list[int] = []
    for value in interesting_values:
        index = bisect.bisect_left(noninteresting_values, value)
        for neighbor_index in (index - 1, index):
            if 0 <= neighbor_index < len(noninteresting_values):
                candidates.append(noninteresting_values[neighbor_index])
    deduped: list[int] = []
    seen: set[int] = set()
    for value in candidates:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return _spread_sample(deduped, limit)


def _dedupe_preserve_order(values: list[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _sentinel_values_from_tokens(tokens: list[str]) -> list[int]:
    return [int(token, 0) for token in tokens]


@dataclass
class ScalarHotspot:
    stage: int
    seed_name: str
    family: str
    sub_index: int
    instruction_index: int
    field_offset: int
    field_name: str
    total_cases: int = 0
    interesting_cases: int = 0
    values_total: list[int] = field(default_factory=list)
    values_interesting: list[int] = field(default_factory=list)
    representative_results: list[str] = field(default_factory=list)
    representative_result_paths: list[Path] = field(default_factory=list)
    finding_kinds: dict[str, int] = field(default_factory=dict)

    def add(self, data: dict[str, object], *, result_path: Path) -> None:
        self.total_cases += 1
        interesting = bool(data.get("interesting"))
        value = _mutation_value(data)
        if value is not None:
            self.values_total.append(value)
            if interesting:
                self.values_interesting.append(value)
        if interesting:
            self.interesting_cases += 1
            for kind in _finding_kinds(data):
                self.finding_kinds[kind] = self.finding_kinds.get(kind, 0) + 1
            if len(self.representative_results) < 8:
                self.representative_results.append(str(result_path.resolve()))
                self.representative_result_paths.append(result_path.resolve())

    @property
    def interesting_ratio(self) -> float:
        return float(self.interesting_cases) / float(self.total_cases) if self.total_cases else 0.0

    @property
    def values_noninteresting(self) -> list[int]:
        interesting = set(self.values_interesting)
        return [value for value in self.values_total if value not in interesting]

    def selected_values(
        self,
        *,
        max_interesting_values: int,
        max_neighbor_values: int,
        sentinel_values: list[int],
    ) -> list[int]:
        interesting = sorted(set(self.values_interesting))
        noninteresting = sorted(set(self.values_noninteresting))
        selected = _spread_sample(interesting, max_interesting_values)
        selected.extend(_neighbor_values(selected, noninteresting, max_neighbor_values))
        selected.extend(sentinel_values)
        return sorted(_dedupe_preserve_order(selected))

    def to_row(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "seed_name": self.seed_name,
            "family": self.family,
            "path": {
                "sub_index": self.sub_index,
                "instruction_index": self.instruction_index,
            },
            "field_offset": self.field_offset,
            "field_name": self.field_name,
            "total_cases": self.total_cases,
            "interesting_cases": self.interesting_cases,
            "interesting_ratio": self.interesting_ratio,
            "values_total": sorted(set(self.values_total)),
            "values_interesting": sorted(set(self.values_interesting)),
            "finding_kinds": dict(sorted(self.finding_kinds.items(), key=lambda item: (-item[1], item[0]))),
            "representative_results": list(self.representative_results),
        }


def _collect_scalar_hotspots(result_paths: list[Path]) -> list[ScalarHotspot]:
    hotspots: dict[tuple[object, ...], ScalarHotspot] = {}
    for result_path in sorted(result_paths, key=_result_sort_key):
        data = _load_result(result_path)
        stage = data.get("stage")
        seed_name = data.get("seed_name")
        sub_index, instruction_index = _site_key(data.get("path"))
        field_offset = _metadata_field_offset(data)
        field_name = _metadata_field_name(data)
        family = _family_name(data)
        if (
            not isinstance(stage, int)
            or not isinstance(seed_name, str)
            or not isinstance(sub_index, int)
            or not isinstance(instruction_index, int)
            or not isinstance(field_offset, int)
            or not isinstance(field_name, str)
        ):
            continue
        if _mutation_value(data) is None:
            continue
        key = (stage, seed_name, family, sub_index, instruction_index, field_offset, field_name)
        hotspot = hotspots.get(key)
        if hotspot is None:
            hotspot = ScalarHotspot(
                stage=stage,
                seed_name=seed_name,
                family=family,
                sub_index=sub_index,
                instruction_index=instruction_index,
                field_offset=field_offset,
                field_name=field_name,
            )
            hotspots[key] = hotspot
        hotspot.add(data, result_path=result_path)
    rows = list(hotspots.values())
    rows.sort(
        key=lambda row: (
            -row.interesting_cases,
            -row.interesting_ratio,
            -row.total_cases,
            row.stage,
            row.seed_name,
            row.family,
            row.sub_index,
            row.instruction_index,
        )
    )
    return rows


def _load_seed_site(
    *,
    seed_name: str,
    sub_index: int,
    instruction_index: int,
    field_offset: int,
) -> tuple[Path, int, int]:
    seed_ecl = _seed_corpus_path(seed_name).resolve()
    if not seed_ecl.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {seed_ecl}")
    ecl = parse_ecl(seed_ecl.read_bytes())
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if field_offset < 0 or field_offset + 4 > len(instruction.args):
        raise RuntimeError(
            f"field offset {field_offset} is outside instruction args length {len(instruction.args)} "
            f"for {seed_name} ({sub_index}, {instruction_index})"
        )
    original_value = int.from_bytes(instruction.args[field_offset:field_offset + 4], "little", signed=True)
    return seed_ecl, int(instruction.opcode), original_value


def _site_slug(hotspot: ScalarHotspot) -> str:
    return (
        f"stage{hotspot.stage}-"
        f"{hotspot.seed_name.removesuffix('.ecl')}-"
        f"{hotspot.family}-"
        f"s{hotspot.sub_index:02d}-i{hotspot.instruction_index:04d}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Harvest scalar semantic hotspots into exact site-basin reruns."
    )
    parser.add_argument("input", nargs="+", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--family", type=str)
    parser.add_argument("--stage", type=int)
    parser.add_argument("--seed-name", type=str)
    parser.add_argument("--sub-index", type=int)
    parser.add_argument("--instruction-index", type=int)
    parser.add_argument("--limit-sites", type=int, default=3)
    parser.add_argument("--min-interesting", type=int, default=2)
    parser.add_argument("--max-interesting-values", type=int, default=8)
    parser.add_argument("--max-neighbor-values", type=int, default=4)
    parser.add_argument(
        "--sentinel-value",
        dest="sentinel_values",
        action="append",
        default=["-1", "0", "1"],
        help="Extra exact i32 sentinel values to always include (default: -1, 0, 1). Repeatable.",
    )
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


def main() -> int:
    args = parse_args()
    result_paths = _discover_results(args.input)
    hotspots = _collect_scalar_hotspots(result_paths)
    filtered: list[ScalarHotspot] = []
    for hotspot in hotspots:
        if hotspot.interesting_cases < args.min_interesting:
            continue
        if args.family is not None and hotspot.family != args.family:
            continue
        if args.stage is not None and hotspot.stage != args.stage:
            continue
        if args.seed_name is not None and hotspot.seed_name != args.seed_name:
            continue
        if args.sub_index is not None and hotspot.sub_index != args.sub_index:
            continue
        if args.instruction_index is not None and hotspot.instruction_index != args.instruction_index:
            continue
        filtered.append(hotspot)
    selected_sites = filtered[: args.limit_sites]

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    sentinel_values = _sentinel_values_from_tokens(args.sentinel_values)

    harvested_rows: list[dict[str, object]] = []
    for hotspot in selected_sites:
        values = hotspot.selected_values(
            max_interesting_values=args.max_interesting_values,
            max_neighbor_values=args.max_neighbor_values,
            sentinel_values=sentinel_values,
        )
        if not values:
            continue
        seed_ecl, opcode, original_value = _load_seed_site(
            seed_name=hotspot.seed_name,
            sub_index=hotspot.sub_index,
            instruction_index=hotspot.instruction_index,
            field_offset=hotspot.field_offset,
        )
        site_artifact_dir = artifact_dir / _site_slug(hotspot)
        basin_summary = map_site_basins(
            seed_ecl=seed_ecl,
            stage=hotspot.stage,
            sub_index=hotspot.sub_index,
            instruction_index=hotspot.instruction_index,
            field_offset=hotspot.field_offset,
            family=hotspot.family,
            field_name=hotspot.field_name,
            values=values,
            artifact_dir=site_artifact_dir,
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
            expected_opcode=opcode,
            expected_original_value=original_value,
        )
        harvested_rows.append(
            {
                "hotspot": hotspot.to_row(),
                "selected_values": values,
                "seed_ecl": str(seed_ecl),
                "opcode": opcode,
                "original_value": original_value,
                "artifact_dir": str(site_artifact_dir.resolve()),
                "summary": str((site_artifact_dir / "summary.json").resolve()),
                "groups_by_trace": basin_summary["groups_by_trace"],
                "groups_by_scheduler": basin_summary["groups_by_scheduler"],
            }
        )

    summary = {
        "artifact_dir": str(artifact_dir),
        "inputs": [str(path.resolve()) for path in args.input],
        "filters": {
            "family": args.family,
            "stage": args.stage,
            "seed_name": args.seed_name,
            "sub_index": args.sub_index,
            "instruction_index": args.instruction_index,
            "min_interesting": args.min_interesting,
            "limit_sites": args.limit_sites,
            "max_interesting_values": args.max_interesting_values,
            "max_neighbor_values": args.max_neighbor_values,
            "sentinel_values": sentinel_values,
        },
        "discovered_scalar_hotspots": len(hotspots),
        "selected_sites": len(selected_sites),
        "harvested_sites": harvested_rows,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
