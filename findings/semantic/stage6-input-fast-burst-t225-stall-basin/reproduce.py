from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from danmakufuzz.headless.baseline import (
    DEFAULT_GAME_DIR,
    build_command,
    default_headless_binary,
    run_baseline,
)
from danmakufuzz.interestingness.rules import Finding, load_trace_records, score_trace_path_with_baseline
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import classify_process_result
from danmakufuzz.semantic.input_campaign import STRONG_INPUT_FINDINGS


FINDING_NAME = "semantic/stage6-input-fast-burst-t225-stall-basin"
TARGET_STAGE = 6
TARGET_SEED = 7
TARGET_DIFFICULTY = 3
TARGET_CHARACTER = 0
TARGET_SHOT_TYPE = 0
TARGET_MAX_TICKS = 1800
EXPECTED_TRACE_SHA256 = "89e457118c3512990da70c58b23cb62bccadb1f5df37064262a6be6d613bda6f"
EXPECTED_FINDING_KINDS = {
    "stalled-progress",
    "stalled-frame",
    "stage-script-drift",
    "ecl-timeline-drift",
}
EXPECTED_STALL_DETAIL = (
    "frame=1470 window>=240 tick=1710 game_frame=1470 rng_generation=16066 "
    "stage_vm.loaded=False stage_vm.script_time=1470 stage_vm.instruction_index=4 "
    "ecl_timeline.time=1470 ecl_timeline.next_time=1544"
)
EXPECTED_STAGE_DRIFT_DETAIL = "tick 1486 stage_vm.loaded baseline=True case=False"
EXPECTED_TIMELINE_DRIFT_DETAIL = "tick 1486 ecl_timeline.time baseline=1486 case=1470"
EXPECTED_BASELINE_TAIL = {
    "tick": 1800,
    "game_frame": 1731,
    "score": 1578580,
    "enemy_count": 6,
    "stage_vm": {
        "loaded": False,
        "script_time": 1731,
        "instruction_index": 5,
    },
    "ecl_timeline": {
        "time": 1731,
        "next_time": 1784,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_MUTANT_TAIL = {
    "tick": 1800,
    "game_frame": 1470,
    "score": 1062100,
    "enemy_count": 4,
    "stage_vm": {
        "loaded": False,
        "script_time": 1470,
        "instruction_index": 4,
    },
    "ecl_timeline": {
        "time": 1470,
        "next_time": 1544,
    },
    "terminal_reason": "tick-limit",
}


def _here() -> Path:
    return Path(__file__).resolve().parent


def _trace_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _run_once(
    *,
    binary: Path,
    game_dir: Path,
    action_file: Path,
    trace_path: Path,
    log_path: Path,
    baseline_records: list[dict[str, object]],
) -> dict[str, object]:
    command = build_command(
        binary=binary,
        game_dir=game_dir,
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        actions=action_file,
        trace=trace_path,
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=True,
        continue_after_hit=True,
        trace_compact_counts=False,
    )
    with log_path.open("w", encoding="utf-8") as log_handle:
        completed = subprocess.run(
            command,
            cwd=game_dir,
            env=os.environ.copy(),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    findings = classify_process_result(completed.returncode, timed_out=False)
    findings.extend(score_trace_path_with_baseline(trace_path, baseline_records=baseline_records))
    return {
        "command": command,
        "returncode": completed.returncode,
        "trace": trace_path,
        "log": log_path,
        "trace_sha256": _trace_sha256(trace_path),
        "findings": findings,
    }


def _assert_tail(label: str, record: dict[str, object], expected: dict[str, object]) -> None:
    for key, expected_value in expected.items():
        actual_value = record.get(key)
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict):
                raise RuntimeError(f"{label} tail field {key!r} is not a dict: {actual_value!r}")
            for child_key, child_expected in expected_value.items():
                child_actual = actual_value.get(child_key)
                if child_actual != child_expected:
                    raise RuntimeError(
                        f"{label} tail field {key}.{child_key} drifted: expected {child_expected!r}, got {child_actual!r}"
                    )
            continue
        if actual_value != expected_value:
            raise RuntimeError(f"{label} tail field {key!r} drifted: expected {expected_value!r}, got {actual_value!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 input fast-burst t225 stall basin finding."
    )
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument(
        "--baseline-actions",
        type=Path,
        default=Path("config/headless_baseline_actions_1800.txt"),
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-input-fast-burst-t225-stall-basin",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    binary = args.headless_bin.resolve()
    game_dir = args.game_dir.resolve()
    baseline_actions = args.baseline_actions.resolve()
    payload_actions = (_here() / "payload_actions.txt").resolve()

    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=binary,
        game_dir=game_dir,
        resource_override_dir=None,
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        action_file=baseline_actions,
        artifact_dir=baseline_dir,
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=True,
        continue_after_hit=True,
        trace_compact_counts=False,
        log_path=baseline_dir / "run.log",
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_records = load_trace_records(baseline_trace)
    _assert_tail("baseline", baseline_records[-1], EXPECTED_BASELINE_TAIL)

    run_a = _run_once(
        binary=binary,
        game_dir=game_dir,
        action_file=payload_actions,
        trace_path=artifact_dir / "trace-a.jsonl",
        log_path=artifact_dir / "run-a.log",
        baseline_records=baseline_records,
    )
    run_b = _run_once(
        binary=binary,
        game_dir=game_dir,
        action_file=payload_actions,
        trace_path=artifact_dir / "trace-b.jsonl",
        log_path=artifact_dir / "run-b.log",
        baseline_records=baseline_records,
    )
    if int(run_a["returncode"]) != 0 or int(run_b["returncode"]) != 0:
        raise RuntimeError(f"mutant run failed: run_a={run_a['returncode']} run_b={run_b['returncode']}")
    if str(run_a["trace_sha256"]) != str(run_b["trace_sha256"]):
        raise RuntimeError(
            f"repeat trace hash drifted: {run_a['trace_sha256']} != {run_b['trace_sha256']}"
        )
    if str(run_a["trace_sha256"]) != EXPECTED_TRACE_SHA256:
        raise RuntimeError(
            f"trace hash drifted: expected {EXPECTED_TRACE_SHA256}, got {run_a['trace_sha256']}"
        )

    mutant_records = load_trace_records(Path(run_a["trace"]))
    _assert_tail("mutant", mutant_records[-1], EXPECTED_MUTANT_TAIL)

    findings = [
        finding
        for finding in list(run_a["findings"])
        if finding.kind in STRONG_INPUT_FINDINGS
    ]
    finding_rows = [{"kind": finding.kind, "detail": finding.detail} for finding in findings]
    finding_kinds = {row["kind"] for row in finding_rows}
    if finding_kinds != EXPECTED_FINDING_KINDS:
        raise RuntimeError(f"finding kinds drifted: expected {EXPECTED_FINDING_KINDS}, got {finding_kinds}")

    finding_map = {row["kind"]: row["detail"] for row in finding_rows}
    if finding_map.get("stalled-progress") != EXPECTED_STALL_DETAIL:
        raise RuntimeError(f"stalled-progress detail drifted: {finding_map.get('stalled-progress')!r}")
    if finding_map.get("stage-script-drift") != EXPECTED_STAGE_DRIFT_DETAIL:
        raise RuntimeError(f"stage-script-drift detail drifted: {finding_map.get('stage-script-drift')!r}")
    if finding_map.get("ecl-timeline-drift") != EXPECTED_TIMELINE_DRIFT_DETAIL:
        raise RuntimeError(f"ecl-timeline-drift detail drifted: {finding_map.get('ecl-timeline-drift')!r}")

    summary = {
        "finding": FINDING_NAME,
        "payload_actions": str(payload_actions),
        "baseline_actions": str(baseline_actions),
        "baseline": baseline_metadata,
        "run_a": {
            "command": run_a["command"],
            "returncode": run_a["returncode"],
            "trace": str(Path(run_a["trace"]).resolve()),
            "log": str(Path(run_a["log"]).resolve()),
            "trace_sha256": run_a["trace_sha256"],
        },
        "run_b": {
            "command": run_b["command"],
            "returncode": run_b["returncode"],
            "trace": str(Path(run_b["trace"]).resolve()),
            "log": str(Path(run_b["log"]).resolve()),
            "trace_sha256": run_b["trace_sha256"],
        },
        "findings": finding_rows,
        "baseline_tail": baseline_records[-1],
        "mutant_tail": mutant_records[-1],
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
