from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import time

from ..headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, build_command, default_headless_binary, run_baseline
from ..interestingness.rules import (
    Finding,
    load_trace_records,
    score_trace_path_with_baseline,
)
from ..repo import ARTIFACTS_DIR, CONFIG_DIR, REFERENCE_DIR, ensure_directory
from .payload_mutants import (
    PayloadMutant,
    generate_ir_mutants,
    generate_payload_mutants,
    generate_structural_mutants,
    materialize_ir_mutant,
)


ECLDATA_RE = re.compile(r"ecldata(?P<stage>\d+)\.ecl$")
LONG_ACTION_FILE = CONFIG_DIR / "headless_baseline_actions_1800.txt"
DEFAULT_EXPLORATION_CAMPAIGN_LIMIT = 128
DEFAULT_EXPLORATION_SWEEP_LIMIT = 32
DEFAULT_EXPLORATION_GRID_LIMIT = 32
DEFAULT_CORE_NAME_FILTERS = (
    "jump-offset-",
    "call-sub-",
    "move-time-",
    "shoot-interval-",
    "bullet-count",
    "drop-items-",
    "drop-item-id-",
    "time-set-",
)
DEFAULT_BOSS_NAME_FILTERS = (
    "boss-timer-",
    "life-callback-threshold-",
    "timer-callback-threshold-",
    "boss-life-count-",
    "time-set-",
)


def infer_stage_from_ecl_name(path: Path) -> int:
    match = ECLDATA_RE.fullmatch(path.name)
    if match is None:
        raise ValueError(f"cannot infer stage from ECL filename: {path.name}")
    return int(match.group("stage"))


def default_seed_ecl() -> Path:
    return REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"


def practice_stage_supported(stage: int) -> bool:
    return 1 <= stage <= 6


def filter_mutants_by_name(mutants: list[PayloadMutant], name_filters: Sequence[str] | None) -> list[PayloadMutant]:
    if not name_filters:
        return list(mutants)
    return [mutant for mutant in mutants if any(name_filter in mutant.name for name_filter in name_filters)]


def select_mutants(
    seed_payload: bytes,
    *,
    include_structural: bool = True,
    name_filters: Sequence[str] | None = None,
    mutation_mode: str = "deterministic",
    random_seed: int = 0,
    samples_per_site: int = 4,
    limit: int | None = None,
    family_filters: Sequence[str] | None = None,
    selection_mode: str = "family",
) -> list[PayloadMutant]:
    if limit is not None:
        candidates: list[object] = []
        if include_structural:
            candidates.extend(generate_structural_mutants(seed_payload))
        ir_mutants = generate_ir_mutants(
            seed_payload,
            mutation_mode=mutation_mode,
            random_seed=random_seed,
            samples_per_site=samples_per_site,
            family_filters=family_filters or name_filters,
        )
        candidates.extend(ir_mutants)
        filtered_candidates = filter_mutants_by_name(candidates, name_filters)
        selected_candidates = select_diverse_mutants(
            filtered_candidates,
            limit=limit,
            family_filters=family_filters or name_filters,
            selection_mode=selection_mode,
        )
        selected: list[PayloadMutant] = []
        for mutant in selected_candidates:
            if isinstance(mutant, PayloadMutant):
                selected.append(mutant)
            else:
                selected.append(materialize_ir_mutant(mutant))
        return selected

    mutants = generate_payload_mutants(
        seed_payload,
        include_structural=include_structural,
        mutation_mode=mutation_mode,
        random_seed=random_seed,
        samples_per_site=samples_per_site,
        family_filters=family_filters or name_filters,
    )
    return filter_mutants_by_name(mutants, name_filters)


def mutant_family(mutant: PayloadMutant, family_filters: Sequence[str] | None = None) -> str:
    if family_filters:
        for family_filter in family_filters:
            if family_filter and family_filter in mutant.name:
                return family_filter.rstrip("-")
    metadata = mutant.metadata or {}
    metadata_family = metadata.get("family")
    if isinstance(metadata_family, str) and metadata_family:
        return metadata_family
    parts = [part for part in mutant.name.split("-") if part]
    if len(parts) >= 2:
        return "-".join(parts[:2])
    return mutant.name


