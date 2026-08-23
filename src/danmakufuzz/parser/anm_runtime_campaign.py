from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import time

from ..corpus.pbg3 import Pbg3Archive
from ..headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    build_command,
    default_headless_binary,
    run_baseline,
)
from ..headless.prepare_worker_game_dir import prepare_worker_game_dir
from ..interestingness.rules import Finding, load_trace_records, score_trace_path_with_baseline
from ..repo import ARTIFACTS_DIR, ensure_directory
from .anm import DEFAULT_ARCHIVE, parse_anm
from .anm_campaign import evaluate_anm_payload
from .anm_mutants import AnmMutant, generate_anm_mutants


ENTRY_STAGE_RE = re.compile(r"^stg(?P<stage>\d+)(?P<kind>bg|enm(?:\d+)?)\.anm$", re.IGNORECASE)
DEFAULT_TARGET_KINDS = (
    "anm-script-drift",
    "anm-non-finite",
    "anm-set-active-sprite-failure",
)
DEFAULT_FOCUSED_MUTANT_NAMES = (
    "first-sprite-offset-zero",
    "first-script-id-ffff",
    "first-script-offset-zero",
    "first-instr-argsize-zero",
)
DEFAULT_TRACE_COMPACT_COUNTS = True


@dataclass(frozen=True)
class SelectedAnmMutant:
    mutant: AnmMutant
    evaluation: dict[str, object]


@dataclass
class StageRuntimeContext:
    stage: int
    worker_game_dir: Path
    worker_prepare: dict[str, object]
    baseline_dir: Path
    baseline_metadata: dict[str, object]
    baseline_records: list[dict[str, object]]


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-anm-runtime" / stamp


