from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl
from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch, sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import LONG_ACTION_FILE, run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


TARGET_MUTANT_NAME = "bullet-count2-257"
TARGET_MUTANT_PATH = (1, 5)
TARGET_COUNT2_VALUE = 257
TARGET_ORIGINAL_COUNT1_VALUE = 1
TARGET_ORIGINAL_COUNT2_VALUE = 1
TARGET_OPCODE = 67
TARGET_PAYLOAD_SHA256 = "c8d63d119721faa3e62bfa874b24b2b9f694d5ac9ad5619e24c2dc6a65a7ecd5"
TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata1.ecl"
PAYLOAD_PATCH_PATH = Path(__file__).with_name("payload_patch.json")

EXPECTED_FINDING_KINDS = {
    "stalled-progress",
    "stalled-frame",
    "stage-script-drift",
    "ecl-timeline-drift",
}
EXPECTED_FROZEN_FRAME = 951
EXPECTED_FIRST_FROZEN_TICK = 951
EXPECTED_FIRST_STAGE_VM_DRIFT_TICK = 952
EXPECTED_FIRST_TIMELINE_DRIFT_TICK = 952
EXPECTED_CASE_FINAL = {
    "tick": 1800,
    "game_frame": 951,
    "score": 256470,
    "lives": 0,
    "bombs": 3,
    "power": 0,
    "enemy_count": 5,
    "item_count": 5,
    "bullet_count": 150,
    "stage_vm": {
        "loaded": False,
        "script_time": 951,
        "instruction_index": 4,
    },
    "ecl_timeline": {
        "time": 951,
        "next_time": 960,
    },
}
EXPECTED_BASELINE_FINAL = {
    "tick": 1800,
    "game_frame": 1028,
    "score": 177470,
    "lives": 0,
    "bombs": 3,
    "power": 0,
    "enemy_count": 5,
    "item_count": 5,
    "bullet_count": 61,
    "stage_vm": {
        "loaded": False,
        "script_time": 1028,
        "instruction_index": 4,
    },
    "ecl_timeline": {
        "time": 1028,
        "next_time": 1040,
    },
}


def _target_mutant() -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_MUTANT_PATH
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if instruction.opcode != TARGET_OPCODE:
        raise RuntimeError(f"target opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}")
    original_count1 = int.from_bytes(instruction.args[4:8], "little", signed=True)
    if original_count1 != TARGET_ORIGINAL_COUNT1_VALUE:
        raise RuntimeError(
            f"target bullet-count1 drifted: expected {TARGET_ORIGINAL_COUNT1_VALUE}, got {original_count1}"
        )
    original_count2 = int.from_bytes(instruction.args[8:12], "little", signed=True)
    if original_count2 != TARGET_ORIGINAL_COUNT2_VALUE:
        raise RuntimeError(
            f"target bullet-count2 drifted: expected {TARGET_ORIGINAL_COUNT2_VALUE}, got {original_count2}"
        )
    if not PAYLOAD_PATCH_PATH.is_file():
        raise FileNotFoundError(f"missing payload patch: {PAYLOAD_PATCH_PATH}")
    canonical_seed_payload = serialize_ecl(ecl)
    payload_patch = load_payload_patch(PAYLOAD_PATCH_PATH)
    payload = apply_payload_patch(canonical_seed_payload, payload_patch)
    payload_sha256 = sha256_bytes(payload)
    if payload_sha256 != TARGET_PAYLOAD_SHA256:
        raise RuntimeError(
            f"target mutant sha256 drifted: expected {TARGET_PAYLOAD_SHA256}, got {payload_sha256}"
        )
    return PayloadMutant(
        name=TARGET_MUTANT_NAME,
        payload=payload,
        source="ir-exact",
        path=TARGET_MUTANT_PATH,
        metadata={
            "family": "bullet-count2",
            "value": TARGET_COUNT2_VALUE,
            "original_value": TARGET_ORIGINAL_COUNT2_VALUE,
            "strategy": "exact-i32",
        },
    )


def _load_trace(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"trace row must be an object: {path}")
            rows.append(value)
    return rows


def _trace_tail_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("trace is empty")
    last_record = rows[-1]
    stage_vm = last_record.get("stage_vm")
    ecl_timeline = last_record.get("ecl_timeline")
    return {
        "tick": last_record.get("tick"),
        "game_frame": last_record.get("game_frame"),
        "score": last_record.get("score"),
        "lives": last_record.get("lives"),
        "bombs": last_record.get("bombs"),
        "power": last_record.get("power"),
        "enemy_count": len(last_record.get("enemies", [])),
        "item_count": len(last_record.get("items", [])),
        "bullet_count": len(last_record.get("bullets", [])),
        "stage_vm": {
            "loaded": stage_vm.get("loaded") if isinstance(stage_vm, dict) else None,
            "script_time": stage_vm.get("script_time") if isinstance(stage_vm, dict) else None,
            "instruction_index": stage_vm.get("instruction_index") if isinstance(stage_vm, dict) else None,
        },
        "ecl_timeline": {
            "time": ecl_timeline.get("time") if isinstance(ecl_timeline, dict) else None,
            "next_time": ecl_timeline.get("next_time") if isinstance(ecl_timeline, dict) else None,
        },
    }


def _freeze_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("trace is empty")
    last_record = rows[-1]
    frozen_frame = last_record.get("game_frame")
    first_index = len(rows) - 1
    while first_index > 0 and rows[first_index - 1].get("game_frame") == frozen_frame:
        first_index -= 1
    first_record = rows[first_index]
    return {
        "frozen_frame": frozen_frame,
        "first_frozen_tick": first_record.get("tick"),
        "last_tick": last_record.get("tick"),
        "frozen_ticks": len(rows) - first_index,
    }


