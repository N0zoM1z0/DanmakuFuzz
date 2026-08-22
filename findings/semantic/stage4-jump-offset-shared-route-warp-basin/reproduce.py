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
from danmakufuzz.headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata4.ecl"
TARGET_OPCODE = 3
TARGET_PATH = (1, 14)
TARGET_ORIGINAL_OFFSET_VALUE = -312
EXPECTED_FINDINGS = [
    {"kind": "bullet-count-drift", "detail": "tick 560 baseline=120 case=28"},
    {"kind": "score-drift", "detail": "tick 595 baseline=4360 case=8600"},
    {"kind": "enemy-count-drift", "detail": "tick 600 baseline=11 case=9"},
]
EXPECTED_BASELINE_TAIL = {
    "tick": 600,
    "game_frame": 600,
    "score": 4380,
    "lives": 2,
    "bombs": 3,
    "power": 128,
    "enemy_count": 11,
    "item_count": 1,
    "bullet_count": 450,
    "stage_vm": {
        "loaded": True,
        "script_time": 600,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 1004,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_SHARED_TRACE_SHA256 = "9feff7b8a44928b0b874afeab9a2b1f2cb0fa71e0c2258b5308c29ff1527f23c"
EXPECTED_SHARED_TAIL = {
    "tick": 600,
    "game_frame": 600,
    "score": 8620,
    "lives": 2,
    "bombs": 3,
    "power": 128,
    "enemy_count": 9,
    "item_count": 3,
    "bullet_count": 48,
    "stage_vm": {
        "loaded": True,
        "script_time": 600,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 1004,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_SHARED_BASIN = {
    "normalized_sink_signature": "25ea4b39d8f0996748a8b38d6861332aa84913dc9786e63c22033e036b834cc6",
    "first_normalized_divergence_tick": 551,
    "first_normalized_divergence_keys": ["enemies"],
    "sink_tick": 551,
    "sink_time": 551,
    "sink_next_time": 1004,
}
REPRESENTATIVES = (
    {
        "name": "jump-offset-neg78",
        "value": -78,
        "patch": "payload_jump_offset_neg78.json",
        "target_sha256": "e867646cb4c2f15e196d2268e2a9aea2f179b3a8a3736cda45e8b1acf990c7e2",
    },
    {
        "name": "jump-offset-neg320",
        "value": -320,
        "patch": "payload_jump_offset_neg320.json",
        "target_sha256": "7c1a500403f96b8ff05605dda7d3f2dd867acefe23259b7aeb2b2f142ec0bfdd",
    },
    {
        "name": "jump-offset-624",
        "value": 624,
        "patch": "payload_jump_offset_624.json",
        "target_sha256": "e470052abef524e87c8919fb4d19dd6dd8be82a9d230718cc56b2a3f159a4167",
    },
    {
        "name": "jump-offset-3784",
        "value": 3784,
        "patch": "payload_jump_offset_3784.json",
        "target_sha256": "833101b81eec7d5761e112d175372e20c5d51f138e5b8cc408142bc4c9cf5bd6",
    },
)
RETAIL_REPRESENTATIVE_NAME = "jump-offset-neg320"


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_PATH
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if instruction.opcode != TARGET_OPCODE:
        raise RuntimeError(f"target opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}")
    original_offset = int.from_bytes(instruction.args[4:8], "little", signed=True)
    if original_offset != TARGET_ORIGINAL_OFFSET_VALUE:
        raise RuntimeError(
            f"target jump offset drifted: expected {TARGET_ORIGINAL_OFFSET_VALUE}, got {original_offset}"
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
            "family": "jump-offset",
            "field_name": "jump_offset",
            "value": value,
            "original_value": TARGET_ORIGINAL_OFFSET_VALUE,
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
        description="Reproduce the Stage 4 shared jump-offset route-warp basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage4-jump-offset-shared-route-warp-basin",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--retail", action="store_true")
    parser.add_argument("--retail-timeout-seconds", type=float, default=35.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not TARGET_SEED.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {TARGET_SEED}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=4,
        seed=7,
        action_file=DEFAULT_ACTION_FILE,
        artifact_dir=baseline_dir,
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=600,
        auto_shoot=True,
        continue_after_hit=False,
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
            game_dir=args.game_dir.resolve(),
            stage=4,
            seed=7,
            action_file=DEFAULT_ACTION_FILE,
            difficulty=3,
            character=0,
            shot_type=0,
            max_ticks=600,
            auto_shoot=True,
            continue_after_hit=False,
            timeout_seconds=5.0,
            campaign_dir=artifact_dir,
            seed_name=TARGET_SEED.name,
            mutant=mutant,
            case_index=case_index,
            baseline_trace=baseline_trace,
            baseline_records=baseline_rows,
        )
        result_path = artifact_dir / result["case_name"] / "result.json"
        payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
        trace_path = Path(str(result["trace"]))
        trace_sha256 = _trace_sha256(trace_path)
        if trace_sha256 != EXPECTED_SHARED_TRACE_SHA256:
            raise RuntimeError(
                f"{rep['name']} trace drifted: expected {EXPECTED_SHARED_TRACE_SHA256}, got {trace_sha256}"
            )
        ordered_findings = _ordered_findings(result)
        if ordered_findings != EXPECTED_FINDINGS:
            raise RuntimeError(
                f"{rep['name']} findings drifted: expected {EXPECTED_FINDINGS}, got {ordered_findings}"
            )
        case_tail = _tail_summary(_load_trace(trace_path))
        if case_tail != EXPECTED_SHARED_TAIL:
            raise RuntimeError(
                f"{rep['name']} tail drifted: expected {EXPECTED_SHARED_TAIL}, got {case_tail}"
            )
        if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()
        headless_cases.append(
            {
                "name": rep["name"],
                "value": rep["value"],
                "payload_sha256": rep["target_sha256"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "result": str(result_path.resolve()),
                "payload_path": str(payload_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "findings": ordered_findings,
                "tail": case_tail,
                "command": result["command"],
            }
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage4-jump-offset-shared-route-warp-basin",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_site": {
            "opcode": TARGET_OPCODE,
            "path": {
                "sub_index": TARGET_PATH[0],
                "instruction_index": TARGET_PATH[1],
            },
            "original_jump_offset": TARGET_ORIGINAL_OFFSET_VALUE,
            "representatives": [
                {
                    "name": rep["name"],
                    "value": rep["value"],
                    "payload_sha256": rep["target_sha256"],
                    "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                }
                for rep in REPRESENTATIVES
            ],
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "command": baseline_metadata["command"],
            "tail": baseline_tail,
        },
        "headless": {
            "shared_trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
            "shared_basin": EXPECTED_SHARED_BASIN,
            "expected_findings": EXPECTED_FINDINGS,
            "shared_tail": EXPECTED_SHARED_TAIL,
            "cases": headless_cases,
        },
    }

    if args.retail:
        if retail_result_path is None:
            raise RuntimeError("retail representative result path was not recorded")
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
            "4",
            "--difficulty",
            "3",
            "--timeout-seconds",
            str(args.retail_timeout_seconds),
        ]
        subprocess.run(command, check=True)
        report_path = retail_dir / "report.json"
        summary["retail"] = {
            "representative": RETAIL_REPRESENTATIVE_NAME,
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
