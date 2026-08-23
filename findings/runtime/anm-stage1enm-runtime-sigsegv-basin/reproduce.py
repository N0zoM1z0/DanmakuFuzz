from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess

from danmakufuzz.corpus.pbg3 import Pbg3Archive
from danmakufuzz.headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    build_command,
    default_headless_binary,
    run_baseline,
)
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.interestingness.rules import Finding, load_trace_records, score_trace_path_with_baseline
from danmakufuzz.parser.anm import DEFAULT_ARCHIVE
from danmakufuzz.parser.anm_mutants import generate_anm_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_ENTRY = "stg1enm.anm"
EXPECTED_RETURN_CODE = -11
EXPECTED_TRACE_LINES = 128
TARGET_MUTANTS = {
    "first-sprite-offset-zero": {
        "process_findings": {"process-signal"},
        "trace_findings": {
            "trace-shortfall",
            "terminal-reason-drift",
            "anm-load-drift",
            "anm-suspicious-sprite",
        },
    },
    "first-script-id-ffff": {
        "process_findings": {"process-signal"},
        "trace_findings": {
            "trace-shortfall",
            "terminal-reason-drift",
        },
    },
    "first-script-offset-zero": {
        "process_findings": {"process-signal"},
        "trace_findings": {
            "trace-shortfall",
            "terminal-reason-drift",
        },
    },
    "first-instr-opcode-255": {
        "process_findings": {"process-signal"},
        "trace_findings": {
            "trace-shortfall",
            "terminal-reason-drift",
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 1 enemy ANM SIGSEGV basin."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "runtime-anm-stage1enm-runtime-sigsegv-basin",
    )
    return parser.parse_args()


def _mutant_payloads(archive_path: Path) -> dict[str, bytes]:
    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    seed_payload = archive.extract(TARGET_ENTRY)
    payloads = {
        mutant.name: mutant.payload
        for mutant in generate_anm_mutants(seed_payload)
        if mutant.name in TARGET_MUTANTS
    }
    missing = sorted(set(TARGET_MUTANTS) - set(payloads))
    if missing:
        raise RuntimeError(f"target ANM mutants disappeared: {missing}")
    return payloads


def _classify_process_result(returncode: int | None) -> list[Finding]:
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


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    game_dir = args.game_dir.resolve()
    headless_bin = args.headless_bin.resolve()
    actions = args.actions.resolve()
    artifact_dir = args.artifact_dir.resolve()

    if not archive_path.is_file():
        raise FileNotFoundError(f"missing archive seed: {archive_path}")
    if not game_dir.is_dir():
        raise FileNotFoundError(f"missing game dir: {game_dir}")
    if not headless_bin.is_file():
        raise FileNotFoundError(f"missing headless binary: {headless_bin}")

    ensure_directory(artifact_dir)
    payloads = _mutant_payloads(archive_path)

    baseline_game_dir = artifact_dir / "worker-baseline"
    baseline_worker_prepare = prepare_worker_game_dir(
        source_game_dir=game_dir,
        destination=baseline_game_dir,
        worker_name="runtime-anm-stage1enm-baseline",
        reuse=True,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=headless_bin,
        game_dir=baseline_game_dir,
        resource_override_dir=None,
        stage=1,
        seed=7,
        action_file=actions,
        artifact_dir=baseline_dir,
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=600,
        auto_shoot=True,
        continue_after_hit=False,
        trace_compact_counts=True,
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_records = load_trace_records(baseline_trace)

    baseline_last = baseline_records[-1] if baseline_records else {}
    if baseline_last.get("terminal_reason") != "physical-hit":
        raise RuntimeError(f"baseline terminal drifted: {baseline_last}")
    if baseline_last.get("tick") != 311:
        raise RuntimeError(f"baseline tick drifted: {baseline_last}")

    cases: list[dict[str, object]] = []
    for mutant_name, expectations in TARGET_MUTANTS.items():
        case_dir = artifact_dir / mutant_name
        worker_game_dir = case_dir / "worker"
        worker_prepare = prepare_worker_game_dir(
            source_game_dir=game_dir,
            destination=worker_game_dir,
            worker_name=f"runtime-anm-stage1enm-{mutant_name}",
            reuse=False,
        )
        override_dir = case_dir / "override"
        ensure_directory(override_dir / "data")
        payload_path = override_dir / "data" / TARGET_ENTRY
        payload_path.write_bytes(payloads[mutant_name])

        trace_path = case_dir / "trace.jsonl"
        log_path = case_dir / "run.log"
        command = build_command(
            binary=headless_bin,
            game_dir=worker_game_dir,
            stage=1,
            seed=7,
            actions=actions,
            trace=trace_path,
            difficulty=3,
            character=0,
            shot_type=0,
            max_ticks=600,
            auto_shoot=True,
            continue_after_hit=False,
            trace_compact_counts=True,
        )
        run_env = os.environ.copy()
        run_env["DANMAKUFUZZ_OVERRIDE_DIR"] = str(override_dir.resolve())
        with log_path.open("w", encoding="utf-8") as log_handle:
            completed = subprocess.run(
                command,
                cwd=worker_game_dir,
                env=run_env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        returncode = completed.returncode
        if returncode != EXPECTED_RETURN_CODE:
            raise RuntimeError(
                f"{mutant_name} returncode drifted: expected={EXPECTED_RETURN_CODE} got={returncode}"
            )
        if not trace_path.is_file() or trace_path.stat().st_size == 0:
            raise RuntimeError(f"{mutant_name} stopped producing a partial trace")

        trace_records = load_trace_records(trace_path)
        trace_line_count = len(trace_records)
        if trace_line_count != EXPECTED_TRACE_LINES:
            raise RuntimeError(
                f"{mutant_name} trace length drifted: expected={EXPECTED_TRACE_LINES} got={trace_line_count}"
            )
        if not (0 < trace_line_count < len(baseline_records)):
            raise RuntimeError(
                f"{mutant_name} stopped landing in the partial-trace basin: "
                f"trace_lines={trace_line_count} baseline_lines={len(baseline_records)}"
            )

        findings = _classify_process_result(returncode)
        findings.extend(
            score_trace_path_with_baseline(
                trace_path,
                baseline_records=baseline_records,
            )
        )
        finding_kinds = {finding.kind for finding in findings}
        missing_process = sorted(expectations["process_findings"] - finding_kinds)
        missing_trace = sorted(expectations["trace_findings"] - finding_kinds)
        if missing_process or missing_trace:
            raise RuntimeError(
                f"{mutant_name} stopped reproducing the crash basin: "
                f"missing_process={missing_process} missing_trace={missing_trace} "
                f"got={sorted(finding_kinds)}"
            )
        cases.append(
            {
                "mutant_name": mutant_name,
                "expected_returncode": EXPECTED_RETURN_CODE,
                "expected_trace_lines": EXPECTED_TRACE_LINES,
                "finding_kinds": sorted(finding_kinds),
                "trace": str(trace_path.resolve()),
                "log": str(log_path.resolve()),
                "payload_path": str(payload_path.resolve()),
                "worker_game_prepare": worker_prepare,
                "findings": [finding.__dict__ for finding in findings],
            }
        )

    summary = {
        "finding": "runtime/anm-stage1enm-runtime-sigsegv-basin",
        "archive": str(archive_path),
        "entry": TARGET_ENTRY,
        "expected_returncode": EXPECTED_RETURN_CODE,
        "expected_trace_lines": EXPECTED_TRACE_LINES,
        "baseline": {
            "trace": str(baseline_trace.resolve()),
            "worker_game_prepare": baseline_worker_prepare,
            "command": baseline_metadata["command"],
        },
        "cases": cases,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