def mutant_site(mutant: PayloadMutant) -> str:
    if mutant.path is None:
        return "raw"
    sub_index, instruction_index = mutant.path
    return f"s{sub_index:02d}:i{instruction_index:04d}"


def resolve_selection_mode(*, mutation_mode: str, selection_mode: str) -> str:
    if selection_mode == "auto":
        return "family-site" if mutation_mode == "exploration" else "family"
    if selection_mode not in {"family", "site", "family-site"}:
        raise ValueError(f"unsupported selection_mode: {selection_mode}")
    return selection_mode


def resolve_mutant_limit(
    *,
    mutation_mode: str,
    requested_limit: int | None,
    full_mutant_set: bool,
    default_exploration_limit: int,
) -> dict[str, object]:
    if requested_limit is not None:
        return {
            "requested_limit": requested_limit,
            "effective_limit": requested_limit,
            "auto_applied": False,
            "reason": "explicit-limit",
        }
    if full_mutant_set:
        return {
            "requested_limit": None,
            "effective_limit": None,
            "auto_applied": False,
            "reason": "full-mutant-set",
        }
    if mutation_mode == "exploration":
        return {
            "requested_limit": None,
            "effective_limit": default_exploration_limit,
            "auto_applied": True,
            "reason": "exploration-auto-budget",
        }
    return {
        "requested_limit": None,
        "effective_limit": None,
        "auto_applied": False,
        "reason": "unbounded-default",
    }


def mutant_bucket_key(
    mutant: PayloadMutant,
    *,
    family_filters: Sequence[str] | None = None,
    selection_mode: str = "family",
) -> str:
    if selection_mode == "family":
        return mutant_family(mutant, family_filters)
    if selection_mode == "site":
        return mutant_site(mutant)
    if selection_mode == "family-site":
        return f"{mutant_family(mutant, family_filters)}|{mutant_site(mutant)}"
    raise ValueError(f"unsupported selection_mode: {selection_mode}")


def select_diverse_mutants(
    mutants: Sequence[PayloadMutant],
    *,
    limit: int | None,
    family_filters: Sequence[str] | None = None,
    selection_mode: str = "family",
) -> list[PayloadMutant]:
    if limit is None or limit >= len(mutants):
        return list(mutants)
    if limit <= 0:
        return []
    if selection_mode == "family-site":
        families: dict[str, dict[str, list[PayloadMutant]]] = {}
        family_order: list[str] = []
        site_order_by_family: dict[str, list[str]] = {}
        next_site_index: dict[str, int] = {}
        for mutant in mutants:
            family_key = mutant_family(mutant, family_filters)
            site_key = mutant_site(mutant)
            if family_key not in families:
                families[family_key] = {}
                family_order.append(family_key)
                site_order_by_family[family_key] = []
                next_site_index[family_key] = 0
            family_sites = families[family_key]
            if site_key not in family_sites:
                family_sites[site_key] = []
                site_order_by_family[family_key].append(site_key)
            family_sites[site_key].append(mutant)

        def pop_next_family_site_mutant(family_key: str) -> PayloadMutant | None:
            order = site_order_by_family[family_key]
            if not order:
                return None
            attempts = 0
            index = next_site_index[family_key]
            while attempts < len(order):
                site_key = order[index % len(order)]
                index += 1
                attempts += 1
                bucket = families[family_key][site_key]
                if bucket:
                    next_site_index[family_key] = index % len(order)
                    return bucket.pop(0)
            next_site_index[family_key] = index % len(order)
            return None

        selected: list[PayloadMutant] = []
        while len(selected) < limit:
            progressed = False
            for family_key in family_order:
                mutant = pop_next_family_site_mutant(family_key)
                if mutant is None:
                    continue
                selected.append(mutant)
                progressed = True
                if len(selected) >= limit:
                    break
            if not progressed:
                break
        return selected

    buckets: dict[str, list[PayloadMutant]] = {}
    family_order: list[str] = []
    for mutant in mutants:
        bucket_key = mutant_bucket_key(
            mutant,
            family_filters=family_filters,
            selection_mode=selection_mode,
        )
        if bucket_key not in buckets:
            buckets[bucket_key] = []
            family_order.append(bucket_key)
        buckets[bucket_key].append(mutant)

    selected: list[PayloadMutant] = []
    while len(selected) < limit:
        progressed = False
        for family in family_order:
            bucket = buckets[family]
            if not bucket:
                continue
            selected.append(bucket.pop(0))
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected


