from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from ..headless.actions import parse_actions_file
from ..headless.action_mutants import ActionMutant, generate_action_mutants
from ..headless.action_mutants import select_diverse_action_mutants
from ..headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    DEFAULT_TRACE_COMPACT_COUNTS,
    build_command,
    default_headless_binary,
    run_baseline,
)
from ..interestingness.rules import Finding, load_trace_records, score_trace_path_with_baseline
from ..repo import ARTIFACTS_DIR, ensure_directory
from .ecl_campaign import classify_process_result


STRONG_INPUT_FINDINGS = {
    "timeout",
    "missing-returncode",
    "process-signal",
    "process-exit",
    "empty-trace",
    "non-finite",
    "timeline-next-time-negative",
    "bullet-explosion",
    "laser-explosion",
    "enemy-explosion",
    "item-explosion",
    "stalled-progress",
    "stalled-frame",
    "unexpected-terminal",
    "trace-shortfall",
    "stage-script-drift",
    "ecl-timeline-drift",
    "boss-ui-drift",
    "spellcard-drift",
    "boss-health-drift",
    "input-repeat-desync",
}


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-input" / stamp


def _trace_sha256(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _filter_findings(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.kind in STRONG_INPUT_FINDINGS]


def _run_once(
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
    trace_compact_counts: bool,
    trace_path: Path,
    log_path: Path,
    baseline_records: list[dict[str, object]] | None,
) -> dict[str, object]:
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
        trace_compact_counts=trace_compact_counts,
    )
    started_at = time.time()
    returncode: int | None = None
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log_handle:
        try:
            completed = subprocess.run(
                command,
                cwd=game_dir,
                env=os.environ.copy(),
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
        findings.extend(
            score_trace_path_with_baseline(
                trace_path,
                baseline_records=baseline_records,
            )
        )
    elif not findings:
        findings.append(Finding("empty-trace", "headless run finished without a non-empty trace"))
    trace_hash = _trace_sha256(trace_path)
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed_seconds,
        "trace": str(trace_path.resolve()),
        "trace_sha256": trace_hash,
        "log": str(log_path.resolve()),
        "findings": findings,
    }