def _first_diff(
    baseline_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, Any]:
    for baseline_row, case_row in zip(baseline_rows, case_rows):
        if baseline_row.get(key) != case_row.get(key):
            return {
                "tick": case_row.get("tick"),
                "baseline": baseline_row.get(key),
                "case": case_row.get(key),
            }
    raise RuntimeError(f"no diff observed for {key}")


def _assert_subset(actual: set[str], expected: set[str], *, label: str) -> None:
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"{label} missing expected findings: {missing}; saw {sorted(actual)}")


def _assert_equal(actual: object, expected: object, *, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} drifted: expected {expected!r}, got {actual!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 1 bullet-count2=257 progress-wedge finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage1-bullet-count2-257-progress-wedge",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--no-reuse-worker-game-dir", action="store_true")
    parser.add_argument("--retail", action="store_true")
    parser.add_argument("--retail-timeout-seconds", type=float, default=35.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not TARGET_SEED.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {TARGET_SEED}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    worker_game_dir = artifact_dir / "worker-game"
    worker_prepare = prepare_worker_game_dir(
        source_game_dir=args.game_dir.resolve(),
        destination=worker_game_dir,
        worker_name="stage1-bullet-count2-257",
        reuse=not args.no_reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        resource_override_dir=None,
        stage=1,
        seed=7,
        action_file=LONG_ACTION_FILE,
        artifact_dir=baseline_dir.resolve(),
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=1800,
        auto_shoot=True,
        continue_after_hit=True,
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    mutant = _target_mutant()
    result = run_case(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        stage=1,
        seed=7,
        action_file=LONG_ACTION_FILE,
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=1800,
        auto_shoot=True,
        continue_after_hit=True,
        timeout_seconds=15.0,
        campaign_dir=artifact_dir,
        seed_name=TARGET_SEED.name,
        mutant=mutant,
        case_index=1,
        baseline_trace=baseline_trace,
    )
    result_path = artifact_dir / result["case_name"] / "result.json"
    payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name

    case_rows = _load_trace(Path(str(result["trace"])))
    baseline_rows = _load_trace(baseline_trace)
    freeze_summary = _freeze_summary(case_rows)
    case_tail = _trace_tail_summary(case_rows)
    baseline_tail = _trace_tail_summary(baseline_rows)
    first_stage_vm_diff = _first_diff(baseline_rows, case_rows, key="stage_vm")
    first_timeline_diff = _first_diff(baseline_rows, case_rows, key="ecl_timeline")
    finding_kinds = {
        finding.get("kind")
        for finding in result["findings"]
        if isinstance(finding, dict) and isinstance(finding.get("kind"), str)
    }

    _assert_subset(finding_kinds, EXPECTED_FINDING_KINDS, label="headless result")
    _assert_equal(freeze_summary["frozen_frame"], EXPECTED_FROZEN_FRAME, label="frozen frame")
    _assert_equal(freeze_summary["first_frozen_tick"], EXPECTED_FIRST_FROZEN_TICK, label="first frozen tick")
    _assert_equal(first_stage_vm_diff["tick"], EXPECTED_FIRST_STAGE_VM_DRIFT_TICK, label="stage_vm drift tick")
    _assert_equal(
        first_timeline_diff["tick"],
        EXPECTED_FIRST_TIMELINE_DRIFT_TICK,
        label="ecl_timeline drift tick",
    )
    _assert_equal(case_tail, EXPECTED_CASE_FINAL, label="case tail")
    _assert_equal(baseline_tail, EXPECTED_BASELINE_FINAL, label="baseline tail")

    summary: dict[str, object] = {
        "finding": "semantic/stage1-bullet-count2-257-progress-wedge",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_mutant": {
            "name": TARGET_MUTANT_NAME,
            "path": {
                "sub_index": TARGET_MUTANT_PATH[0],
                "instruction_index": TARGET_MUTANT_PATH[1],
            },
            "opcode": TARGET_OPCODE,
            "original_bullet_count1": TARGET_ORIGINAL_COUNT1_VALUE,
            "original_bullet_count2": TARGET_ORIGINAL_COUNT2_VALUE,
            "mutated_bullet_count2": TARGET_COUNT2_VALUE,
            "payload_sha256": TARGET_PAYLOAD_SHA256,
            "payload_patch": str(PAYLOAD_PATCH_PATH.resolve()),
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "worker_game_dir": str(worker_game_dir.resolve()),
            "worker_game_prepare": worker_prepare,
            "command": baseline_metadata["command"],
            "tail": baseline_tail,
        },
        "headless": {
            "result": str(result_path.resolve()),
            "payload_path": str(payload_path.resolve()),
            "trace": result["trace"],
            "log": result["log"],
            "findings": result["findings"],
            "command": result["command"],
            "freeze_summary": freeze_summary,
            "first_stage_vm_diff": first_stage_vm_diff,
            "first_timeline_diff": first_timeline_diff,
            "tail": case_tail,
        },
    }

    if args.retail:
        retail_dir = artifact_dir / "retail"
        command = [
            sys.executable,
            "-m",
            "danmakufuzz.retail.confirm_case",
            "--result",
            str(result_path.resolve()),
            "--artifact-dir",
            str(retail_dir.resolve()),
            "--practice-stage",
            "1",
            "--difficulty",
            "3",
            "--timeout-seconds",
            str(args.retail_timeout_seconds),
        ]
        subprocess.run(command, check=True)
        report_path = retail_dir / "report.json"
        summary["retail"] = {
            "artifact_dir": str(retail_dir.resolve()),
            "report": str(report_path.resolve()),
            "command": command,
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
