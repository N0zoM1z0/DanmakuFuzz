from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from ..headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from ..interestingness.rules import load_trace_records
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .ecl_campaign import (
    DEFAULT_EXPLORATION_SWEEP_LIMIT,
    DEFAULT_BOSS_NAME_FILTERS,
    LONG_ACTION_FILE,
    infer_stage_from_ecl_name,
    practice_stage_supported,
    resolve_mutant_limit,
    resolve_selection_mode,
    run_case,
    select_mutants,
)


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-boss-sweep" / stamp
def default_seed_ecls() -> list[Path]:
    return sorted((REFERENCE_DIR / "corpus" / "ecl" / "original").glob("ecldata*.ecl"))


def _summarize_boss_baseline(trace_path: Path) -> dict[str, int | str | None]:
    max_tick = 0
    boss_ticks = 0
    terminal_reason: str | None = None
    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            tick = record.get("tick")
            if isinstance(tick, int):
                max_tick = tick
            boss_ui = record.get("boss_ui")
            if isinstance(boss_ui, dict) and boss_ui.get("present"):
                boss_ticks += 1
            reason = record.get("terminal_reason")
            terminal_reason = reason if isinstance(reason, str) else terminal_reason
    return {
        "max_tick": max_tick,
        "boss_ticks": boss_ticks,
        "terminal_reason": terminal_reason,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep boss-oriented semantic mutator families across multiple retail ECL seeds.")
    parser.add_argument("--seed-ecl", action="append", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--actions", type=Path, default=LONG_ACTION_FILE)
    parser.add_argument("--max-ticks", type=int, default=1800)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--limit-per-seed", type=int)
    parser.add_argument("--full-mutant-set", action="store_true")
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--mutation-mode", choices=("deterministic", "exploration"), default="deterministic")
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--samples-per-site", type=int, default=4)
    parser.add_argument("--selection-mode", choices=("auto", "family", "site", "family-site"), default="auto")
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true", default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_ecls = [path.resolve() for path in args.seed_ecl] if args.seed_ecl else [path.resolve() for path in default_seed_ecls()]
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    name_filters = args.name_filter or list(DEFAULT_BOSS_NAME_FILTERS)
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

    totals = {"seeds_considered": 0, "seeds_run": 0, "cases_run": 0, "interesting_cases": 0}
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
            action_file=args.actions.resolve(),
            artifact_dir=baseline_dir,
            difficulty=args.difficulty,
            character=args.character,
            shot_type=args.shot_type,
            max_ticks=args.max_ticks,
            auto_shoot=args.auto_shoot,
            continue_after_hit=args.continue_after_hit,
            dry_run=False,
        )
        baseline_trace_value = baseline_metadata.get("trace")
        baseline_trace = Path(baseline_trace_value) if isinstance(baseline_trace_value, str) else None
        if baseline_trace is None or not baseline_trace.is_file():
            raise RuntimeError(f"boss sweep baseline trace missing for {seed_ecl}")
        baseline_records = load_trace_records(baseline_trace)

        mutants = select_mutants(
            seed_ecl.read_bytes(),
            include_structural=False,
            name_filters=name_filters,
            mutation_mode=args.mutation_mode,
            random_seed=args.random_seed,
            samples_per_site=args.samples_per_site,
            limit=limit_policy["effective_limit"],
            family_filters=name_filters,
            selection_mode=resolved_selection_mode,
        )

        summary_path = seed_dir / "summary.jsonl"
        seed_totals = {"cases_run": 0, "interesting_cases": 0}
        with summary_path.open("w", encoding="utf-8") as summary_handle:
            for case_index, mutant in enumerate(mutants, start=1):
                result = run_case(
                    binary=args.headless_bin.resolve(),
                    game_dir=args.game_dir.resolve(),
                    stage=stage,
                    seed=args.seed,
                    action_file=args.actions.resolve(),
                    difficulty=args.difficulty,
                    character=args.character,
                    shot_type=args.shot_type,
                    max_ticks=args.max_ticks,
                    auto_shoot=args.auto_shoot,
                    continue_after_hit=args.continue_after_hit,
                    timeout_seconds=args.timeout_seconds,
                    campaign_dir=seed_dir,
                    seed_name=seed_ecl.name,
                    mutant=mutant,
                    case_index=case_index,
                    baseline_trace=baseline_trace,
                    baseline_records=baseline_records,
                )
                seed_totals["cases_run"] += 1
                seed_totals["interesting_cases"] += int(bool(result["interesting"]))
                summary_handle.write(json.dumps(result) + "\n")
                print(json.dumps(
                    {
                        "seed_ecl": str(seed_ecl),
                        "case_name": result["case_name"],
                        "mutant_name": result["mutant_name"],
                        "interesting": result["interesting"],
                        "findings": result["findings"],
                    },
                    ensure_ascii=False,
                ))

        totals["seeds_run"] += 1
        totals["cases_run"] += seed_totals["cases_run"]
        totals["interesting_cases"] += seed_totals["interesting_cases"]
        seed_summary = {
            "seed_ecl": str(seed_ecl),
            "stage": stage,
            "name_filters": list(name_filters),
            "mutation_mode": args.mutation_mode,
            "requested_limit_per_seed": limit_policy["requested_limit"],
            "effective_limit_per_seed": limit_policy["effective_limit"],
            "limit_auto_applied": limit_policy["auto_applied"],
            "limit_reason": limit_policy["reason"],
            "random_seed": args.random_seed,
            "samples_per_site": args.samples_per_site,
            "selection_mode": resolved_selection_mode,
            "actions": str(args.actions.resolve()),
            "max_ticks": args.max_ticks,
            "continue_after_hit": args.continue_after_hit,
            "baseline": _summarize_boss_baseline(baseline_trace),
            "mutants_generated": len(mutants),
            "cases_run": seed_totals["cases_run"],
            "interesting_cases": seed_totals["interesting_cases"],
            "summary": str(summary_path.resolve()),
        }
        seed_summaries.append(seed_summary)
        (seed_dir / "campaign.json").write_text(json.dumps(seed_summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(seed_summary, indent=2))

    report = {
        "artifact_dir": str(artifact_dir),
        "name_filters": list(name_filters),
        "mutation_mode": args.mutation_mode,
        "requested_limit_per_seed": limit_policy["requested_limit"],
        "effective_limit_per_seed": limit_policy["effective_limit"],
        "limit_auto_applied": limit_policy["auto_applied"],
        "limit_reason": limit_policy["reason"],
        "random_seed": args.random_seed,
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