def resolve_campaign_profile(
    *,
    profile: str,
    action_file: Path,
    max_ticks: int,
    timeout_seconds: float,
    continue_after_hit: bool,
    case_prefix: str,
    name_filters: Sequence[str] | None,
) -> dict[str, object]:
    resolved_filters = list(name_filters) if name_filters else []
    resolved_action_file = action_file.resolve()
    resolved_max_ticks = max_ticks
    resolved_timeout = timeout_seconds
    resolved_continue_after_hit = continue_after_hit
    resolved_case_prefix = case_prefix
    if resolved_action_file == DEFAULT_ACTION_FILE.resolve() and resolved_max_ticks > 600:
        resolved_action_file = LONG_ACTION_FILE
    if profile == "core":
        if resolved_case_prefix == "campaign":
            resolved_case_prefix = "core"
        if not resolved_filters:
            resolved_filters = list(DEFAULT_CORE_NAME_FILTERS)
    if profile == "boss":
        if resolved_action_file == DEFAULT_ACTION_FILE.resolve():
            resolved_action_file = LONG_ACTION_FILE
        if resolved_max_ticks == 600:
            resolved_max_ticks = 1800
        if resolved_timeout == 5.0:
            resolved_timeout = 15.0
        resolved_continue_after_hit = True
        if resolved_case_prefix == "campaign":
            resolved_case_prefix = "boss"
        if not resolved_filters:
            resolved_filters = list(DEFAULT_BOSS_NAME_FILTERS)
    return {
        "profile": profile,
        "action_file": resolved_action_file,
        "max_ticks": resolved_max_ticks,
        "timeout_seconds": resolved_timeout,
        "continue_after_hit": resolved_continue_after_hit,
        "case_prefix": resolved_case_prefix,
        "name_filters": resolved_filters,
    }


def slugify_case_name(mutant: PayloadMutant, case_index: int) -> str:
    slug = mutant.name.replace("_", "-")
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", slug).strip("-").lower()
    if mutant.path is None:
        return f"{case_index:04d}-{slug}-raw"
    sub_index, instruction_index = mutant.path
    return f"{case_index:04d}-{slug}-s{sub_index:02d}-i{instruction_index:04d}"


def classify_process_result(returncode: int | None, *, timed_out: bool) -> list[Finding]:
    if timed_out:
        return [Finding("timeout", "headless run exceeded timeout")]
    if returncode is None:
        return [Finding("missing-returncode", "headless run did not report a return code")]
    if returncode < 0:
        signal_id = -returncode
        try:
            signal_name = signal.Signals(signal_id).name
        except ValueError:
            signal_name = f"SIG{signal_id}"
        return [Finding("process-signal", signal_name)]
    if returncode > 0:
        return [Finding("process-exit", str(returncode))]
    return []


def materialize_override(case_dir: Path, seed_name: str, payload: bytes) -> Path:
    override_dir = case_dir / "override"
    ensure_directory(override_dir / "data")
    (override_dir / "data" / seed_name).write_bytes(payload)
    return override_dir


def stage_active_override(game_dir: Path, seed_name: str, payload: bytes) -> Path:
    worker_key = hashlib.sha256(str(game_dir.resolve()).encode("utf-8")).hexdigest()[:16]
    active_override_dir = ARTIFACTS_DIR / "_active-overrides" / worker_key
    if active_override_dir.exists():
        shutil.rmtree(active_override_dir)
    ensure_directory(active_override_dir / "data")
    (active_override_dir / "data" / seed_name).write_bytes(payload)
    return active_override_dir