def _repeat_desync_findings(run_a: dict[str, object], run_b: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    if run_a.get("returncode") != run_b.get("returncode") or run_a.get("timed_out") != run_b.get("timed_out"):
        findings.append(
            Finding(
                "input-repeat-desync",
                " ".join(
                    [
                        f"returncode_a={run_a.get('returncode')}",
                        f"returncode_b={run_b.get('returncode')}",
                        f"timed_out_a={run_a.get('timed_out')}",
                        f"timed_out_b={run_b.get('timed_out')}",
                    ]
                ),
            )
        )
    trace_a = run_a.get("trace_sha256")
    trace_b = run_b.get("trace_sha256")
    if isinstance(trace_a, str) and isinstance(trace_b, str) and trace_a != trace_b:
        findings.append(
            Finding(
                "input-repeat-desync",
                f"trace_sha256_a={trace_a} trace_sha256_b={trace_b}",
            )
        )
    return findings


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_mutant(
    mutant: ActionMutant,
    *,
    case_index: int,
    artifact_dir: Path,
    binary: Path,
    game_dir: Path,
    stage: int,
    seed: int,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    timeout_seconds: float,
    trace_compact_counts: bool,
    baseline_records: list[dict[str, object]] | None,
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{mutant.name}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    actions_path = case_dir / "actions.txt"
    actions_path.write_text(mutant.action_text, encoding="utf-8")

    run_a = _run_once(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        action_file=actions_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        timeout_seconds=timeout_seconds,
        trace_compact_counts=trace_compact_counts,
        trace_path=case_dir / "trace-a.jsonl",
        log_path=case_dir / "run-a.log",
        baseline_records=baseline_records,
    )
    run_b = _run_once(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        action_file=actions_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        timeout_seconds=timeout_seconds,
        trace_compact_counts=trace_compact_counts,
        trace_path=case_dir / "trace-b.jsonl",
        log_path=case_dir / "run-b.log",
        baseline_records=baseline_records,
    )

    findings = list(run_a["findings"])
    findings.extend(_repeat_desync_findings(run_a, run_b))
    filtered_findings = _filter_findings(findings)
    result = {
        "case_name": case_name,
        "mutant_name": mutant.name,
        "source": mutant.source,
        "action_count": mutant.action_count,
        "actions_path": str(actions_path.resolve()),
        "actions_sha256": mutant.sha256,
        "mutation_metadata": mutant.metadata,
        "run_a": {
            key: value
            for key, value in run_a.items()
            if key != "findings"
        },
        "run_b": {
            key: value
            for key, value in run_b.items()
            if key != "findings"
        },
        "findings": [{"kind": finding.kind, "detail": finding.detail} for finding in filtered_findings],
        "interesting": bool(filtered_findings),
    }
    _write_case_result(case_dir, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a generic headless input/action semantic campaign with repeat-desync checking."
    )
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--stage", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--max-ticks", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--trace-compact-counts", dest="trace_compact_counts", action="store_true")
    parser.add_argument("--full-entity-trace", dest="trace_compact_counts", action="store_false")
    parser.set_defaults(trace_compact_counts=DEFAULT_TRACE_COMPACT_COUNTS)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--samples-per-site", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    seed_stream = parse_actions_file(args.actions.resolve())
    baseline_dir = artifact_dir / "_baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=args.stage,
        seed=args.seed,
        action_file=args.actions.resolve(),
        artifact_dir=baseline_dir,
        difficulty=args.difficulty,
        character=args.character,
        shot_type=args.shot_type,
        max_ticks=args.max_ticks,
        auto_shoot=args.auto_shoot,
        continue_after_hit=args.continue_after_hit,
        trace_compact_counts=args.trace_compact_counts,
        log_path=baseline_dir / "run.log",
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_records = load_trace_records(baseline_trace) if baseline_trace.is_file() else None

    mutants = generate_action_mutants(
        seed_stream,
        random_seed=args.random_seed,
        samples_per_site=args.samples_per_site,
    )
    if args.name_filter:
        mutants = [
            mutant
            for mutant in mutants
            if any(name_filter in mutant.name for name_filter in args.name_filter)
        ]
    mutants = select_diverse_action_mutants(mutants, limit=args.limit)

    summary_path = artifact_dir / "summary.jsonl"
    classification_counts: Counter[str] = Counter()
    interesting_cases = 0
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, mutant in enumerate(mutants, start=1):
            result = _run_mutant(
                mutant,
                case_index=case_index,
                artifact_dir=artifact_dir,
                binary=args.headless_bin.resolve(),
                game_dir=args.game_dir.resolve(),
                stage=args.stage,
                seed=args.seed,
                difficulty=args.difficulty,
                character=args.character,
                shot_type=args.shot_type,
                max_ticks=args.max_ticks,
                auto_shoot=args.auto_shoot,
                continue_after_hit=args.continue_after_hit,
                timeout_seconds=args.timeout_seconds,
                trace_compact_counts=args.trace_compact_counts,
                baseline_records=baseline_records,
            )
            if result["interesting"]:
                classification_counts["interesting"] += 1
                interesting_cases += 1
            else:
                classification_counts["boring"] += 1
            summary_handle.write(json.dumps(result) + "\n")
            print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-semantic-input-campaign-v1",
        "baseline": baseline_metadata,
        "stage": args.stage,
        "seed": args.seed,
        "actions": str(args.actions.resolve()),
        "random_seed": args.random_seed,
        "samples_per_site": args.samples_per_site,
        "mutants_generated": len(mutants),
        "interesting_cases": interesting_cases,
        "classification_counts": dict(sorted(classification_counts.items())),
        "summary": str(summary_path.resolve()),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
