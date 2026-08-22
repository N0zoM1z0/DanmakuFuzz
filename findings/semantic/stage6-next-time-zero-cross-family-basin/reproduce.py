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
from danmakufuzz.semantic.trace_basins import _first_divergence, _load_normalized_trace, _signature, _sink_snapshot


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
SHARED_TRACE_SHA256 = "3cc327cbf73a4fb653bd5441add8e71ebc07ca8d9972ac245711fb720690fa53"
SHARED_SINK_SIGNATURE = "ac73ed0fdf15cb866a9da4fa3fc262b12900567dd4e40ed409c403a9d6af52a1"
EXPECTED_FINDING = {
    "kind": "ecl-timeline-drift",
    "detail": "tick 1748 ecl_timeline.next_time baseline=1784 case=0",
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
EXPECTED_SHARED_TAIL = {
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
        "next_time": 0,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_FIRST_DIVERGENCE_TICK = 1733
EXPECTED_FIRST_DIVERGENCE_KEYS = ["ecl_timeline"]

REPRESENTATIVES = (
    {
        "name": "boss-life-count-72",
        "family": "boss-life-count",
        "path": (8, 8),
        "opcode": 126,
        "original_value": 0,
        "value": 72,
        "patch": "payload_boss_life_count_72.json",
        "payload_sha256": "59da6eb310dd2823b91cce2da456db65d0f9dd74f5ce484bd6bfd38f767f9a97",
    },
    {
        "name": "timer-callback-threshold-4080",
        "family": "timer-callback-threshold",
        "path": (9, 13),
        "opcode": 115,
        "original_value": 1020,
        "value": 4080,
        "patch": "payload_timer_callback_threshold_4080.json",
        "payload_sha256": "b914f2e39d6a43d65cbdbf04270fca6139c643b8c0a109266e2ffef75b3c8b18",
    },
    {
        "name": "life-callback-threshold-2798",
        "family": "life-callback-threshold",
        "path": (9, 20),
        "opcode": 113,
        "original_value": 750,
        "value": 2798,
        "patch": "payload_life_callback_threshold_2798.json",
        "payload_sha256": "082cebfdf51261e1ee87fc405b64d606ec0cc02fb9508c924759b9ad35e990b6",
    },
    {
        "name": "boss-timer-64",
        "family": "boss-timer",
        "path": (14, 4),
        "opcode": 112,
        "original_value": 0,
        "value": 64,
        "patch": "payload_boss_timer_64.json",
        "payload_sha256": "690dda6391dd2d6b95d90c7d98f5a470d4aa90e0b7d89ae560487f96c0191bdb",
    },
)


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = rep["path"]  # type: ignore[misc]
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    expected_opcode = int(rep["opcode"])
    if instruction.opcode != expected_opcode:
        raise RuntimeError(f"{rep['name']} opcode drifted: expected {expected_opcode}, got {instruction.opcode}")
    original_value = int.from_bytes(instruction.args[:4], "little", signed=True)
    expected_original_value = int(rep["original_value"])
    if original_value != expected_original_value:
        raise RuntimeError(
            f"{rep['name']} original value drifted: expected {expected_original_value}, got {original_value}"
        )
    patch_path = Path(__file__).with_name(str(rep["patch"]))
    if not patch_path.is_file():
        raise FileNotFoundError(f"missing payload patch: {patch_path}")
    canonical_seed_payload = serialize_ecl(ecl)
    payload_patch = load_payload_patch(patch_path)
    payload = apply_payload_patch(canonical_seed_payload, payload_patch)
    payload_sha256 = sha256_bytes(payload)
    expected_payload_sha256 = str(rep["payload_sha256"])
    if payload_sha256 != expected_payload_sha256:
        raise RuntimeError(
            f"{rep['name']} payload sha256 drifted: expected {expected_payload_sha256}, got {payload_sha256}"
        )
    return PayloadMutant(
        name=str(rep["name"]),
        payload=payload,
        source="ir-exact",
        path=(sub_index, instruction_index),
        metadata={
            "family": str(rep["family"]),
            "field_name": "time" if "threshold" in str(rep["family"]) or str(rep["family"]) == "boss-timer" else "count",
            "value": int(rep["value"]),
            "original_value": expected_original_value,
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


def _trace_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tail_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("trace is empty")
    last = rows[-1]
    stage_vm = last.get("stage_vm")
    ecl_timeline = last.get("ecl_timeline")
    return {
        "tick": last.get("tick"),
        "game_frame": last.get("game_frame"),
        "score": last.get("score"),
        "lives": last.get("lives"),
        "bombs": last.get("bombs"),
        "power": last.get("power"),
        "enemy_count": last.get("enemy_count"),
        "item_count": len(last.get("items", [])),
        "bullet_count": len(last.get("bullets", [])),
        "stage_vm": {
            "loaded": stage_vm.get("loaded") if isinstance(stage_vm, dict) else None,
            "script_time": stage_vm.get("script_time") if isinstance(stage_vm, dict) else None,
            "instruction_index": stage_vm.get("instruction_index") if isinstance(stage_vm, dict) else None,
        },
        "ecl_timeline": {
            "time": ecl_timeline.get("time") if isinstance(ecl_timeline, dict) else None,
            "next_time": ecl_timeline.get("next_time") if isinstance(ecl_timeline, dict) else None,
        },
        "terminal_reason": last.get("terminal_reason"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 cross-family next_time=0 basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-next-time-zero-cross-family-basin",
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
        worker_name="stage6-next-time-zero-cross-family-basin",
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
    baseline_tail = _tail_summary(baseline_rows)
    if baseline_tail != EXPECTED_BASELINE_TAIL:
        raise RuntimeError(f"baseline tail drifted: expected {EXPECTED_BASELINE_TAIL}, got {baseline_tail}")

    normalized_baseline = _load_normalized_trace(baseline_trace, pos_round=4)
    headless_cases: list[dict[str, object]] = []
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
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
            case_index=case_index,
            baseline_trace=baseline_trace,
        )
        if EXPECTED_FINDING not in result["findings"]:
            raise RuntimeError(f"{rep['name']} missing expected finding: {result['findings']}")
        result_path = artifact_dir / result["case_name"] / "result.json"
        trace_path = Path(str(result["trace"]))
        trace_sha256 = _trace_sha256(trace_path)
        if trace_sha256 != SHARED_TRACE_SHA256:
            raise RuntimeError(
                f"{rep['name']} trace sha drifted: expected {SHARED_TRACE_SHA256}, got {trace_sha256}"
            )
        case_rows = _load_trace(trace_path)
        case_tail = _tail_summary(case_rows)
        if case_tail != EXPECTED_SHARED_TAIL:
            raise RuntimeError(f"{rep['name']} shared tail drifted: expected {EXPECTED_SHARED_TAIL}, got {case_tail}")
        normalized_case = _load_normalized_trace(trace_path, pos_round=4)
        divergence_record, divergence_keys = _first_divergence(normalized_baseline, normalized_case)
        if divergence_record is None or divergence_record["tick"] != EXPECTED_FIRST_DIVERGENCE_TICK:
            raise RuntimeError(f"{rep['name']} first divergence tick drifted: {divergence_record}")
        resolved_keys = list(divergence_keys or [])
        if resolved_keys != EXPECTED_FIRST_DIVERGENCE_KEYS:
            raise RuntimeError(f"{rep['name']} first divergence keys drifted: {resolved_keys}")
        sink_signature = _signature(_sink_snapshot(normalized_case[-1]))
        if sink_signature != SHARED_SINK_SIGNATURE:
            raise RuntimeError(
                f"{rep['name']} sink signature drifted: expected {SHARED_SINK_SIGNATURE}, got {sink_signature}"
            )
        headless_cases.append(
            {
                "name": rep["name"],
                "family": rep["family"],
                "path": {
                    "sub_index": rep["path"][0],
                    "instruction_index": rep["path"][1],
                },
                "opcode": rep["opcode"],
                "original_value": rep["original_value"],
                "mutated_value": rep["value"],
                "payload_sha256": rep["payload_sha256"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "result": str(result_path.resolve()),
                "payload_path": str((Path(str(result["override_dir"])) / "data" / TARGET_SEED.name).resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "findings": result["findings"],
                "command": result["command"],
            }
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage6-next-time-zero-cross-family-basin",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "representatives": headless_cases,
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "worker_game_dir": str(worker_game_dir.resolve()),
            "worker_game_prepare": worker_prepare,
            "command": baseline_metadata["command"],
            "tail": baseline_tail,
        },
        "headless": {
            "shared_trace_sha256": SHARED_TRACE_SHA256,
            "shared_sink_signature": SHARED_SINK_SIGNATURE,
            "first_divergence_tick": EXPECTED_FIRST_DIVERGENCE_TICK,
            "first_divergence_keys": EXPECTED_FIRST_DIVERGENCE_KEYS,
            "expected_finding": EXPECTED_FINDING,
            "shared_tail": EXPECTED_SHARED_TAIL,
        },
        "source_grid": {
            "summary": str((ARTIFACTS_DIR / "semantic-exploration-grid" / "20260822T-boss-grid-b" / "summary.json").resolve()),
            "families": {
                "boss-life-count": 8,
                "timer-callback-threshold": 4,
                "life-callback-threshold": 16,
                "boss-timer": 4,
            },
            "cases": 32,
        },
    }

    if args.retail:
        retail_rep = headless_cases[0]
        retail_dir = artifact_dir / "retail"
        command = [
            sys.executable,
            "-m",
            "danmakufuzz.retail.confirm_case",
            "--result",
            str(retail_rep["result"]),
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
            "representative": retail_rep["name"],
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
