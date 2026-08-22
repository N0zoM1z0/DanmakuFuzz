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


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
TARGET_OPCODE = 75
TARGET_PATH = (1, 3)
TARGET_ORIGINAL_COUNT1_VALUE = 6
TARGET_ORIGINAL_COUNT2_VALUE = 2
EXPECTED_FINDING_KINDS = {
    "item-explosion",
    "bullet-count-drift",
    "score-drift",
    "item-count-drift",
    "power-drift",
    "life-drift",
    "enemy-count-drift",
    "point-item-drift",
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
    "point_items_stage": 17,
    "point_items_total": 17,
    "terminal_reason": "tick-limit",
}
EXPECTED_SHARED_CASE = {
    "trace_sha256": "11a4e3bc29984ec19daf33ac357d1aef17b4c15a7091a30d62b1d3801a8fe7ef",
    "max_items": 355,
    "max_bullets": 336,
    "item_explosion": {
        "count": 21,
        "first_tick": 1177,
        "last_tick": 1197,
    },
    "first_score_diff_tick": 659,
    "first_item_count_diff_tick": 767,
    "first_stage_vm_diff_tick": 1732,
    "first_timeline_diff_tick": 1732,
    "tail": {
        "tick": 1800,
        "game_frame": 1800,
        "score": 1591490,
        "lives": 0,
        "bombs": 3,
        "power": 115,
        "enemy_count": 8,
        "item_count": 9,
        "bullet_count": 78,
        "stage_vm": {
            "loaded": True,
            "script_time": 1800,
            "instruction_index": 5,
        },
        "ecl_timeline": {
            "time": 1800,
            "next_time": 2084,
        },
        "point_items_stage": 15,
        "point_items_total": 15,
        "terminal_reason": "tick-limit",
    },
}

REPRESENTATIVES = (
    {
        "name": "bullet-count2-zero",
        "value": 0,
        "patch": "payload_bullet_count2_zero.json",
        "target_sha256": "af83ddb14b84ec4caf6731679e1c5a9c132e5501c1bfa203516ab5be8d468eb1",
    },
    {
        "name": "bullet-count2-2147483596",
        "value": 2147483596,
        "patch": "payload_bullet_count2_2147483596.json",
        "target_sha256": "d496fea75ae331429754dc1f0df631bbf6817939d1546e9b439f380e7785b435",
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
        "point_items_stage": last_record.get("point_items_stage"),
        "point_items_total": last_record.get("point_items_total"),
        "terminal_reason": last_record.get("terminal_reason"),
    }


def _trace_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _item_explosion_summary(rows: list[dict[str, Any]], *, threshold: int = 256) -> dict[str, int | None]:
    best_count = 0
    best_first_tick: int | None = None
    best_last_tick: int | None = None
    current_count = 0
    current_first_tick: int | None = None
    for row in rows:
        item_count = len(row.get("items", []))
        if item_count > threshold:
            if current_count == 0:
                current_first_tick = int(row.get("tick", 0))
            current_count += 1
            if current_count > best_count:
                best_count = current_count
                best_first_tick = current_first_tick
                best_last_tick = int(row.get("tick", 0))
        else:
            current_count = 0
            current_first_tick = None
    return {
        "count": best_count,
        "first_tick": best_first_tick,
        "last_tick": best_last_tick,
    }


def _max_count(rows: list[dict[str, Any]], key: str) -> int:
    if key == "items":
        return max(len(row.get("items", [])) for row in rows)
    if key == "bullets":
        return max(len(row.get("bullets", [])) for row in rows)
    raise ValueError(f"unsupported trace collection key: {key}")


def _first_diff(
    baseline_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, Any]:
    for baseline_row, case_row in zip(baseline_rows, case_rows):
        if key == "item_count":
            baseline_value = len(baseline_row.get("items", []))
            case_value = len(case_row.get("items", []))
        else:
            baseline_value = baseline_row.get(key)
            case_value = case_row.get(key)
        if baseline_value != case_value:
            return {
                "tick": case_row.get("tick"),
                "baseline": baseline_value,
                "case": case_value,
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
        description="Reproduce the Stage 6 bullet-count2 item-flood basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-bullet-count2-item-flood-basin",
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
        worker_name="stage6-bullet-count2-basin-baseline",
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
    shared_trace_sha256: str | None = None
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
        case_worker_game_dir = artifact_dir / f"worker-{case_index}"
        case_worker_prepare = prepare_worker_game_dir(
            source_game_dir=args.game_dir.resolve(),
            destination=case_worker_game_dir,
            worker_name=f"stage6-bullet-count2-basin-{case_index}",
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
        trace_sha256 = _trace_sha256(trace_path)
        item_explosion = _item_explosion_summary(case_rows)
        first_score_diff = _first_diff(baseline_rows, case_rows, key="score")
        first_item_count_diff = _first_diff(baseline_rows, case_rows, key="item_count")
        first_stage_vm_diff = _first_diff(baseline_rows, case_rows, key="stage_vm")
        first_timeline_diff = _first_diff(baseline_rows, case_rows, key="ecl_timeline")
        tail = _tail_summary(case_rows)
        finding_kinds = {
            finding.get("kind")
            for finding in result["findings"]
            if isinstance(finding, dict) and isinstance(finding.get("kind"), str)
        }
        _assert_subset(finding_kinds, EXPECTED_FINDING_KINDS, label=str(rep["name"]))
        _assert_equal(trace_sha256, EXPECTED_SHARED_CASE["trace_sha256"], label=f"{rep['name']} trace sha256")
        _assert_equal(_max_count(case_rows, "items"), EXPECTED_SHARED_CASE["max_items"], label=f"{rep['name']} max items")
        _assert_equal(
            _max_count(case_rows, "bullets"),
            EXPECTED_SHARED_CASE["max_bullets"],
            label=f"{rep['name']} max bullets",
        )
        _assert_equal(item_explosion, EXPECTED_SHARED_CASE["item_explosion"], label=f"{rep['name']} item explosion")
        _assert_equal(
            first_score_diff["tick"],
            EXPECTED_SHARED_CASE["first_score_diff_tick"],
            label=f"{rep['name']} first score diff tick",
        )
        _assert_equal(
            first_item_count_diff["tick"],
            EXPECTED_SHARED_CASE["first_item_count_diff_tick"],
            label=f"{rep['name']} first item-count diff tick",
        )
        _assert_equal(
            first_stage_vm_diff["tick"],
            EXPECTED_SHARED_CASE["first_stage_vm_diff_tick"],
            label=f"{rep['name']} first stage_vm diff tick",
        )
        _assert_equal(
            first_timeline_diff["tick"],
            EXPECTED_SHARED_CASE["first_timeline_diff_tick"],
            label=f"{rep['name']} first timeline diff tick",
        )
        _assert_equal(tail, EXPECTED_SHARED_CASE["tail"], label=f"{rep['name']} tail")
        if shared_trace_sha256 is None:
            shared_trace_sha256 = trace_sha256
        elif trace_sha256 != shared_trace_sha256:
            raise RuntimeError(
                f"representatives did not converge on one identical trace digest: "
                f"expected {shared_trace_sha256}, got {trace_sha256}"
            )
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
                "item_explosion": item_explosion,
                "first_score_diff": first_score_diff,
                "first_item_count_diff": first_item_count_diff,
                "first_stage_vm_diff": first_stage_vm_diff,
                "first_timeline_diff": first_timeline_diff,
                "tail": tail,
            }
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage6-bullet-count2-item-flood-basin",
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
        "expected_shared_case": EXPECTED_SHARED_CASE,
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
            "representative": REPRESENTATIVES[0]["name"],
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
