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


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata1.ecl"
TARGET_OPCODE = 77
TARGET_PATH = (1, 7)
TARGET_ORIGINAL_VALUE = 120
EXPECTED_BASELINE_TAIL = {
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
    "terminal_reason": "tick-limit",
}
REPRESENTATIVES = (
    {
        "name": "shoot-interval-neg1",
        "value": -1,
        "patch": "payload_shoot_interval_neg1.json",
        "payload_sha256": "6bbb56e60c3ba26278993b9b9fb8faae3377e7cec1264bdc16e3bf982aebbb02",
        "trace_sha256": "dcc0b9953bea29d9f4baf5d5cc7fc809d64234ad36192994fd787a0f043f9bf1",
        "expected_tail": {
            "tick": 1800,
            "game_frame": 1391,
            "score": 268250,
            "lives": 0,
            "bombs": 3,
            "power": 0,
            "enemy_count": 14,
            "item_count": 6,
            "bullet_count": 78,
            "stage_vm": {
                "loaded": False,
                "script_time": 1391,
                "instruction_index": 4,
            },
            "ecl_timeline": {
                "time": 1391,
                "next_time": 1400,
            },
            "terminal_reason": "tick-limit",
        },
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 626 baseline=6870 case=6370"},
            {"kind": "item-count-drift", "detail": "tick 640 baseline=10 case=3"},
            {"kind": "life-drift", "detail": "tick 650 baseline=0 case=1"},
            {"kind": "point-item-drift", "detail": "tick 656 baseline=0 case=1"},
            {"kind": "bullet-count-drift", "detail": "tick 992 baseline=40 case=0"},
            {"kind": "stage-script-drift", "detail": "tick 1044 stage_vm.loaded baseline=False case=True"},
            {"kind": "ecl-timeline-drift", "detail": "tick 1044 ecl_timeline.time baseline=1028 case=1044"},
            {"kind": "enemy-count-drift", "detail": "tick 1076 baseline=5 case=7"},
        ],
    },
    {
        "name": "shoot-interval-1",
        "value": 1,
        "patch": "payload_shoot_interval_1.json",
        "payload_sha256": "fa6f570f22805ecd498a0cf20e09b02103849b7bbe93ba99d7457258cb5cec71",
        "trace_sha256": "1db8907f5d960048332f062755c2e80ef570298e2db5c6fcbbb0f347007c9a6f",
        "expected_tail": {
            "tick": 1800,
            "game_frame": 1028,
            "score": 238110,
            "lives": 0,
            "bombs": 3,
            "power": 0,
            "enemy_count": 5,
            "item_count": 5,
            "bullet_count": 60,
            "stage_vm": {
                "loaded": False,
                "script_time": 1028,
                "instruction_index": 4,
            },
            "ecl_timeline": {
                "time": 1028,
                "next_time": 1040,
            },
            "terminal_reason": "tick-limit",
        },
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 471 baseline=0 case=64"},
            {"kind": "score-drift", "detail": "tick 614 baseline=6870 case=48370"},
            {"kind": "life-drift", "detail": "tick 642 baseline=1 case=0"},
            {"kind": "power-drift", "detail": "tick 879 baseline=1 case=9"},
        ],
    },
    {
        "name": "shoot-interval-1144",
        "value": 1144,
        "patch": "payload_shoot_interval_1144.json",
        "payload_sha256": "8e8cbc4b925ec3a6480bc5e446e70018e5334aeddd0973d338c1d108c06b759e",
        "trace_sha256": "1c8a6632d7df057c33c36ac65328ef3762e4c0abaa6cf882b6ecfc301ccfd465",
        "expected_tail": {
            "tick": 1800,
            "game_frame": 1201,
            "score": 265690,
            "lives": 0,
            "bombs": 3,
            "power": 0,
            "enemy_count": 7,
            "item_count": 5,
            "bullet_count": 143,
            "stage_vm": {
                "loaded": False,
                "script_time": 1201,
                "instruction_index": 4,
            },
            "ecl_timeline": {
                "time": 1201,
                "next_time": 1220,
            },
            "terminal_reason": "tick-limit",
        },
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 626 baseline=6870 case=6370"},
            {"kind": "item-count-drift", "detail": "tick 640 baseline=10 case=3"},
            {"kind": "life-drift", "detail": "tick 650 baseline=0 case=1"},
            {"kind": "point-item-drift", "detail": "tick 656 baseline=0 case=1"},
            {"kind": "bullet-count-drift", "detail": "tick 882 baseline=32 case=0"},
            {"kind": "stage-script-drift", "detail": "tick 1044 stage_vm.loaded baseline=False case=True"},
            {"kind": "ecl-timeline-drift", "detail": "tick 1044 ecl_timeline.time baseline=1028 case=1044"},
            {"kind": "enemy-count-drift", "detail": "tick 1076 baseline=5 case=7"},
        ],
    },
)
RETAIL_REPRESENTATIVE_NAME = "shoot-interval-neg1"


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_PATH
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if instruction.opcode != TARGET_OPCODE:
        raise RuntimeError(f"target opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}")
    original_value = int.from_bytes(instruction.args[:4], "little", signed=True)
    if original_value != TARGET_ORIGINAL_VALUE:
        raise RuntimeError(
            f"target shoot-interval drifted: expected {TARGET_ORIGINAL_VALUE}, got {original_value}"
        )
    patch_path = Path(__file__).with_name(str(rep["patch"]))
    if not patch_path.is_file():
        raise FileNotFoundError(f"missing payload patch: {patch_path}")
    canonical_seed_payload = serialize_ecl(ecl)
    payload_patch = load_payload_patch(patch_path)
    payload = apply_payload_patch(canonical_seed_payload, payload_patch)
    payload_sha256 = sha256_bytes(payload)
    expected_sha256 = str(rep["payload_sha256"])
    if payload_sha256 != expected_sha256:
        raise RuntimeError(
            f"{rep['name']} payload sha256 drifted: expected {expected_sha256}, got {payload_sha256}"
        )
    return PayloadMutant(
        name=str(rep["name"]),
        payload=payload,
        source="ir-exact",
        path=TARGET_PATH,
        metadata={
            "family": "shoot-interval",
            "field_name": "time",
            "value": int(rep["value"]),
            "original_value": TARGET_ORIGINAL_VALUE,
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


def _trace_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _ordered_findings(result: dict[str, object]) -> list[dict[str, str]]:
    findings = result.get("findings")
    if not isinstance(findings, list):
        return []
    ordered: list[dict[str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        detail = item.get("detail")
        if not isinstance(kind, str):
            continue
        row = {"kind": kind}
        if isinstance(detail, str):
            row["detail"] = detail
        ordered.append(row)
    return ordered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 1 second-site cross-value shoot-interval three-basin fork."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage1-second-shoot-interval-cross-value-three-basin-fork",
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
        worker_name="stage1-second-shoot-interval-three-basin-fork",
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
    baseline_rows = _load_trace(baseline_trace)
    baseline_tail = _tail_summary(baseline_rows)
    if baseline_tail != EXPECTED_BASELINE_TAIL:
        raise RuntimeError(
            f"baseline tail drifted: expected {EXPECTED_BASELINE_TAIL}, got {baseline_tail}"
        )

    headless_cases: list[dict[str, object]] = []
    retail_result_path: Path | None = None
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
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
            case_index=case_index,
            baseline_trace=baseline_trace,
        )
        if not result.get("interesting"):
            raise RuntimeError(f"{rep['name']} no longer triggers interestingness")
        result_path = artifact_dir / str(result["case_name"]) / "result.json"
        trace_path = Path(str(result["trace"]))
        payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
        ordered_findings = _ordered_findings(result)
        if ordered_findings != list(rep["expected_findings"]):
            raise RuntimeError(
                f"{rep['name']} findings drifted: expected {rep['expected_findings']}, got {ordered_findings}"
            )
        rows = _load_trace(trace_path)
        tail = _tail_summary(rows)
        if tail != rep["expected_tail"]:
            raise RuntimeError(f"{rep['name']} tail drifted: expected {rep['expected_tail']}, got {tail}")
        trace_sha = _trace_sha256(trace_path)
        if trace_sha != rep["trace_sha256"]:
            raise RuntimeError(
                f"{rep['name']} trace sha drifted: expected {rep['trace_sha256']}, got {trace_sha}"
            )
        headless_cases.append(
            {
                "name": rep["name"],
                "value": rep["value"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "payload_path": str(payload_path.resolve()),
                "payload_sha256": rep["payload_sha256"],
                "result": str(result_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha,
                "tail": tail,
                "findings": ordered_findings,
                "command": result["command"],
            }
        )
        if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()

    summary: dict[str, object] = {
        "finding": "semantic/stage1-second-shoot-interval-cross-value-three-basin-fork",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_site": {
            "path": {
                "sub_index": TARGET_PATH[0],
                "instruction_index": TARGET_PATH[1],
            },
            "opcode": TARGET_OPCODE,
            "original_value": TARGET_ORIGINAL_VALUE,
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "tail": baseline_tail,
            "worker_game_dir": str(worker_game_dir.resolve()),
            "worker_game_prepare": worker_prepare,
            "command": baseline_metadata["command"],
        },
        "headless_cases": headless_cases,
    }

    if args.retail:
        if retail_result_path is None:
            raise RuntimeError(f"retail representative {RETAIL_REPRESENTATIVE_NAME} was not produced")
        retail_dir = artifact_dir / "retail"
        command = [
            sys.executable,
            "-m",
            "danmakufuzz.retail.confirm_case",
            "--result",
            str(retail_result_path),
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
        summary["retail"] = {
            "artifact_dir": str(retail_dir.resolve()),
            "report": str((retail_dir / "report.json").resolve()),
            "command": command,
            "representative": RETAIL_REPRESENTATIVE_NAME,
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