def write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def run_case(
    *,
    binary: Path,
    game_dir: Path,
    stage: int,
    seed: int,
    action_file: Path,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    timeout_seconds: float,
    campaign_dir: Path,
    seed_name: str,
    mutant: PayloadMutant,
    case_index: int,
    baseline_trace: Path | None = None,
    baseline_records: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    case_name = slugify_case_name(mutant, case_index)
    case_dir = campaign_dir / case_name
    ensure_directory(case_dir)
    trace_path = case_dir / "trace.jsonl"
    log_path = case_dir / "run.log"
    override_dir = materialize_override(case_dir, seed_name, mutant.payload)
    active_override_dir = stage_active_override(game_dir, seed_name, mutant.payload)
    command = build_command(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        actions=action_file,
        trace=trace_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
    )
    run_env = os.environ.copy()
    run_env["DANMAKUFUZZ_OVERRIDE_DIR"] = str(active_override_dir.resolve())

    started_at = time.time()
    returncode: int | None = None
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log_handle:
        try:
            completed = subprocess.run(
                command,
                cwd=game_dir,
                env=run_env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    elapsed_seconds = time.time() - started_at

    findings = classify_process_result(returncode, timed_out=timed_out)
    if trace_path.exists() and trace_path.stat().st_size > 0:
        resolved_baseline_records = baseline_records
        if resolved_baseline_records is None and baseline_trace is not None and baseline_trace.is_file():
            resolved_baseline_records = load_trace_records(baseline_trace)
        findings.extend(
            score_trace_path_with_baseline(
                trace_path,
                baseline_records=resolved_baseline_records,
            )
        )
    elif not findings:
        findings.append(Finding("empty-trace", "headless run finished without a non-empty trace"))

    result = {
        "case_name": case_name,
        "mutant_name": mutant.name,
        "source": mutant.source,
        "path": (
            {"sub_index": mutant.path[0], "instruction_index": mutant.path[1]}
            if mutant.path is not None
            else None
        ),
        "mutation_metadata": mutant.metadata,
        "command": command,
        "seed_name": seed_name,
        "stage": stage,
        "cwd": str(game_dir.resolve()),
        "elapsed_seconds": elapsed_seconds,
        "returncode": returncode,
        "timed_out": timed_out,
        "trace": str(trace_path.resolve()),
        "log": str(log_path.resolve()),
        "override_dir": str(override_dir.resolve()),
        "active_override_dir": str(active_override_dir.resolve()),
        "findings": [{"kind": finding.kind, "detail": finding.detail} for finding in findings],
        "interesting": bool(findings),
    }
    write_case_result(case_dir, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a targeted TH06 headless semantic fuzz campaign over one ECL seed.")
    parser.add_argument("--seed-ecl", type=Path, default=default_seed_ecl())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--stage", type=int)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--max-ticks", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--profile", choices=("default", "core", "boss"), default="default")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--full-mutant-set", action="store_true")
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--case-prefix", type=str, default="campaign")
    parser.add_argument("--no-structural", action="store_true")
    parser.add_argument("--mutation-mode", choices=("deterministic", "exploration"), default="deterministic")
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--samples-per-site", type=int, default=4)
    parser.add_argument("--selection-mode", choices=("auto", "family", "site", "family-site"), default="auto")
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_ecl = args.seed_ecl.resolve()
    if not seed_ecl.is_file():
        raise FileNotFoundError(f"missing seed ECL: {seed_ecl}")
    stage = args.stage if args.stage is not None else infer_stage_from_ecl_name(seed_ecl)
    resolved_selection_mode = resolve_selection_mode(
        mutation_mode=args.mutation_mode,
        selection_mode=args.selection_mode,
    )
    limit_policy = resolve_mutant_limit(
        mutation_mode=args.mutation_mode,
        requested_limit=args.limit,
        full_mutant_set=args.full_mutant_set,
        default_exploration_limit=DEFAULT_EXPLORATION_CAMPAIGN_LIMIT,
    )
    profile = resolve_campaign_profile(
        profile=args.profile,
        action_file=args.actions.resolve(),
        max_ticks=args.max_ticks,
        timeout_seconds=args.timeout_seconds,
        continue_after_hit=args.continue_after_hit,
        case_prefix=args.case_prefix,
        name_filters=args.name_filter,
    )
    artifact_dir = args.artifact_dir or (
        ARTIFACTS_DIR / "semantic" / f"{profile['case_prefix']}-stage{stage}-seed{args.seed}-{seed_ecl.stem}"
    )
    ensure_directory(artifact_dir)
    baseline_artifact_dir = artifact_dir / "_baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=stage,
        seed=args.seed,
        action_file=profile["action_file"],
        artifact_dir=baseline_artifact_dir.resolve(),
        difficulty=args.difficulty,
        character=args.character,
        shot_type=args.shot_type,
        max_ticks=profile["max_ticks"],
        auto_shoot=args.auto_shoot,
        continue_after_hit=profile["continue_after_hit"],
        dry_run=False,
    )
    baseline_trace_value = baseline_metadata.get("trace")
    baseline_trace = Path(baseline_trace_value) if isinstance(baseline_trace_value, str) else None
    baseline_records = (
        load_trace_records(baseline_trace)
        if baseline_trace is not None and baseline_trace.is_file()
        else None
    )

    seed_payload = seed_ecl.read_bytes()
    mutants = select_mutants(
        seed_payload,
        include_structural=not args.no_structural,
        name_filters=profile["name_filters"],
        mutation_mode=args.mutation_mode,
        random_seed=args.random_seed,
        samples_per_site=args.samples_per_site,
        limit=limit_policy["effective_limit"],
        family_filters=profile["name_filters"],
        selection_mode=resolved_selection_mode,
    )

    summary_path = artifact_dir / "summary.jsonl"
    totals = {"cases": 0, "interesting": 0}
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, mutant in enumerate(mutants, start=1):
            result = run_case(
                binary=args.headless_bin.resolve(),
                game_dir=args.game_dir.resolve(),
                stage=stage,
                seed=args.seed,
                action_file=profile["action_file"],
                difficulty=args.difficulty,
                character=args.character,
                shot_type=args.shot_type,
                max_ticks=profile["max_ticks"],
                auto_shoot=args.auto_shoot,
                continue_after_hit=profile["continue_after_hit"],
                timeout_seconds=profile["timeout_seconds"],
                campaign_dir=artifact_dir.resolve(),
                seed_name=seed_ecl.name,
                mutant=mutant,
                case_index=case_index,
                baseline_trace=baseline_trace,
                baseline_records=baseline_records,
            )
            totals["cases"] += 1
            totals["interesting"] += int(bool(result["interesting"]))
            summary_handle.write(json.dumps(result) + "\n")
            print(json.dumps(
                {
                    "case_name": result["case_name"],
                    "mutant_name": result["mutant_name"],
                    "interesting": result["interesting"],
                    "returncode": result["returncode"],
                    "timed_out": result["timed_out"],
                    "findings": result["findings"],
                },
                ensure_ascii=False,
            ))

    campaign_result = {
        "seed_ecl": str(seed_ecl),
        "stage": stage,
        "profile": profile["profile"],
        "name_filters": profile["name_filters"],
        "mutation_mode": args.mutation_mode,
        "requested_limit": limit_policy["requested_limit"],
        "effective_limit": limit_policy["effective_limit"],
        "limit_auto_applied": limit_policy["auto_applied"],
        "limit_reason": limit_policy["reason"],
        "random_seed": args.random_seed,
        "samples_per_site": args.samples_per_site,
        "selection_mode": resolved_selection_mode,
        "actions": str(profile["action_file"]),
        "max_ticks": profile["max_ticks"],
        "continue_after_hit": profile["continue_after_hit"],
        "mutants_generated": len(mutants),
        "cases_run": totals["cases"],
        "interesting_cases": totals["interesting"],
        "summary": str(summary_path.resolve()),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(campaign_result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(campaign_result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
