from __future__ import annotations

import argparse
import hashlib
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


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata2.ecl"
TARGET_OPCODE = 69
TARGET_PATH = (2, 9)
TARGET_ORIGINAL_COUNT1_VALUE = 10
TARGET_ORIGINAL_COUNT2_VALUE = 2
EXPECTED_FINDING_KINDS = {
    "bullet-count-drift",
    "score-drift",
    "stage-script-drift",
    "ecl-timeline-drift",
}
EXPECTED_BASELINE_TAIL = {
    "tick": 1800,
    "game_frame": 1226,
    "score": 483910,
    "lives": 0,
    "bombs": 3,
    "power": 0,
    "enemy_count": 4,
    "item_count": 11,
    "bullet_count": 101,
    "stage_vm": {
        "loaded": False,
        "script_time": 1226,
        "instruction_index": 4,
    },
    "ecl_timeline": {
        "time": 1226,
        "next_time": 1230,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_SHARED_WEDGE = {
    "trace_sha256": "83372232558f688fb187bcfe49f09e7fb51bba9ae24f4bdbc4d5040f47e74c5b",
    "freeze_summary": {
        "frozen_frame": 1212,
        "first_frozen_tick": 1212,
        "last_tick": 1800,
        "frozen_ticks": 589,
    },
    "first_score_diff_tick": 851,
    "first_stage_vm_diff_tick": 1213,
    "first_timeline_diff_tick": 1213,
    "tail": {
        "tick": 1800,
        "game_frame": 1212,
        "score": 481910,
        "lives": 0,
        "bombs": 3,
        "power": 0,
        "enemy_count": 4,
        "item_count": 10,
        "bullet_count": 23,
        "stage_vm": {
            "loaded": False,
            "script_time": 1212,
            "instruction_index": 4,
        },
        "ecl_timeline": {
            "time": 1212,
            "next_time": 1214,
        },
        "terminal_reason": "tick-limit",
    },
}
OBSERVED_BASIN_VALUES_FROM_PROBE = [
    -2147483648,
    -12208722,
    -4096,
    -2047,
    -255,
    -16,
    -2,
    -1,
    0,
    1,
    2147483596,
]

REPRESENTATIVES = (
    {
        "name": "bullet-count2-one",
        "value": 1,
        "patch": "payload_bullet_count2_one.json",
        "target_sha256": "8815ed33aee8eb2a446f3a3e58fed10201dd5bb8bdbd024e8d7ba885141be73d",
    },
    {
        "name": "bullet-count2-zero",
        "value": 0,
        "patch": "payload_bullet_count2_zero.json",
        "target_sha256": "e6b8cbcfbb2e80b85a000f499dab515ced556a0a1430f6751cbac4c7995fb225",
    },
    {
        "name": "bullet-count2-neg12208722",
        "value": -12208722,
        "patch": "payload_bullet_count2_neg12208722.json",
        "target_sha256": "de85098caee0c63974116bc7baa5d016d597d733708766ecd4daa651c69f5285",
    },
    {
        "name": "bullet-count2-2147483596",
        "value": 2147483596,
        "patch": "payload_bullet_count2_2147483596.json",
        "target_sha256": "ff0ed568d7f107102895ab89d9816a5ae4d6820be68f467f88552b82d7f229bb",
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


def _trace_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _assert_subset(actual: set[str], expected: set[str], *, label: str) -> None:
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"{label} missing expected findings: {missing}; saw {sorted(actual)}")


def _assert_equal(actual: object, expected: object, *, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} drifted: expected {expected!r}, got {actual!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 2 bullet-count2 time=1212 wedge basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage2-bullet-count2-time-1212-wedge-basin",
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
        worker_name="stage2-bullet-count2-1212-baseline",
        reuse=not args.no_reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=baseline_worker_game_dir.resolve(),
        resource_override_dir=None,
        stage=2,
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
    trace_sha_values: set[str] = set()
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
        case_worker_game_dir = artifact_dir / f"worker-{case_index}"
        case_worker_prepare = prepare_worker_game_dir(
            source_game_dir=args.game_dir.resolve(),
            destination=case_worker_game_dir,
            worker_name=f"stage2-bullet-count2-1212-{case_index}",
            reuse=not args.no_reuse_worker_game_dir,
        )
        result = run_case(
            binary=args.headless_bin.resolve(),
            game_dir=case_worker_game_dir.resolve(),
            stage=2,
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
        trace_sha256 = _trace_sha256(trace_path)
        freeze_summary = _freeze_summary(case_rows)
        tail = _tail_summary(case_rows)
        first_score_diff = _first_diff(baseline_rows, case_rows, key="score")
        first_stage_vm_diff = _first_diff(baseline_rows, case_rows, key="stage_vm")
        first_timeline_diff = _first_diff(baseline_rows, case_rows, key="ecl_timeline")
        finding_kinds = {
            finding.get("kind")
            for finding in result["findings"]
            if isinstance(finding, dict) and isinstance(finding.get("kind"), str)
        }
        _assert_subset(finding_kinds, EXPECTED_FINDING_KINDS, label=str(rep["name"]))
        _assert_equal(
            trace_sha256,
            EXPECTED_SHARED_WEDGE["trace_sha256"],
            label=f"{rep['name']} trace sha256",
        )
        _assert_equal(
            freeze_summary,
            EXPECTED_SHARED_WEDGE["freeze_summary"],
            label=f"{rep['name']} freeze summary",
        )
        _assert_equal(
            first_score_diff["tick"],
            EXPECTED_SHARED_WEDGE["first_score_diff_tick"],
            label=f"{rep['name']} first score diff tick",
        )
        _assert_equal(
            first_stage_vm_diff["tick"],
            EXPECTED_SHARED_WEDGE["first_stage_vm_diff_tick"],
            label=f"{rep['name']} first stage_vm diff tick",
        )
        _assert_equal(
            first_timeline_diff["tick"],
            EXPECTED_SHARED_WEDGE["first_timeline_diff_tick"],
            label=f"{rep['name']} first timeline diff tick",
        )
        _assert_equal(tail, EXPECTED_SHARED_WEDGE["tail"], label=f"{rep['name']} tail")
        trace_sha_values.add(trace_sha256)
        if retail_result_path is None:
            retail_result_path = result_path
        cases.append(
            {
                "representative": rep["name"],
                "value": rep["value"],
                "result": str(result_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "log": result["log"],
                "findings": result["findings"],
                "worker_game_dir": str(case_worker_game_dir.resolve()),
                "worker_game_prepare": case_worker_prepare,
                "freeze_summary": freeze_summary,
                "first_score_diff": first_score_diff,
                "first_stage_vm_diff": first_stage_vm_diff,
                "first_timeline_diff": first_timeline_diff,
                "tail": tail,
            }
        )

    if trace_sha_values != {EXPECTED_SHARED_WEDGE["trace_sha256"]}:
        raise RuntimeError(f"representatives did not converge on one shared trace: {sorted(trace_sha_values)}")

    summary: dict[str, object] = {
        "finding": "semantic/stage2-bullet-count2-time-1212-wedge-basin",
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
        "expected_shared_wedge": EXPECTED_SHARED_WEDGE,
        "observed_basin_values_from_probe": OBSERVED_BASIN_VALUES_FROM_PROBE,
        "cases": cases,
    }

    if args.retail:
        if retail_result_path is None:
            raise RuntimeError("retail requested but no representative result was produced")
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
            "2",
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
            "representative": REPRESENTATIVES[0]["name"],
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
