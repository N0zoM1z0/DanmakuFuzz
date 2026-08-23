from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from ..headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from ..interestingness.rules import load_trace_records
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .ecl_campaign import (
    DEFAULT_EXPLORATION_SWEEP_LIMIT,
    infer_stage_from_ecl_name,
    practice_stage_supported,
    resolve_campaign_profile,
    resolve_mutant_limit,
    resolve_selection_mode,
    run_case,
    select_mutants,
)


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-family-sweep" / stamp


def default_seed_ecls() -> list[Path]:
    return sorted((REFERENCE_DIR / "corpus" / "ecl" / "original").glob("ecldata*.ecl"))


def _value_slug(value: int) -> str:
    if value < 0:
        return f"neg{-value}"
    return str(value)


def _dedupe_preserve_order(values: list[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _resolve_random_seeds(args: argparse.Namespace) -> list[int]:
    if args.random_seed:
        return _dedupe_preserve_order(list(args.random_seed))
    generated = list(range(args.random_seed_start, args.random_seed_start + args.random_seed_count))
    return _dedupe_preserve_order(generated)


def _peak_count(record: dict[str, object], key: str) -> int:
    value = record.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _summarize_baseline(trace_path: Path) -> dict[str, int | str | None]:
    max_tick = 0
    peak_bullets = 0
    peak_lasers = 0
    peak_enemies = 0
    peak_items = 0
    terminal_reason: str | None = None
    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            tick = record.get("tick")
            if isinstance(tick, int):
                max_tick = tick
            peak_bullets = max(peak_bullets, _peak_count(record, "bullets"))
            peak_lasers = max(peak_lasers, _peak_count(record, "lasers"))
            peak_enemies = max(peak_enemies, _peak_count(record, "enemies"))
            peak_items = max(peak_items, _peak_count(record, "items"))
            reason = record.get("terminal_reason")
            terminal_reason = reason if isinstance(reason, str) else terminal_reason
    return {
        "max_tick": max_tick,
        "peak_bullets": peak_bullets,
        "peak_lasers": peak_lasers,
        "peak_enemies": peak_enemies,
        "peak_items": peak_items,
        "terminal_reason": terminal_reason,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep reusable semantic mutator families across multiple retail ECL seeds."
    )
    parser.add_argument("--seed-ecl", action="append", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--max-ticks", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--profile", choices=("default", "core", "boss"), default="core")
    parser.add_argument("--limit-per-seed", type=int)
    parser.add_argument("--full-mutant-set", action="store_true")
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--include-structural", action="store_true")
    parser.add_argument("--mutation-mode", choices=("deterministic", "exploration"), default="deterministic")
    parser.add_argument("--random-seed", action="append", type=int)
    parser.add_argument("--random-seed-start", type=int, default=0)
    parser.add_argument("--random-seed-count", type=int, default=1)
    parser.add_argument("--samples-per-site", type=int, default=4)
    parser.add_argument("--selection-mode", choices=("auto", "family", "site", "family-site"), default="auto")
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_ecls = [path.resolve() for path in args.seed_ecl] if args.seed_ecl else [path.resolve() for path in default_seed_ecls()]
    random_seeds = _resolve_random_seeds(args)
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    resolved_selection_mode = resolve_selection_mode(
        mutation_mode=args.mutation_mode,
        selection_mode=args.selection_mode,
    )
    limit_policy = resolve_mutant_limit(
        mutation_mode=args.mutation_mode,
        requested_limit=args.limit_per_seed,
        full_mutant_set=args.full_mutant_set,
        default_exploration_limit=DEFAULT_EXPLORATION_SWEEP_LIMIT,
    )
    profile = resolve_campaign_profile(
        profile=args.profile,
        action_file=args.actions.resolve(),
        max_ticks=args.max_ticks,
        timeout_seconds=args.timeout_seconds,
        continue_after_hit=args.continue_after_hit,
        case_prefix="campaign",
        name_filters=args.name_filter,
    )

    totals = {
        "seeds_considered": 0,
        "seeds_run": 0,
        "sampler_runs": 0,
        "cases_run": 0,
        "interesting_cases": 0,
    }
    seed_summaries: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    for seed_ecl in seed_ecls:
        totals["seeds_considered"] += 1
        if not seed_ecl.is_file():
            skipped.append({"seed_ecl": str(seed_ecl), "reason": "missing-seed"})
            continue
        stage = infer_stage_from_ecl_name(seed_ecl)
        if not practice_stage_supported(stage):
            skipped.append(
                {
                    "seed_ecl": str(seed_ecl),
                    "stage": stage,
                    "reason": "unsupported-practice-stage",
                }
            )
            continue

        seed_dir = artifact_dir / seed_ecl.stem
        ensure_directory(seed_dir)
        baseline_dir = seed_dir / "_baseline"
        baseline_metadata = run_baseline(
            binary=args.headless_bin.resolve(),
            game_dir=args.game_dir.resolve(),
            resource_override_dir=None,
            stage=stage,
            seed=args.seed,
            action_file=Path(profile["action_file"]),
            artifact_dir=baseline_dir,
            difficulty=args.difficulty,
            character=args.character,
            shot_type=args.shot_type,
            max_ticks=int(profile["max_ticks"]),
            auto_shoot=args.auto_shoot,
            continue_after_hit=bool(profile["continue_after_hit"]),
            trace_compact_counts=True,
            dry_run=False,
        )
        baseline_trace_value = baseline_metadata.get("trace")
        baseline_trace = Path(baseline_trace_value) if isinstance(baseline_trace_value, str) else None
        if baseline_trace is None or not baseline_trace.is_file():
            raise RuntimeError(f"family sweep baseline trace missing for {seed_ecl}")
        baseline_records = load_trace_records(baseline_trace)

        totals["seeds_run"] += 1
        for random_seed in random_seeds:
            run_dir = seed_dir / f"rs{_value_slug(random_seed)}"
            ensure_directory(run_dir)
            mutants = select_mutants(
                seed_ecl.read_bytes(),
                include_structural=args.include_structural,
                name_filters=profile["name_filters"],
                mutation_mode=args.mutation_mode,
                random_seed=random_seed,
                samples_per_site=args.samples_per_site,
                limit=limit_policy["effective_limit"],
                family_filters=profile["name_filters"],
                selection_mode=resolved_selection_mode,
            )

            summary_path = run_dir / "summary.jsonl"
            seed_totals = {"cases_run": 0, "interesting_cases": 0}
            with summary_path.open("w", encoding="utf-8") as summary_handle:
                for case_index, mutant in enumerate(mutants, start=1):
                    result = run_case(
                        binary=args.headless_bin.resolve(),
                        game_dir=args.game_dir.resolve(),
                        stage=stage,
                        seed=args.seed,
                        action_file=Path(profile["action_file"]),
                        difficulty=args.difficulty,
                        character=args.character,
                        shot_type=args.shot_type,
                        max_ticks=int(profile["max_ticks"]),
                        auto_shoot=args.auto_shoot,
                        continue_after_hit=bool(profile["continue_after_hit"]),
                        timeout_seconds=float(profile["timeout_seconds"]),
                        trace_compact_counts=True,
                        campaign_dir=run_dir,
                        seed_name=seed_ecl.name,
                        mutant=mutant,
                        case_index=case_index,
                        baseline_trace=baseline_trace,
                        baseline_records=baseline_records,
                    )
                    seed_totals["cases_run"] += 1
                    seed_totals["interesting_cases"] += int(bool(result["interesting"]))
                    summary_handle.write(json.dumps(result) + "\n")
                    print(
                        json.dumps(
                            {
                                "profile": profile["profile"],
                                "seed_ecl": str(seed_ecl),
                                "random_seed": random_seed,
                                "case_name": result["case_name"],
                                "mutant_name": result["mutant_name"],
                                "interesting": result["interesting"],
                                "findings": result["findings"],
                            },
                            ensure_ascii=False,
                        )
                    )

            totals["sampler_runs"] += 1
            totals["cases_run"] += seed_totals["cases_run"]
            totals["interesting_cases"] += seed_totals["interesting_cases"]
            seed_summary = {
                "profile": profile["profile"],
                "seed_ecl": str(seed_ecl),
                "stage": stage,
                "name_filters": list(profile["name_filters"]),
                "include_structural": args.include_structural,
                "mutation_mode": args.mutation_mode,
                "requested_limit_per_seed": limit_policy["requested_limit"],
                "effective_limit_per_seed": limit_policy["effective_limit"],
                "limit_auto_applied": limit_policy["auto_applied"],
                "limit_reason": limit_policy["reason"],
                "random_seed": random_seed,
                "samples_per_site": args.samples_per_site,
                "selection_mode": resolved_selection_mode,
                "actions": str(Path(profile["action_file"]).resolve()),
                "max_ticks": int(profile["max_ticks"]),
                "continue_after_hit": bool(profile["continue_after_hit"]),
                "baseline": _summarize_baseline(baseline_trace),
                "mutants_generated": len(mutants),
                "cases_run": seed_totals["cases_run"],
                "interesting_cases": seed_totals["interesting_cases"],
                "summary": str(summary_path.resolve()),
            }
            seed_summaries.append(seed_summary)
            (run_dir / "campaign.json").write_text(json.dumps(seed_summary, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(seed_summary, indent=2))

    report = {
        "artifact_dir": str(artifact_dir),
        "profile": profile["profile"],
        "name_filters": list(profile["name_filters"]),
        "include_structural": args.include_structural,
        "mutation_mode": args.mutation_mode,
        "requested_limit_per_seed": limit_policy["requested_limit"],
        "effective_limit_per_seed": limit_policy["effective_limit"],
        "limit_auto_applied": limit_policy["auto_applied"],
        "limit_reason": limit_policy["reason"],
        "random_seeds": random_seeds,
        "samples_per_site": args.samples_per_site,
        "selection_mode": resolved_selection_mode,
        "totals": totals,
        "seeds": seed_summaries,
        "skipped": skipped,
    }
    (artifact_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