def _slug_entry_name(entry_name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", entry_name).strip("._-")
    return slug or "entry"


def practice_stage_supported(stage: int) -> bool:
    return 1 <= stage <= 7


def _parse_entry_stage_override(raw: str) -> tuple[str, int]:
    if "=" not in raw:
        raise ValueError(f"expected ENTRY=STAGE override, got: {raw}")
    entry_name, raw_stage = raw.split("=", 1)
    entry_name = entry_name.strip()
    if not entry_name:
        raise ValueError(f"empty entry name in override: {raw}")
    try:
        stage = int(raw_stage)
    except ValueError as exc:
        raise ValueError(f"invalid stage override in {raw}") from exc
    return entry_name, stage


def _resolve_entry_stage(entry_name: str, *, stage_overrides: dict[str, int]) -> int:
    override = stage_overrides.get(entry_name)
    if override is not None:
        return override
    match = ENTRY_STAGE_RE.fullmatch(entry_name)
    if match is None:
        raise ValueError(f"cannot infer practice stage from ANM entry name: {entry_name}")
    return int(match.group("stage"))


def _entry_sort_key(entry_name: str, stage: int) -> tuple[int, int, str]:
    match = ENTRY_STAGE_RE.fullmatch(entry_name)
    kind_order = 9
    if match is not None:
        kind = match.group("kind").lower()
        if kind == "bg":
            kind_order = 0
        elif kind == "enm":
            kind_order = 1
        else:
            kind_order = 2
    return stage, kind_order, entry_name


def _select_entry_names(
    archive: Pbg3Archive,
    *,
    requested_entries: list[str] | None,
    stage_overrides: dict[str, int],
) -> tuple[list[tuple[str, int]], list[dict[str, object]]]:
    archive_entry_names = {entry.filename for entry in archive.entries}
    skipped: list[dict[str, object]] = []

    if requested_entries:
        selected: list[tuple[str, int]] = []
        for entry_name in requested_entries:
            if entry_name not in archive_entry_names:
                raise KeyError(f"archive is missing requested ANM entry: {entry_name}")
            stage = _resolve_entry_stage(entry_name, stage_overrides=stage_overrides)
            if not practice_stage_supported(stage):
                raise ValueError(
                    f"entry {entry_name} maps to unsupported practice stage {stage}; "
                    "current headless practice startup only supports stages 1..6"
                )
            selected.append((entry_name, stage))
        return sorted(selected, key=lambda item: _entry_sort_key(item[0], item[1])), skipped

    selected = []
    for entry in archive.entries:
        match = ENTRY_STAGE_RE.fullmatch(entry.filename)
        if match is None:
            continue
        stage = _resolve_entry_stage(entry.filename, stage_overrides=stage_overrides)
        if not practice_stage_supported(stage):
            skipped.append(
                {
                    "entry_name": entry.filename,
                    "stage": stage,
                    "reason": "unsupported-practice-stage",
                }
            )
            continue
        selected.append((entry.filename, stage))

    if not selected:
        raise RuntimeError("no ANM runtime entries matched the default stgXbg/stgXenm/stgXenm2 selector")
    return sorted(selected, key=lambda item: _entry_sort_key(item[0], item[1])), skipped


def _select_mutants(
    payload: bytes,
    *,
    max_script_instructions: int,
    mutant_profile: str,
    name_filters: list[str] | None,
) -> tuple[list[SelectedAnmMutant], dict[str, object]]:
    baseline_summary = parse_anm(payload, max_script_instructions=max_script_instructions)
    classification_counts: Counter[str] = Counter()
    selected: list[SelectedAnmMutant] = []
    accepted_total = 0
    generated = generate_anm_mutants(payload)

    for mutant in generated:
        if name_filters and not any(name_filter in mutant.name for name_filter in name_filters):
            continue
        evaluation = evaluate_anm_payload(
            mutant.payload,
            baseline_summary,
            max_script_instructions=max_script_instructions,
        )
        classification = str(evaluation["classification"])
        classification_counts[classification] += 1
        if classification != "accepted":
            continue
        if not bool(evaluation.get("interesting")):
            continue
        accepted_total += 1
        if mutant_profile == "focused" and mutant.name not in DEFAULT_FOCUSED_MUTANT_NAMES:
            continue
        selected.append(SelectedAnmMutant(mutant=mutant, evaluation=evaluation))

    inventory = {
        "generated_mutants": len(generated),
        "accepted_interesting_mutants": accepted_total,
        "selected_mutants": len(selected),
        "classification_counts": dict(sorted(classification_counts.items())),
        "selected_mutant_names": [selected_mutant.mutant.name for selected_mutant in selected],
        "mutant_profile": mutant_profile,
        "name_filters": list(name_filters or []),
    }
    return selected, {
        "summary": baseline_summary,
        "inventory": inventory,
    }


def _materialize_override(case_dir: Path, entry_name: str, payload: bytes) -> Path:
    override_dir = case_dir / "override"
    ensure_directory(override_dir / "data")
    (override_dir / "data" / entry_name).write_bytes(payload)
    return override_dir


def _stage_active_override(game_dir: Path, entry_name: str, payload: bytes) -> Path:
    worker_key = hashlib.sha256(str(game_dir.resolve()).encode("utf-8")).hexdigest()[:16]
    active_override_dir = ARTIFACTS_DIR / "_active-overrides" / worker_key
    if active_override_dir.exists():
        shutil.rmtree(active_override_dir)
    ensure_directory(active_override_dir / "data")
    (active_override_dir / "data" / entry_name).write_bytes(payload)
    return active_override_dir


def _classify_process_result(returncode: int | None, *, timed_out: bool) -> list[Finding]:
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


def _trace_line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _finding_records(findings: list[Finding]) -> list[dict[str, str]]:
    return [{"kind": finding.kind, "detail": finding.detail} for finding in findings]


def _result_summary_record(result: dict[str, object]) -> dict[str, object]:
    return {
        "case_name": result["case_name"],
        "entry_name": result["entry_name"],
        "stage": result["stage"],
        "mutant_name": result["mutant_name"],
        "source": result["source"],
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "trace_lines": result["trace_lines"],
        "finding_kinds": result["finding_kinds"],
        "target_hits": result["target_hits"],
        "target_hit": result["target_hit"],
        "interesting": result["interesting"],
        "result_path": result["result_path"],
        "trace": result["trace"],
        "log": result["log"],
        "override_dir": result["override_dir"],
    }


def _ensure_stage_context(
    stage_contexts: dict[int, StageRuntimeContext],
    *,
    stage: int,
    artifact_dir: Path,
    binary: Path,
    source_game_dir: Path,
    action_file: Path,
    seed: int,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    trace_compact_counts: bool,
) -> StageRuntimeContext:
    existing = stage_contexts.get(stage)
    if existing is not None:
        return existing

    worker_game_dir = artifact_dir / "workers" / f"stage{stage}"
    worker_prepare = prepare_worker_game_dir(
        source_game_dir=source_game_dir,
        destination=worker_game_dir,
        worker_name=f"anm-runtime-stage{stage}",
        reuse=True,
    )
    baseline_dir = artifact_dir / "baselines" / f"stage{stage}"
    baseline_metadata = run_baseline(
        binary=binary,
        game_dir=worker_game_dir,
        resource_override_dir=None,
        stage=stage,
        seed=seed,
        action_file=action_file,
        artifact_dir=baseline_dir,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        trace_compact_counts=trace_compact_counts,
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    context = StageRuntimeContext(
        stage=stage,
        worker_game_dir=worker_game_dir,
        worker_prepare=worker_prepare,
        baseline_dir=baseline_dir,
        baseline_metadata=baseline_metadata,
        baseline_records=load_trace_records(baseline_trace),
    )
    stage_contexts[stage] = context
    return context


def _run_runtime_case(
    *,
    artifact_dir: Path,
    entry_name: str,
    stage_context: StageRuntimeContext,
    selected_mutant: SelectedAnmMutant,
    case_index: int,
    binary: Path,
    action_file: Path,
    seed: int,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    timeout_seconds: float,
    trace_compact_counts: bool,
    target_kinds: set[str],
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{selected_mutant.mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)

    override_dir = _materialize_override(case_dir, entry_name, selected_mutant.mutant.payload)
    active_override_dir = _stage_active_override(
        stage_context.worker_game_dir,
        entry_name,
        selected_mutant.mutant.payload,
    )
    trace_path = case_dir / "trace.jsonl"
    log_path = case_dir / "run.log"
    command = build_command(
        binary=binary,
        game_dir=stage_context.worker_game_dir,
        stage=stage_context.stage,
        seed=seed,
        actions=action_file,
        trace=trace_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        trace_compact_counts=trace_compact_counts,
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
                cwd=stage_context.worker_game_dir,
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

    findings = _classify_process_result(returncode, timed_out=timed_out)
    if trace_path.is_file() and trace_path.stat().st_size > 0:
        findings.extend(
            score_trace_path_with_baseline(
                trace_path,
                baseline_records=stage_context.baseline_records,
            )
        )
    elif not findings:
        findings.append(Finding("empty-trace", "headless run finished without a non-empty trace"))

    finding_kinds = [finding.kind for finding in findings]
    target_hits = sorted({kind for kind in finding_kinds if kind in target_kinds})
    result = {
        "case_name": case_name,
        "entry_name": entry_name,
        "stage": stage_context.stage,
        "mutant_name": selected_mutant.mutant.name,
        "source": selected_mutant.mutant.source,
        "payload_sha256": selected_mutant.mutant.sha256,
        "payload_size": len(selected_mutant.mutant.payload),
        "command": command,
        "cwd": str(stage_context.worker_game_dir.resolve()),
        "elapsed_seconds": elapsed_seconds,
        "returncode": returncode,
        "timed_out": timed_out,
        "trace": str(trace_path.resolve()),
        "trace_exists": trace_path.is_file(),
        "trace_lines": _trace_line_count(trace_path),
        "log": str(log_path.resolve()),
        "override_dir": str(override_dir.resolve()),
        "active_override_dir": str(active_override_dir.resolve()),
        "baseline_trace": str(Path(str(stage_context.baseline_metadata["trace"])).resolve()),
        "parser_evaluation": selected_mutant.evaluation,
        "findings": _finding_records(findings),
        "finding_kinds": finding_kinds,
        "target_hits": target_hits,
        "target_hit": bool(target_hits),
        "interesting": bool(findings),
    }
    result_path = case_dir / "result.json"
    result["result_path"] = str(result_path.resolve())
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a stage-entry ANM runtime campaign over stgXbg/stgXenm/stgXenm2 archive seeds."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", action="append")
    parser.add_argument(
        "--entry-stage",
        action="append",
        help="override stage inference as ENTRY=STAGE; useful when future titles diverge from stgX naming",
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--max-ticks", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--max-script-instructions", type=int, default=4096)
    parser.add_argument("--mutant-profile", choices=("focused", "accepted"), default="focused")
    parser.add_argument("--name-filter", action="append")
    parser.add_argument("--limit-per-entry", type=int)
    parser.add_argument("--target-kind", action="append")
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--trace-compact-counts", dest="trace_compact_counts", action="store_true")
    parser.add_argument("--full-entity-trace", dest="trace_compact_counts", action="store_false")
    parser.set_defaults(trace_compact_counts=DEFAULT_TRACE_COMPACT_COUNTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    game_dir = args.game_dir.resolve()
    headless_bin = args.headless_bin.resolve()
    actions = args.actions.resolve()
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    if not archive_path.is_file():
        raise FileNotFoundError(f"missing archive: {archive_path}")
    if not game_dir.is_dir():
        raise FileNotFoundError(f"missing game directory: {game_dir}")
    if not headless_bin.is_file():
        raise FileNotFoundError(f"missing headless binary: {headless_bin}")

    stage_overrides: dict[str, int] = {}
    for raw_override in args.entry_stage or []:
        entry_name, stage = _parse_entry_stage_override(raw_override)
        stage_overrides[entry_name] = stage

    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    selected_entries, skipped_entries = _select_entry_names(
        archive,
        requested_entries=args.entry,
        stage_overrides=stage_overrides,
    )
    target_kinds = set(args.target_kind or DEFAULT_TARGET_KINDS)

    stage_contexts: dict[int, StageRuntimeContext] = {}
    summary_path = artifact_dir / "summary.jsonl"
    target_hits_path = artifact_dir / "target-hits.jsonl"
    target_kind_counts: Counter[str] = Counter()
    finding_kind_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    total_cases = 0
    interesting_cases = 0
    target_hit_cases = 0
    entry_reports: list[dict[str, object]] = []

    with (
        summary_path.open("w", encoding="utf-8") as summary_handle,
        target_hits_path.open("w", encoding="utf-8") as target_hits_handle,
    ):
        for entry_name, stage in selected_entries:
            entry_dir = artifact_dir / _slug_entry_name(entry_name)
            ensure_directory(entry_dir)
            seed_payload = archive.extract(entry_name)
            seed_path = entry_dir / "seed.anm"
            seed_path.write_bytes(seed_payload)

            selected_mutants, parser_report = _select_mutants(
                seed_payload,
                max_script_instructions=args.max_script_instructions,
                mutant_profile=args.mutant_profile,
                name_filters=args.name_filter,
            )
            baseline_summary = {
                "input": f"{archive_path}!{entry_name}",
                **parser_report["summary"],
            }
            (entry_dir / "parser-baseline.json").write_text(
                json.dumps(baseline_summary, indent=2) + "\n",
                encoding="utf-8",
            )

            if args.limit_per_entry is not None:
                selected_mutants = selected_mutants[: args.limit_per_entry]

            for classification, count in dict(parser_report["inventory"]["classification_counts"]).items():
                classification_counts[str(classification)] += int(count)

            entry_summary_path = entry_dir / "summary.jsonl"
            if not selected_mutants:
                entry_summary_path.write_text("", encoding="utf-8")
                entry_report = {
                    "entry_name": entry_name,
                    "stage": stage,
                    "seed_path": str(seed_path.resolve()),
                    "parser_baseline": str((entry_dir / "parser-baseline.json").resolve()),
                    "parser_inventory": parser_report["inventory"],
                    "baseline_trace": None,
                    "summary": str(entry_summary_path.resolve()),
                    "cases_run": 0,
                    "interesting_cases": 0,
                    "target_hit_cases": 0,
                    "target_hits": [],
                }
                (entry_dir / "entry.json").write_text(json.dumps(entry_report, indent=2) + "\n", encoding="utf-8")
                entry_reports.append(entry_report)
                continue

            stage_context = _ensure_stage_context(
                stage_contexts,
                stage=stage,
                artifact_dir=artifact_dir,
                binary=headless_bin,
                source_game_dir=game_dir,
                action_file=actions,
                seed=args.seed,
                difficulty=args.difficulty,
                character=args.character,
                shot_type=args.shot_type,
                max_ticks=args.max_ticks,
                auto_shoot=args.auto_shoot,
                continue_after_hit=args.continue_after_hit,
                trace_compact_counts=args.trace_compact_counts,
            )

            entry_cases: list[dict[str, object]] = []
            with entry_summary_path.open("w", encoding="utf-8") as entry_summary_handle:
                for case_index, selected_mutant in enumerate(selected_mutants, start=1):
                    result = _run_runtime_case(
                        artifact_dir=entry_dir,
                        entry_name=entry_name,
                        stage_context=stage_context,
                        selected_mutant=selected_mutant,
                        case_index=case_index,
                        binary=headless_bin,
                        action_file=actions,
                        seed=args.seed,
                        difficulty=args.difficulty,
                        character=args.character,
                        shot_type=args.shot_type,
                        max_ticks=args.max_ticks,
                        auto_shoot=args.auto_shoot,
                        continue_after_hit=args.continue_after_hit,
                        timeout_seconds=args.timeout_seconds,
                        trace_compact_counts=args.trace_compact_counts,
                        target_kinds=target_kinds,
                    )
                    total_cases += 1
                    interesting_cases += int(bool(result["interesting"]))
                    target_hit_cases += int(bool(result["target_hit"]))
                    for finding_kind in result["finding_kinds"]:
                        finding_kind_counts[str(finding_kind)] += 1
                    for target_kind in result["target_hits"]:
                        target_kind_counts[str(target_kind)] += 1
                    entry_cases.append(result)
                    summary_record = _result_summary_record(result)
                    encoded = json.dumps(summary_record, ensure_ascii=False)
                    entry_summary_handle.write(encoded + "\n")
                    summary_handle.write(encoded + "\n")
                    if result["target_hit"]:
                        target_hits_handle.write(encoded + "\n")
                    print(encoded)

            entry_report = {
                "entry_name": entry_name,
                "stage": stage,
                "seed_path": str(seed_path.resolve()),
                "parser_baseline": str((entry_dir / "parser-baseline.json").resolve()),
                "parser_inventory": parser_report["inventory"],
                "baseline_trace": str(Path(str(stage_context.baseline_metadata["trace"])).resolve()),
                "summary": str(entry_summary_path.resolve()),
                "cases_run": len(entry_cases),
                "interesting_cases": sum(int(bool(case["interesting"])) for case in entry_cases),
                "target_hit_cases": sum(int(bool(case["target_hit"])) for case in entry_cases),
                "target_hits": [
                    {
                        "case_name": case["case_name"],
                        "mutant_name": case["mutant_name"],
                        "target_hits": case["target_hits"],
                    }
                    for case in entry_cases
                    if case["target_hit"]
                ],
            }
            (entry_dir / "entry.json").write_text(json.dumps(entry_report, indent=2) + "\n", encoding="utf-8")
            entry_reports.append(entry_report)

    campaign = {
        "schema": "danmakufuzz-anm-runtime-campaign-v1",
        "archive": str(archive_path),
        "game_dir": str(game_dir),
        "headless_bin": str(headless_bin),
        "actions": str(actions),
        "seed": args.seed,
        "difficulty": args.difficulty,
        "character": args.character,
        "shot_type": args.shot_type,
        "max_ticks": args.max_ticks,
        "timeout_seconds": args.timeout_seconds,
        "trace_compact_counts": args.trace_compact_counts,
        "mutant_profile": args.mutant_profile,
        "target_kinds": sorted(target_kinds),
        "entry_count": len(selected_entries),
        "stage_count": len(stage_contexts),
        "selected_entries": [
            {"entry_name": entry_name, "stage": stage}
            for entry_name, stage in selected_entries
        ],
        "skipped_entries": skipped_entries,
        "classification_counts": dict(sorted(classification_counts.items())),
        "finding_kind_counts": dict(sorted(finding_kind_counts.items())),
        "target_kind_counts": dict(sorted(target_kind_counts.items())),
        "total_cases": total_cases,
        "interesting_cases": interesting_cases,
        "target_hit_cases": target_hit_cases,
        "summary": str(summary_path.resolve()),
        "target_hits": str(target_hits_path.resolve()),
        "entries": entry_reports,
        "baselines": [
            {
                "stage": context.stage,
                "worker_game_dir": str(context.worker_game_dir.resolve()),
                "worker_prepare": context.worker_prepare,
                "baseline_dir": str(context.baseline_dir.resolve()),
                "baseline_metadata": context.baseline_metadata,
            }
            for _, context in sorted(stage_contexts.items())
        ],
    }
    campaign_path = artifact_dir / "campaign.json"
    campaign_path.write_text(json.dumps(campaign, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(campaign, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
