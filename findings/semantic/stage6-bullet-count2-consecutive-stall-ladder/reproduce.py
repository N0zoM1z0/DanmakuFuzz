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


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
TARGET_OPCODE = 75
TARGET_PATH = (4, 3)
TARGET_ORIGINAL_COUNT1_VALUE = 9
TARGET_ORIGINAL_COUNT2_VALUE = 1
EXPECTED_FINDING_KINDS = {
    "stalled-progress",
    "stalled-frame",
    "stage-script-drift",
    "ecl-timeline-drift",
}
EXPECTED_BASELINE_TAIL = {
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
    "terminal_reason": "tick-limit",
}
REPRESENTATIVES = (
    {
        "name": "bullet-count2-six",
        "value": 6,
        "patch": "payload_bullet_count2_six.json",
        "target_sha256": "cac47031ecd0321afc3de4f49f5a9d84a0a4c8dbc760fae1edb7507c71d1db13",
        "expected_scheduler_signature": "60b86f944fa6e2a2e81e1a35e4ffa288062a0d32323c4c5e4fa25cdd762c536e",
        "expected_freeze_summary": {
            "frozen_frame": 1480,
            "first_frozen_tick": 1480,
            "last_tick": 1800,
            "frozen_ticks": 321,
        },
        "expected_first_score_diff_tick": 659,
        "expected_first_stage_vm_diff_tick": 1481,
        "expected_first_timeline_diff_tick": 1481,
        "expected_tail": {
            "tick": 1800,
            "game_frame": 1480,
            "score": 1234510,
            "lives": 0,
            "bombs": 3,
            "power": 0,
            "enemy_count": 4,
            "item_count": 21,
            "bullet_count": 187,
            "stage_vm": {
                "loaded": False,
                "script_time": 1480,
                "instruction_index": 4,
            },
            "ecl_timeline": {
                "time": 1480,
                "next_time": 1544,
            },
            "terminal_reason": "tick-limit",
        },
    },
    {
        "name": "bullet-count2-seven",
        "value": 7,
        "patch": "payload_bullet_count2_seven.json",
        "target_sha256": "112b6a1e7128997855b9df4072747155a9043c97a379e87f42bedae5c31025b4",
        "expected_scheduler_signature": "1270e6b3ba804c537cb68d8c6157ff30888fa2561d69da7d2c2e0c435b2e820b",
        "expected_freeze_summary": {
            "frozen_frame": 1534,
            "first_frozen_tick": 1534,
            "last_tick": 1800,
            "frozen_ticks": 267,
        },
        "expected_first_score_diff_tick": 659,
        "expected_first_stage_vm_diff_tick": 1535,
        "expected_first_timeline_diff_tick": 1535,
        "expected_tail": {
            "tick": 1800,
            "game_frame": 1534,
            "score": 1494540,
            "lives": 0,
            "bombs": 3,
            "power": 0,
            "enemy_count": 4,
            "item_count": 13,
            "bullet_count": 114,
            "stage_vm": {
                "loaded": False,
                "script_time": 1534,
                "instruction_index": 4,
            },
            "ecl_timeline": {
                "time": 1534,
                "next_time": 1544,
            },
            "terminal_reason": "tick-limit",
        },
    },
    {
        "name": "bullet-count2-eight",
        "value": 8,
        "patch": "payload_bullet_count2_eight.json",
        "target_sha256": "952446d75d1328b3c0fc3fba3d01437679939329ad1df506a5bbf98bdb6d578a",
        "expected_scheduler_signature": "d039faed0ee71ee53fd151428af88dcbe32dbef96e4f70f69d850e768f41ada8",
        "expected_freeze_summary": {
            "frozen_frame": 1555,
            "first_frozen_tick": 1555,
            "last_tick": 1800,
            "frozen_ticks": 246,
        },
        "expected_first_score_diff_tick": 653,
        "expected_first_stage_vm_diff_tick": 1556,
        "expected_first_timeline_diff_tick": 1556,
        "expected_tail": {
            "tick": 1800,
            "game_frame": 1555,
            "score": 1495310,
            "lives": 0,
            "bombs": 3,
            "power": 0,
            "enemy_count": 6,
            "item_count": 12,
            "bullet_count": 107,
            "stage_vm": {
                "loaded": False,
                "script_time": 1555,
                "instruction_index": 4,
            },
            "ecl_timeline": {
                "time": 1555,
                "next_time": 1664,
            },
            "terminal_reason": "tick-limit",
        },
    },
    {
        "name": "bullet-count2-nine",
        "value": 9,
        "patch": "payload_bullet_count2_nine.json",
        "target_sha256": "e588a8246680766078a2a4e9cd5d0538f752496255b2a03423c5c73b4d93228a",
        "expected_scheduler_signature": "10c0f1d4d06854c39fe6576df3a950d9b270d9c626af2e6223a63d9717da69e2",
        "expected_freeze_summary": {
            "frozen_frame": 1492,
            "first_frozen_tick": 1492,
            "last_tick": 1800,
            "frozen_ticks": 309,
        },
        "expected_first_score_diff_tick": 644,
        "expected_first_stage_vm_diff_tick": 1493,
        "expected_first_timeline_diff_tick": 1493,
        "expected_tail": {
            "tick": 1800,
            "game_frame": 1492,
            "score": 1065810,
            "lives": 0,
            "bombs": 3,
            "power": 0,
            "enemy_count": 4,
            "item_count": 19,
            "bullet_count": 169,
            "stage_vm": {
                "loaded": False,
                "script_time": 1492,
                "instruction_index": 4,
            },
            "ecl_timeline": {
                "time": 1492,
                "next_time": 1544,
            },
            "terminal_reason": "tick-limit",
        },
    },
)


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_PATH
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

    patch_path = Path(__file__).with_name(str(rep["patch"]))
    if not patch_path.is_file():
        raise FileNotFoundError(f"missing payload patch: {patch_path}")
    canonical_seed_payload = serialize_ecl(ecl)
    payload_patch = load_payload_patch(patch_path)
    payload = apply_payload_patch(canonical_seed_payload, payload_patch)
    payload_sha256 = sha256_bytes(payload)
    expected_sha256 = str(rep["target_sha256"])
    if payload_sha256 != expected_sha256:
        raise RuntimeError(
            f"{rep['name']} target sha256 drifted: expected {expected_sha256}, got {payload_sha256}"
        )
    value = int(rep["value"])
    return PayloadMutant(
        name=str(rep["name"]),
        payload=payload,
        source="ir-exact",
        path=TARGET_PATH,
        metadata={
            "family": "bullet-count2",
            "field_name": "bullet_count2",
            "value": value,
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


def _tail_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
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
        "enemy_count": last_record.get("enemy_count"),
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
        "terminal_reason": last_record.get("terminal_reason"),
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


def _scheduler_signature(
    *,
    freeze_summary: dict[str, Any],
    first_stage_vm_diff: dict[str, Any],
    first_timeline_diff: dict[str, Any],
    tail: dict[str, Any],
) -> str:
    snapshot = {
        "freeze_summary": freeze_summary,
        "first_stage_vm_diff_tick": first_stage_vm_diff["tick"],
        "first_timeline_diff_tick": first_timeline_diff["tick"],
        "tail": {
            "game_frame": tail["game_frame"],
            "stage_vm": tail["stage_vm"],
            "ecl_timeline": tail["ecl_timeline"],
            "terminal_reason": tail["terminal_reason"],
        },
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib

    return hashlib.sha256(encoded).hexdigest()


def _assert_subset(actual: set[str], expected: set[str], *, label: str) -> None:
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"{label} missing expected findings: {missing}; saw {sorted(actual)}")


def _assert_equal(actual: object, expected: object, *, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} drifted: expected {expected!r}, got {actual!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 bullet-count2 consecutive stall ladder."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-bullet-count2-consecutive-stall-ladder",
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
    baseline_worker_game_dir = artifact_dir / "worker-baseline"
    baseline_worker_prepare = prepare_worker_game_dir(
        source_game_dir=args.game_dir.resolve(),
        destination=baseline_worker_game_dir,
        worker_name="stage6-bullet-count2-stall-ladder-baseline",
        reuse=not args.no_reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=baseline_worker_game_dir.resolve(),
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
    baseline_tail = _tail_summary(baseline_rows)
    _assert_equal(baseline_tail, EXPECTED_BASELINE_TAIL, label="baseline tail")

    cases: list[dict[str, object]] = []
    retail_result_path: Path | None = None
    scheduler_signatures: set[str] = set()
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
        case_worker_game_dir = artifact_dir / f"worker-{case_index}"
        case_worker_prepare = prepare_worker_game_dir(
            source_game_dir=args.game_dir.resolve(),
            destination=case_worker_game_dir,
            worker_name=f"stage6-bullet-count2-stall-ladder-{case_index}",
            reuse=not args.no_reuse_worker_game_dir,
        )
        result = run_case(
            binary=args.headless_bin.resolve(),
            game_dir=case_worker_game_dir.resolve(),
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
            case_index=case_index,
            baseline_trace=baseline_trace,
        )
        result_path = artifact_dir / result["case_name"] / "result.json"
        trace_path = Path(str(result["trace"]))
        case_rows = _load_trace(trace_path)
        freeze_summary = _freeze_summary(case_rows)
        tail = _tail_summary(case_rows)
        first_score_diff = _first_diff(baseline_rows, case_rows, key="score")
        first_stage_vm_diff = _first_diff(baseline_rows, case_rows, key="stage_vm")
        first_timeline_diff = _first_diff(baseline_rows, case_rows, key="ecl_timeline")
        scheduler_signature = _scheduler_signature(
            freeze_summary=freeze_summary,
            first_stage_vm_diff=first_stage_vm_diff,
            first_timeline_diff=first_timeline_diff,
            tail=tail,
        )
        finding_kinds = {
            finding.get("kind")
            for finding in result["findings"]
            if isinstance(finding, dict) and isinstance(finding.get("kind"), str)
        }
        _assert_subset(finding_kinds, EXPECTED_FINDING_KINDS, label=str(rep["name"]))
        _assert_equal(
            freeze_summary,
            rep["expected_freeze_summary"],
            label=f"{rep['name']} freeze summary",
        )
        _assert_equal(
            first_score_diff["tick"],
            rep["expected_first_score_diff_tick"],
            label=f"{rep['name']} first score diff tick",
        )
        _assert_equal(
            first_stage_vm_diff["tick"],
            rep["expected_first_stage_vm_diff_tick"],
            label=f"{rep['name']} first stage_vm diff tick",
        )
        _assert_equal(
            first_timeline_diff["tick"],
            rep["expected_first_timeline_diff_tick"],
            label=f"{rep['name']} first timeline diff tick",
        )
        _assert_equal(
            scheduler_signature,
            rep["expected_scheduler_signature"],
            label=f"{rep['name']} scheduler signature",
        )
        _assert_equal(tail, rep["expected_tail"], label=f"{rep['name']} tail")
        scheduler_signatures.add(scheduler_signature)
        if str(rep["name"]) == "bullet-count2-eight":
            retail_result_path = result_path
        cases.append(
            {
                "representative": rep["name"],
                "value": rep["value"],
                "result": str(result_path.resolve()),
                "trace": str(trace_path.resolve()),
                "log": result["log"],
                "findings": result["findings"],
                "worker_game_dir": str(case_worker_game_dir.resolve()),
                "worker_game_prepare": case_worker_prepare,
                "freeze_summary": freeze_summary,
                "first_score_diff": first_score_diff,
                "first_stage_vm_diff": first_stage_vm_diff,
                "first_timeline_diff": first_timeline_diff,
                "scheduler_signature": scheduler_signature,
                "tail": tail,
            }
        )

    expected_signatures = {str(rep["expected_scheduler_signature"]) for rep in REPRESENTATIVES}
    if scheduler_signatures != expected_signatures:
        raise RuntimeError(
            f"representatives did not land on the expected distinct scheduler signatures: "
            f"expected {sorted(expected_signatures)}, got {sorted(scheduler_signatures)}"
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage6-bullet-count2-consecutive-stall-ladder",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "path": {
            "sub_index": TARGET_PATH[0],
            "instruction_index": TARGET_PATH[1],
        },
        "opcode": TARGET_OPCODE,
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "worker_game_dir": str(baseline_worker_game_dir.resolve()),
            "worker_game_prepare": baseline_worker_prepare,
            "command": baseline_metadata["command"],
            "tail": baseline_tail,
        },
        "expected_distinct_scheduler_signatures": sorted(expected_signatures),
        "cases": cases,
    }

    if args.retail:
        if retail_result_path is None:
            raise RuntimeError("retail requested but no retail representative result was produced")
        retail_dir = artifact_dir / "retail"
        command = [
            sys.executable,
            "-m",
            "danmakufuzz.retail.confirm_case",
            "--result",
            str(retail_result_path.resolve()),
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
            "representative": "bullet-count2-eight",
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
