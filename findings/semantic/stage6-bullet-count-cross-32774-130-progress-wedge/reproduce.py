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


TARGET_MUTANT_NAME = "bullet-count-cross-32774-130"
TARGET_MUTANT_PATH = (1, 3)
TARGET_COUNT1_VALUE = 32774
TARGET_COUNT2_VALUE = 130
TARGET_ORIGINAL_COUNT1_VALUE = 6
TARGET_ORIGINAL_COUNT2_VALUE = 2
TARGET_OPCODE = 75
TARGET_PAYLOAD_SHA256 = "bcce7b0b69b2b268c9b48fa6c6d73d1eba0611a95ba62f60092bc27c79759880"
TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
PAYLOAD_PATCH_PATH = Path(__file__).with_name("payload_patch.json")

EXPECTED_FINDING_KINDS = {
    "stalled-progress",
    "stalled-frame",
    "bullet-count-drift",
    "stage-script-drift",
    "ecl-timeline-drift",
}
EXPECTED_MAX_BULLETS = 640
EXPECTED_MAX_BULLET_TICK = 637
EXPECTED_FROZEN_FRAME = 1382
EXPECTED_FIRST_FROZEN_TICK = 1382
EXPECTED_FIRST_STAGE_VM_DRIFT_TICK = 1383
EXPECTED_FIRST_TIMELINE_DRIFT_TICK = 1383
EXPECTED_CASE_FINAL = {
    "tick": 1800,
    "game_frame": 1382,
    "score": 971800,
    "lives": 0,
    "bombs": 3,
    "power": 0,
    "enemy_count": 4,
    "item_count": 32,
    "bullet_count": 405,
    "stage_vm": {
        "loaded": False,
        "script_time": 1382,
        "instruction_index": 4,
    },
    "ecl_timeline": {
        "time": 1382,
        "next_time": 0,
    },
}
EXPECTED_BASELINE_FINAL = {
    "tick": 1800,
    "game_frame": 1731,
    "score": 1578580,
    "lives": 0,
    "bombs": 3,
    "power": 0,
    "enemy_count": 6,
    "item_count": 14,
    "bullet_count": 170,
    "stage_vm": {
        "loaded": False,
        "script_time": 1731,
        "instruction_index": 5,
    },
    "ecl_timeline": {
        "time": 1731,
        "next_time": 1784,
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
    patched_ecl = parse_ecl(payload)
    patched_instruction = patched_ecl.subs[sub_index].instructions[instruction_index]
    patched_count1 = int.from_bytes(patched_instruction.args[4:8], "little", signed=True)
    patched_count2 = int.from_bytes(patched_instruction.args[8:12], "little", signed=True)
    if patched_count1 != TARGET_COUNT1_VALUE or patched_count2 != TARGET_COUNT2_VALUE:
        raise RuntimeError(
            f"patched bullet-count pair drifted: expected {(TARGET_COUNT1_VALUE, TARGET_COUNT2_VALUE)}, "
            f"got {(patched_count1, patched_count2)}"
        )
    return PayloadMutant(
        name=TARGET_MUTANT_NAME,
        payload=payload,
        source="ir-exact",
        path=TARGET_MUTANT_PATH,
        metadata={
            "family": "bullet-count-cross",
            "count1_value": TARGET_COUNT1_VALUE,
            "count2_value": TARGET_COUNT2_VALUE,
            "original_count1": TARGET_ORIGINAL_COUNT1_VALUE,
            "original_count2": TARGET_ORIGINAL_COUNT2_VALUE,
            "strategy": "exact-i32-pair",
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


def _max_bullet_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("trace is empty")
    best_record = max(rows, key=lambda row: len(row.get("bullets", [])))
    return {
        "tick": best_record.get("tick"),
        "bullet_count": len(best_record.get("bullets", [])),
    }


def _assert_subset(actual: set[str], expected: set[str], *, label: str) -> None:
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"{label} missing expected findings: {missing}; saw {sorted(actual)}")


def _assert_equal(actual: object, expected: object, *, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} drifted: expected {expected!r}, got {actual!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 bullet-count-cross=(32774,130) progress-wedge finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-bullet-count-cross-32774-130-progress-wedge",
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
        worker_name="stage6-bullet-count-cross-32774-130",
        reuse=not args.no_reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        resource_override_dir=None,
        stage=6,
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
    baseline_rows = _load_trace(baseline_trace)
    mutant = _target_mutant()
    result = run_case(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        stage=6,
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

    finding_kinds = {str(entry["kind"]) for entry in result["findings"]}
    _assert_subset(finding_kinds, EXPECTED_FINDING_KINDS, label="headless case")

    freeze_summary = _freeze_summary(case_rows)
    _assert_equal(freeze_summary["frozen_frame"], EXPECTED_FROZEN_FRAME, label="frozen frame")
    _assert_equal(freeze_summary["first_frozen_tick"], EXPECTED_FIRST_FROZEN_TICK, label="first frozen tick")

    stage_vm_diff = _first_diff(baseline_rows, case_rows, key="stage_vm")
    _assert_equal(stage_vm_diff["tick"], EXPECTED_FIRST_STAGE_VM_DRIFT_TICK, label="first stage_vm drift tick")

    timeline_diff = _first_diff(baseline_rows, case_rows, key="ecl_timeline")
    _assert_equal(timeline_diff["tick"], EXPECTED_FIRST_TIMELINE_DRIFT_TICK, label="first ecl_timeline drift tick")

    max_bullet_summary = _max_bullet_summary(case_rows)
    _assert_equal(max_bullet_summary["bullet_count"], EXPECTED_MAX_BULLETS, label="max bullet count")
    _assert_equal(max_bullet_summary["tick"], EXPECTED_MAX_BULLET_TICK, label="max bullet tick")

    case_final = _trace_tail_summary(case_rows)
    baseline_final = _trace_tail_summary(baseline_rows)
    _assert_equal(case_final, EXPECTED_CASE_FINAL, label="case final summary")
    _assert_equal(baseline_final, EXPECTED_BASELINE_FINAL, label="baseline final summary")

    summary: dict[str, object] = {
        "finding": "semantic/stage6-bullet-count-cross-32774-130-progress-wedge",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "payload_patch": str(PAYLOAD_PATCH_PATH.resolve()),
        "target_mutant": {
            "name": TARGET_MUTANT_NAME,
            "path": {
                "sub_index": TARGET_MUTANT_PATH[0],
                "instruction_index": TARGET_MUTANT_PATH[1],
            },
            "opcode": TARGET_OPCODE,
            "original_counts": [TARGET_ORIGINAL_COUNT1_VALUE, TARGET_ORIGINAL_COUNT2_VALUE],
            "patched_counts": [TARGET_COUNT1_VALUE, TARGET_COUNT2_VALUE],
            "payload_sha256": TARGET_PAYLOAD_SHA256,
        },
        "worker_prepare": worker_prepare,
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "command": baseline_metadata["command"],
            "final": baseline_final,
        },
        "headless": {
            "result": str(result_path.resolve()),
            "payload_path": str(payload_path.resolve()),
            "trace": result["trace"],
            "log": result["log"],
            "findings": result["findings"],
            "command": result["command"],
            "freeze": freeze_summary,
            "first_stage_vm_diff": stage_vm_diff,
            "first_ecl_timeline_diff": timeline_diff,
            "max_bullets": max_bullet_summary,
            "final": case_final,
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
            "6",
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
