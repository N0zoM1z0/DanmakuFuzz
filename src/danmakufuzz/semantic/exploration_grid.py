from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import re
import threading
import traceback
from typing import Any

from ..headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from ..headless.prepare_worker_game_dir import prepare_worker_game_dir
from ..interestingness.rules import load_trace_records
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .ecl_campaign import (
    DEFAULT_EXPLORATION_GRID_LIMIT,
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
    return ARTIFACTS_DIR / "semantic-exploration-grid" / stamp


def default_seed_ecls() -> list[Path]:
    return sorted((REFERENCE_DIR / "corpus" / "ecl" / "original").glob("ecldata*.ecl"))


def _value_slug(value: int) -> str:
    if value < 0:
        return f"neg{-value}"
    return str(value)


def _sanitize_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()


@dataclass(frozen=True)
class TaskSpec:
    task_index: int
    seed_ecl: Path
    stage: int
    random_seed: int
    slug: str


@dataclass(frozen=True)
class BaselineCacheKey:
    stage: int
    seed: int
    action_file: Path
    difficulty: int
    character: int
    shot_type: int
    max_ticks: int
    auto_shoot: bool
    continue_after_hit: bool


@dataclass
class WorkerBaseline:
    artifact_dir: Path
    metadata: dict[str, object]
    trace: Path
    records: list[dict[str, object]]


@dataclass
class WorkerContext:
    worker_index: int
    worker_name: str
    game_dir: Path
    manifest: dict[str, object]
    baseline_cache: dict[BaselineCacheKey, WorkerBaseline] = field(default_factory=dict)


def _emit_json(lock: threading.Lock, payload: dict[str, object]) -> None:
    with lock:
        print(json.dumps(payload, ensure_ascii=False), flush=True)


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


def _task_slug(*, task_index: int, seed_ecl: Path, random_seed: int) -> str:
    return f"{task_index:04d}-{seed_ecl.stem}-rs{_value_slug(random_seed)}"


def _build_tasks(seed_ecls: list[Path], random_seeds: list[int]) -> tuple[list[TaskSpec], list[dict[str, object]], int]:
    tasks: list[TaskSpec] = []
    skipped: list[dict[str, object]] = []
    usable_seed_count = 0
    next_task_index = 1
    for seed_ecl in seed_ecls:
        resolved = seed_ecl.resolve()
        if not resolved.is_file():
            skipped.append({"seed_ecl": str(resolved), "reason": "missing-seed"})
            continue
        stage = infer_stage_from_ecl_name(resolved)
        if not practice_stage_supported(stage):
            skipped.append(
                {
                    "seed_ecl": str(resolved),
                    "stage": stage,
                    "reason": "unsupported-practice-stage",
                }
            )
            continue
        usable_seed_count += 1
        for random_seed in random_seeds:
            tasks.append(
                TaskSpec(
                    task_index=next_task_index,
                    seed_ecl=resolved,
                    stage=stage,
                    random_seed=random_seed,
                    slug=_task_slug(task_index=next_task_index, seed_ecl=resolved, random_seed=random_seed),
                )
            )
            next_task_index += 1
    return tasks, skipped, usable_seed_count


def _baseline_dir_name(key: BaselineCacheKey) -> str:
    action_slug = _sanitize_token(key.action_file.stem)
    return (
        f"stage{key.stage}-seed{key.seed}-{action_slug}-ticks{key.max_ticks}"
        f"-d{key.difficulty}-c{key.character}-s{key.shot_type}"
        f"-auto{int(key.auto_shoot)}-cont{int(key.continue_after_hit)}"
    )


def _finding_counter_from_result(result: dict[str, object]) -> Counter[str]:
    counter: Counter[str] = Counter()
    findings = result.get("findings")
    if not isinstance(findings, list):
        return counter
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        kind = finding.get("kind")
        if isinstance(kind, str) and kind:
            counter[kind] += 1
    return counter


def _get_worker_baseline(
    *,
    worker: WorkerContext,
    artifact_dir: Path,
    task: TaskSpec,
    action_file: Path,
    headless_seed: int,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    binary: Path,
) -> tuple[WorkerBaseline, bool]:
    key = BaselineCacheKey(
        stage=task.stage,
        seed=headless_seed,
        action_file=action_file.resolve(),
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
    )
    cached = worker.baseline_cache.get(key)
    if cached is not None:
        return cached, True

    baseline_dir = artifact_dir / "_worker-baselines" / worker.worker_name / _baseline_dir_name(key)
    log_path = baseline_dir / "run.log"
    metadata = run_baseline(
        binary=binary,
        game_dir=worker.game_dir,
        resource_override_dir=None,
        stage=task.stage,
        seed=headless_seed,
        action_file=action_file,
        artifact_dir=baseline_dir,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        trace_compact_counts=True,
        log_path=log_path,
        dry_run=False,
    )
    trace_value = metadata.get("trace")
    trace_path = Path(trace_value) if isinstance(trace_value, str) else None
    if trace_path is None or not trace_path.is_file():
        raise RuntimeError(f"worker baseline trace missing for {worker.worker_name} stage {task.stage}")
    baseline = WorkerBaseline(
        artifact_dir=baseline_dir.resolve(),
        metadata=metadata,
        trace=trace_path.resolve(),
        records=load_trace_records(trace_path),
    )
    worker.baseline_cache[key] = baseline
    return baseline, False


def _run_task(
    *,
    worker: WorkerContext,
    task: TaskSpec,
    artifact_dir: Path,
    binary: Path,
    profile: dict[str, object],
    resolved_selection_mode: str,
    headless_seed: int,
    difficulty: int,
    character: int,
    shot_type: int,
    timeout_seconds: float,
    include_structural: bool,
    mutation_mode: str,
    samples_per_site: int,
    limit_per_task: int | None,
    auto_shoot: bool,
    print_lock: threading.Lock,
) -> dict[str, object]:
    task_dir = artifact_dir / "tasks" / task.slug
    ensure_directory(task_dir)
    action_file = Path(profile["action_file"]).resolve()
    max_ticks = int(profile["max_ticks"])
    continue_after_hit = bool(profile["continue_after_hit"])
    baseline, baseline_cache_hit = _get_worker_baseline(
        worker=worker,
        artifact_dir=artifact_dir,
        task=task,
        action_file=action_file,
        headless_seed=headless_seed,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        binary=binary,
    )

    _emit_json(
        print_lock,
        {
            "event": "task-start",
            "worker": worker.worker_name,
            "task_slug": task.slug,
            "seed_ecl": str(task.seed_ecl),
            "stage": task.stage,
            "random_seed": task.random_seed,
            "baseline_cache_hit": baseline_cache_hit,
        },
    )

    mutants = select_mutants(
        task.seed_ecl.read_bytes(),
        include_structural=include_structural,
        name_filters=profile["name_filters"],
        mutation_mode=mutation_mode,
        random_seed=task.random_seed,
        samples_per_site=samples_per_site,
        limit=limit_per_task,
        family_filters=profile["name_filters"],
        selection_mode=resolved_selection_mode,
    )

    summary_path = task_dir / "summary.jsonl"
    task_totals = {"cases_run": 0, "interesting_cases": 0}
    finding_counts: Counter[str] = Counter()
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, mutant in enumerate(mutants, start=1):
            result = run_case(
                binary=binary,
                game_dir=worker.game_dir,
                stage=task.stage,
                seed=headless_seed,
                action_file=action_file,
                difficulty=difficulty,
                character=character,
                shot_type=shot_type,
                max_ticks=max_ticks,
                auto_shoot=auto_shoot,
                continue_after_hit=continue_after_hit,
                timeout_seconds=timeout_seconds,
                trace_compact_counts=True,
                campaign_dir=task_dir,
                seed_name=task.seed_ecl.name,
                mutant=mutant,
                case_index=case_index,
                baseline_trace=baseline.trace,
                baseline_records=baseline.records,
            )
            task_totals["cases_run"] += 1
            task_totals["interesting_cases"] += int(bool(result["interesting"]))
            finding_counts.update(_finding_counter_from_result(result))
            summary_handle.write(json.dumps(result) + "\n")
            _emit_json(
                print_lock,
                {
                    "event": "case-finished",
                    "worker": worker.worker_name,
                    "task_slug": task.slug,
                    "seed_ecl": str(task.seed_ecl),
                    "stage": task.stage,
                    "random_seed": task.random_seed,
                    "case_name": result["case_name"],
                    "mutant_name": result["mutant_name"],
                    "interesting": result["interesting"],
                    "findings": result["findings"],
                },
            )

    task_summary = {
        "status": "ok",
        "task_index": task.task_index,
        "task_slug": task.slug,
        "worker": worker.worker_name,
        "worker_game_dir": str(worker.game_dir),
        "profile": profile["profile"],
        "seed_ecl": str(task.seed_ecl),
        "stage": task.stage,
        "random_seed": task.random_seed,
        "name_filters": list(profile["name_filters"]),
        "include_structural": include_structural,
        "mutation_mode": mutation_mode,
        "samples_per_site": samples_per_site,
        "selection_mode": resolved_selection_mode,
        "actions": str(action_file),
        "headless_seed": headless_seed,
        "difficulty": difficulty,
        "character": character,
        "shot_type": shot_type,
        "max_ticks": max_ticks,
        "timeout_seconds": timeout_seconds,
        "continue_after_hit": continue_after_hit,
        "limit_per_task": limit_per_task,
        "baseline": {
            "artifact_dir": str(baseline.artifact_dir),
            "trace": str(baseline.trace),
            "log": baseline.metadata.get("log"),
            "cache_hit": baseline_cache_hit,
            "command": baseline.metadata.get("command"),
        },
        "mutants_generated": len(mutants),
        "cases_run": task_totals["cases_run"],
        "interesting_cases": task_totals["interesting_cases"],
        "finding_kinds": dict(finding_counts.most_common()),
        "summary": str(summary_path.resolve()),
    }
    (task_dir / "campaign.json").write_text(json.dumps(task_summary, indent=2) + "\n", encoding="utf-8")
    _emit_json(
        print_lock,
        {
            "event": "task-finished",
            "worker": worker.worker_name,
            "task_slug": task.slug,
            "seed_ecl": str(task.seed_ecl),
            "random_seed": task.random_seed,
            "cases_run": task_summary["cases_run"],
            "interesting_cases": task_summary["interesting_cases"],
            "finding_kinds": task_summary["finding_kinds"],
        },
    )
    return task_summary


def _task_error_summary(
    *,
    task: TaskSpec,
    worker: WorkerContext,
    artifact_dir: Path,
    profile: dict[str, object],
    resolved_selection_mode: str,
    include_structural: bool,
    mutation_mode: str,
    samples_per_site: int,
    limit_per_task: int | None,
    timeout_seconds: float,
    error: Exception,
) -> dict[str, object]:
    task_dir = artifact_dir / "tasks" / task.slug
    ensure_directory(task_dir)
    summary = {
        "status": "error",
        "task_index": task.task_index,
        "task_slug": task.slug,
        "worker": worker.worker_name,
        "worker_game_dir": str(worker.game_dir),
        "profile": profile["profile"],
        "seed_ecl": str(task.seed_ecl),
        "stage": task.stage,
        "random_seed": task.random_seed,
        "name_filters": list(profile["name_filters"]),
        "include_structural": include_structural,
        "mutation_mode": mutation_mode,
        "samples_per_site": samples_per_site,
        "selection_mode": resolved_selection_mode,
        "limit_per_task": limit_per_task,
        "timeout_seconds": timeout_seconds,
        "error": {
            "message": str(error),
            "type": type(error).__name__,
            "traceback": traceback.format_exc(),
        },
    }
    (task_dir / "error.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a parallel seed-ECL × sampler-seed semantic exploration grid with isolated worker game copies."
    )
    parser.add_argument("--seed-ecl", action="append", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--reuse-workers", action="store_true")
    parser.add_argument("--seed", type=int, default=7, help="headless runtime RNG seed")
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--max-ticks", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--profile", choices=("default", "core", "boss"), default="core")
    parser.add_argument("--limit-per-task", type=int)
    parser.add_argument("--full-mutant-set", action="store_true")
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--include-structural", action="store_true")
    parser.add_argument("--mutation-mode", choices=("deterministic", "exploration"), default="exploration")
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
    worker_count = max(1, args.worker_count)
    resolved_selection_mode = resolve_selection_mode(
        mutation_mode=args.mutation_mode,
        selection_mode=args.selection_mode,
    )
    limit_policy = resolve_mutant_limit(
        mutation_mode=args.mutation_mode,
        requested_limit=args.limit_per_task,
        full_mutant_set=args.full_mutant_set,
        default_exploration_limit=DEFAULT_EXPLORATION_GRID_LIMIT,
    )
    profile = resolve_campaign_profile(
        profile=args.profile,
        action_file=args.actions.resolve(),
        max_ticks=args.max_ticks,
        timeout_seconds=args.timeout_seconds,
        continue_after_hit=args.continue_after_hit,
        case_prefix="grid",
        name_filters=args.name_filter,
    )
    tasks, skipped, usable_seed_count = _build_tasks(seed_ecls, random_seeds)

    workers: list[WorkerContext] = []
    for worker_index in range(worker_count):
        worker_name = f"worker-{worker_index:02d}"
        worker_game_dir = artifact_dir / "workers" / worker_name / "game"
        manifest = prepare_worker_game_dir(
            source_game_dir=args.game_dir.resolve(),
            destination=worker_game_dir,
            worker_name=worker_name,
            reuse=args.reuse_workers,
        )
        workers.append(
            WorkerContext(
                worker_index=worker_index,
                worker_name=worker_name,
                game_dir=worker_game_dir.resolve(),
                manifest=manifest,
            )
        )

    task_queue: queue.Queue[TaskSpec | None] = queue.Queue()
    for task in tasks:
        task_queue.put(task)
    for _ in workers:
        task_queue.put(None)

    results: list[dict[str, object]] = []
    results_lock = threading.Lock()
    print_lock = threading.Lock()

    def worker_loop(worker: WorkerContext) -> None:
        while True:
            task = task_queue.get()
            try:
                if task is None:
                    return
                try:
                    summary = _run_task(
                        worker=worker,
                        task=task,
                        artifact_dir=artifact_dir,
                        binary=args.headless_bin.resolve(),
                        profile=profile,
                        resolved_selection_mode=resolved_selection_mode,
                        headless_seed=args.seed,
                        difficulty=args.difficulty,
                        character=args.character,
                        shot_type=args.shot_type,
                        timeout_seconds=float(profile["timeout_seconds"]),
                        include_structural=args.include_structural,
                        mutation_mode=args.mutation_mode,
                        samples_per_site=args.samples_per_site,
                        limit_per_task=limit_policy["effective_limit"],
                        auto_shoot=args.auto_shoot,
                        print_lock=print_lock,
                    )
                except Exception as error:
                    summary = _task_error_summary(
                        task=task,
                        worker=worker,
                        artifact_dir=artifact_dir,
                        profile=profile,
                        resolved_selection_mode=resolved_selection_mode,
                        include_structural=args.include_structural,
                        mutation_mode=args.mutation_mode,
                        samples_per_site=args.samples_per_site,
                        limit_per_task=limit_policy["effective_limit"],
                        timeout_seconds=float(profile["timeout_seconds"]),
                        error=error,
                    )
                    _emit_json(
                        print_lock,
                        {
                            "event": "task-error",
                            "worker": worker.worker_name,
                            "task_slug": task.slug,
                            "seed_ecl": str(task.seed_ecl),
                            "random_seed": task.random_seed,
                            "error": summary["error"],
                        },
                    )
                with results_lock:
                    results.append(summary)
            finally:
                task_queue.task_done()

    threads = [
        threading.Thread(target=worker_loop, name=worker.worker_name, args=(worker,), daemon=False)
        for worker in workers
    ]
    for thread in threads:
        thread.start()
    task_queue.join()
    for thread in threads:
        thread.join()

    ordered_results = sorted(
        results,
        key=lambda item: (
            int(item.get("task_index", 0)) if isinstance(item.get("task_index"), int) else 0,
            str(item.get("task_slug", "")),
        ),
    )
    finding_totals: Counter[str] = Counter()
    ok_results = 0
    error_results = 0
    total_cases = 0
    total_interesting = 0
    for result in ordered_results:
        if result.get("status") == "ok":
            ok_results += 1
            cases_run = result.get("cases_run")
            interesting_cases = result.get("interesting_cases")
            if isinstance(cases_run, int):
                total_cases += cases_run
            if isinstance(interesting_cases, int):
                total_interesting += interesting_cases
            finding_kinds = result.get("finding_kinds")
            if isinstance(finding_kinds, dict):
                for kind, count in finding_kinds.items():
                    if isinstance(kind, str) and isinstance(count, int):
                        finding_totals[kind] += count
        else:
            error_results += 1

    report = {
        "artifact_dir": str(artifact_dir),
        "profile": profile["profile"],
        "name_filters": list(profile["name_filters"]),
        "include_structural": args.include_structural,
        "mutation_mode": args.mutation_mode,
        "requested_limit_per_task": limit_policy["requested_limit"],
        "effective_limit_per_task": limit_policy["effective_limit"],
        "limit_auto_applied": limit_policy["auto_applied"],
        "limit_reason": limit_policy["reason"],
        "random_seeds": random_seeds,
        "samples_per_site": args.samples_per_site,
        "selection_mode": resolved_selection_mode,
        "worker_count": worker_count,
        "headless_seed": args.seed,
        "difficulty": args.difficulty,
        "character": args.character,
        "shot_type": args.shot_type,
        "max_ticks": int(profile["max_ticks"]),
        "continue_after_hit": bool(profile["continue_after_hit"]),
        "timeout_seconds": float(profile["timeout_seconds"]),
        "workers": [
            {
                "worker_name": worker.worker_name,
                "game_dir": str(worker.game_dir),
                "manifest": worker.manifest,
            }
            for worker in workers
        ],
        "totals": {
            "seed_ecls_considered": len(seed_ecls),
            "seed_ecls_usable": usable_seed_count,
            "random_seed_count": len(random_seeds),
            "tasks_queued": len(tasks),
            "tasks_completed": ok_results,
            "tasks_failed": error_results,
            "cases_run": total_cases,
            "interesting_cases": total_interesting,
            "finding_kinds": dict(finding_totals.most_common()),
        },
        "tasks": ordered_results,
        "skipped": skipped,
    }
    (artifact_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if error_results else 0


if __name__ == "__main__":
    raise SystemExit(main())
