from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from ..headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, build_command, default_headless_binary, run_baseline
from ..interestingness.rules import Finding, score_trace, score_trace_differential
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .payload_mutants import PayloadMutant, generate_payload_mutants


ECLDATA_RE = re.compile(r"ecldata(?P<stage>\d+)\.ecl$")


def infer_stage_from_ecl_name(path: Path) -> int:
    match = ECLDATA_RE.fullmatch(path.name)
    if match is None:
        raise ValueError(f"cannot infer stage from ECL filename: {path.name}")
    return int(match.group("stage"))


def default_seed_ecl() -> Path:
    return REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"


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
) -> dict[str, object]:
    case_name = slugify_case_name(mutant, case_index)
    case_dir = campaign_dir / case_name
    ensure_directory(case_dir)
    trace_path = case_dir / "trace.jsonl"
    log_path = case_dir / "run.log"
    override_dir = materialize_override(case_dir, seed_name, mutant.payload)
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
    run_env["DANMAKUFUZZ_OVERRIDE_DIR"] = str(override_dir.resolve())

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
        findings.extend(score_trace(trace_path))
        if baseline_trace is not None and baseline_trace.is_file():
            findings.extend(score_trace_differential(trace_path, baseline_trace))
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
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", type=str)
    parser.add_argument("--case-prefix", type=str, default="campaign")
    parser.add_argument("--no-structural", action="store_true")
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
    artifact_dir = args.artifact_dir or (
        ARTIFACTS_DIR / "semantic" / f"{args.case_prefix}-stage{stage}-seed{args.seed}-{seed_ecl.stem}"
    )
    ensure_directory(artifact_dir)
    baseline_artifact_dir = artifact_dir / "_baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=stage,
        seed=args.seed,
        action_file=args.actions.resolve(),
        artifact_dir=baseline_artifact_dir.resolve(),
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

    seed_payload = seed_ecl.read_bytes()
    mutants = generate_payload_mutants(seed_payload, include_structural=not args.no_structural)
    if args.name_filter:
        mutants = [mutant for mutant in mutants if args.name_filter in mutant.name]
    if args.limit is not None:
        mutants = mutants[:args.limit]

    summary_path = artifact_dir / "summary.jsonl"
    totals = {"cases": 0, "interesting": 0}
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
                campaign_dir=artifact_dir.resolve(),
                seed_name=seed_ecl.name,
                mutant=mutant,
                case_index=case_index,
                baseline_trace=baseline_trace,
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
