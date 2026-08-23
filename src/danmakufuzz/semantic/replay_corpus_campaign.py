from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from ..headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, DEFAULT_TRACE_COMPACT_COUNTS, default_headless_binary
from ..parser.replay import replay_populated_stages, validate_replay
from ..repo import ARTIFACTS_DIR, ensure_directory
from .replay_desync_campaign import run_replay_desync_campaign


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-replay-corpus" / stamp


def _sanitize_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "replay"


def _result_paths_from_directory(directory: Path) -> list[Path]:
    return sorted(path.resolve() for path in directory.rglob("*.rpy") if path.is_file())


def _discover_inputs(
    *,
    input_paths: list[Path],
    input_dirs: list[Path],
    input_globs: list[str],
    replay_dirs: list[Path],
) -> list[Path]:
    discovered: list[Path] = []
    for path in input_paths:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"missing replay input: {resolved}")
        discovered.append(resolved)
    for directory in input_dirs + replay_dirs:
        resolved = directory.resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"missing replay directory: {resolved}")
        discovered.extend(_result_paths_from_directory(resolved))
    for pattern in input_globs:
        matches = [path.resolve() for path in Path.cwd().glob(pattern) if path.is_file()]
        if not matches:
            raise FileNotFoundError(f"replay glob did not match any files: {pattern}")
        discovered.extend(sorted(matches))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the replay semantic/desync lane across a corpus of real or harvested .rpy files."
    )
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--input-dir", type=Path, action="append", default=[])
    parser.add_argument("--input-glob", action="append", default=[])
    parser.add_argument(
        "--replay-dir",
        type=Path,
        action="append",
        default=[],
        help="explicit replay directory, e.g. a copied game replay folder",
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--stage-filter", type=int, action="append")
    parser.add_argument("--max-ticks", type=int)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--trace-compact-counts", dest="trace_compact_counts", action="store_true")
    parser.add_argument("--full-entity-trace", dest="trace_compact_counts", action="store_false")
    parser.set_defaults(trace_compact_counts=DEFAULT_TRACE_COMPACT_COUNTS)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--samples-per-site", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--limit-replays", type=int)
    parser.add_argument("--limit-stage-slots", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    replay_paths = _discover_inputs(
        input_paths=list(args.input),
        input_dirs=list(args.input_dir),
        input_globs=list(args.input_glob),
        replay_dirs=list(args.replay_dir),
    )
    if not replay_paths:
        raise ValueError("replay corpus campaign did not discover any .rpy inputs")
    if args.limit_replays is not None:
        replay_paths = replay_paths[: args.limit_replays]

    stage_filters = set(args.stage_filter or [])
    summary_path = artifact_dir / "summary.jsonl"
    skipped_path = artifact_dir / "skipped.jsonl"
    classification_counts: Counter[str] = Counter()
    discovered_stage_slots = 0
    executed_stage_slots = 0
    interesting_campaigns = 0
    interesting_cases = 0
    skipped_inputs = 0

    with summary_path.open("w", encoding="utf-8") as summary_handle, skipped_path.open(
        "w", encoding="utf-8"
    ) as skipped_handle:
        for replay_index, replay_path in enumerate(replay_paths, start=1):
            row_prefix = {
                "replay": str(replay_path),
                "replay_index": replay_index,
            }
            try:
                payload = replay_path.read_bytes()
                validation = validate_replay(payload)
                populated = list(replay_populated_stages(payload))
            except Exception as exc:
                skipped_inputs += 1
                row = {
                    **row_prefix,
                    "status": "invalid-replay",
                    "reason": str(exc),
                }
                skipped_handle.write(json.dumps(row) + "\n")
                print(json.dumps(row, ensure_ascii=False))
                continue

            if stage_filters:
                populated = [stage for stage in populated if stage in stage_filters]
            discovered_stage_slots += len(populated)
            if not populated:
                skipped_inputs += 1
                row = {
                    **row_prefix,
                    "status": "no-selected-stage-slots",
                    "validation": validation,
                }
                skipped_handle.write(json.dumps(row) + "\n")
                print(json.dumps(row, ensure_ascii=False))
                continue

            if args.limit_stage_slots is not None:
                remaining = max(0, args.limit_stage_slots - executed_stage_slots)
                if remaining <= 0:
                    break
                populated = populated[:remaining]

            for stage in populated:
                executed_stage_slots += 1
                stage_artifact_dir = (
                    artifact_dir / f"{executed_stage_slots:04d}-{_sanitize_component(replay_path.stem)}-s{stage}"
                )
                report = run_replay_desync_campaign(
                    artifact_dir=stage_artifact_dir,
                    input_path=replay_path,
                    actions_path=args.actions.resolve(),
                    game_dir=args.game_dir.resolve(),
                    headless_bin=args.headless_bin.resolve(),
                    stage=stage,
                    seed=args.seed,
                    difficulty=None,
                    character=None,
                    shot_type=None,
                    max_ticks=args.max_ticks,
                    timeout_seconds=args.timeout_seconds,
                    auto_shoot=True,
                    continue_after_hit=args.continue_after_hit,
                    trace_compact_counts=args.trace_compact_counts,
                    random_seed=args.random_seed,
                    samples_per_site=args.samples_per_site,
                    limit=args.limit,
                    name_filters=list(args.name_filter or []),
                    emit_stdout=False,
                )
                row = {
                    **row_prefix,
                    "status": "ran",
                    "stage": stage,
                    "artifact_dir": str(stage_artifact_dir.resolve()),
                    "validation": validation,
                    "campaign": report,
                }
                if int(report.get("interesting_cases", 0)) > 0:
                    interesting_campaigns += 1
                    classification_counts["interesting-campaign"] += 1
                else:
                    classification_counts["boring-campaign"] += 1
                interesting_cases += int(report.get("interesting_cases", 0))
                summary_handle.write(json.dumps(row) + "\n")
                print(json.dumps(row, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-semantic-replay-corpus-v1",
        "inputs": [str(path) for path in replay_paths],
        "stage_filters": sorted(stage_filters),
        "limit_replays": args.limit_replays,
        "limit_stage_slots": args.limit_stage_slots,
        "seed": args.seed,
        "random_seed": args.random_seed,
        "samples_per_site": args.samples_per_site,
        "limit": args.limit,
        "discovered_replays": len(replay_paths),
        "discovered_stage_slots": discovered_stage_slots,
        "executed_stage_slots": executed_stage_slots,
        "interesting_campaigns": interesting_campaigns,
        "interesting_cases": interesting_cases,
        "skipped_inputs": skipped_inputs,
        "classification_counts": dict(sorted(classification_counts.items())),
        "summary": str(summary_path.resolve()),
        "skipped": str(skipped_path.resolve()),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
