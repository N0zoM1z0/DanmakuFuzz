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


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
TARGET_OPCODE = 75
TARGET_PATH = (2, 3)
EXPECTED_FINDINGS = [
    {"kind": "bullet-count-drift", "detail": "tick 472 baseline=30 case=0"},
]
EXPECTED_BASELINE_TAIL = {
    "tick": 600,
    "game_frame": 600,
    "score": 16270,
    "lives": 2,
    "bombs": 3,
    "power": 128,
    "enemy_count": 6,
    "item_count": 14,
    "bullet_count": 187,
    "stage_vm": {
        "loaded": True,
        "script_time": 600,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 600,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_SHARED_TRACE_SHA256 = "40ba3f92a18b45aa258b9d62c9e25ed798aff2debe0b32d27e0db9c4bcf93d54"
EXPECTED_SHARED_TAIL = {
    "tick": 600,
    "game_frame": 600,
    "score": 16270,
    "lives": 2,
    "bombs": 3,
    "power": 128,
    "enemy_count": 6,
    "item_count": 14,
    "bullet_count": 628,
    "stage_vm": {
        "loaded": True,
        "script_time": 600,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 600,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_BULLET_LANDMARKS = {
    457: {"baseline": 12, "case": 640},
    464: {"baseline": 33, "case": 640},
    470: {"baseline": 42, "case": 640},
    472: {"baseline": 30, "case": 0},
    475: {"baseline": 39, "case": 0},
    582: {"baseline": 197, "case": 590},
    600: {"baseline": 187, "case": 628},
}
RETAIL_REPRESENTATIVE_NAME = "bullet-count2-258"

REPRESENTATIVES = (
    {
        "name": "bullet-count1-4102",
        "family": "bullet-count1",
        "arg_offset": 4,
        "original_value": 6,
        "value": 4102,
        "patch": "payload_bullet_count1_4102.json",
        "payload_sha256": "d5aaae391fdd83648de958fbc783cf8b01cb94b3d3d99dc9a9101c9fd1c7cf18",
    },
    {
        "name": "bullet-count2-258",
        "family": "bullet-count2",
        "arg_offset": 8,
        "original_value": 2,
        "value": 258,
        "patch": "payload_bullet_count2_258.json",
        "payload_sha256": "3c7327f17fbf198fb0d29c3a4b1cbc356e3f2d0b5b43fa90081be2f0f846bc59",
    },
)


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_PATH
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if instruction.opcode != TARGET_OPCODE:
        raise RuntimeError(f"target opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}")
    arg_offset = int(rep["arg_offset"])
    original_value = int.from_bytes(instruction.args[arg_offset:arg_offset + 4], "little", signed=True)
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
    expected_sha256 = str(rep["payload_sha256"])
    if payload_sha256 != expected_sha256:
        raise RuntimeError(
            f"{rep['name']} payload sha256 drifted: expected {expected_sha256}, got {payload_sha256}"
        )
    value = int(rep["value"])
    return PayloadMutant(
        name=str(rep["name"]),
        payload=payload,
        source="ir-exact",
        path=TARGET_PATH,
        metadata={
            "family": str(rep["family"]),
            "field_name": "count",
            "value": value,
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


def _record_at_tick(rows: list[dict[str, Any]], tick: int) -> dict[str, Any]:
    for row in rows:
        if row.get("tick") == tick:
            return row
    raise RuntimeError(f"missing tick {tick} in trace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 cross-field bullet-count surge-collapse basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-bullet-count-cross-field-surge-collapse-basin",
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
        stage=6,
        seed=7,
        action_file=DEFAULT_ACTION_FILE,
        artifact_dir=baseline_dir.resolve(),
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
            stage=6,
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
        if result["findings"] != EXPECTED_FINDINGS:
            raise RuntimeError(f"{rep['name']} findings drifted: expected {EXPECTED_FINDINGS}, got {result['findings']}")
        result_path = artifact_dir / result["case_name"] / "result.json"
        payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
        trace_path = Path(str(result["trace"]))
        trace_sha256 = _trace_sha256(trace_path)
        if trace_sha256 != EXPECTED_SHARED_TRACE_SHA256:
            raise RuntimeError(
                f"{rep['name']} trace drifted: expected {EXPECTED_SHARED_TRACE_SHA256}, got {trace_sha256}"
            )
        case_rows = _load_trace(trace_path)
        case_tail = _tail_summary(case_rows)
        if case_tail != EXPECTED_SHARED_TAIL:
            raise RuntimeError(
                f"{rep['name']} tail drifted: expected {EXPECTED_SHARED_TAIL}, got {case_tail}"
            )
        bullet_landmarks: dict[int, dict[str, int]] = {}
        for tick, expected in EXPECTED_BULLET_LANDMARKS.items():
            baseline_record = _record_at_tick(baseline_rows, tick)
            case_record = _record_at_tick(case_rows, tick)
            actual = {
                "baseline": len(baseline_record.get("bullets", [])),
                "case": len(case_record.get("bullets", [])),
            }
            if actual != expected:
                raise RuntimeError(f"{rep['name']} bullet landmark drifted at tick {tick}: expected {expected}, got {actual}")
            bullet_landmarks[tick] = actual
        if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()
        headless_cases.append(
            {
                "name": rep["name"],
                "family": rep["family"],
                "arg_offset": rep["arg_offset"],
                "original_value": rep["original_value"],
                "value": rep["value"],
                "payload_sha256": rep["payload_sha256"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "result": str(result_path.resolve()),
                "payload_path": str(payload_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "findings": result["findings"],
                "bullet_landmarks": bullet_landmarks,
                "command": result["command"],
            }
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage6-bullet-count-cross-field-surge-collapse-basin",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_site": {
            "opcode": TARGET_OPCODE,
            "path": {
                "sub_index": TARGET_PATH[0],
                "instruction_index": TARGET_PATH[1],
            },
            "representatives": [
                {
                    "name": rep["name"],
                    "family": rep["family"],
                    "arg_offset": rep["arg_offset"],
                    "original_value": rep["original_value"],
                    "value": rep["value"],
                    "payload_sha256": rep["payload_sha256"],
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
            "expected_findings": EXPECTED_FINDINGS,
            "shared_tail": EXPECTED_SHARED_TAIL,
            "bullet_landmarks": EXPECTED_BULLET_LANDMARKS,
            "cases": headless_cases,
        },
        "source_grid": {
            "summary": str((ARTIFACTS_DIR / "semantic-exploration-grid" / "20260822T-core-grid-b" / "summary.json").resolve()),
            "cluster_summary": str((ARTIFACTS_DIR / "semantic-clusters" / "20260822T-core-grid-b" / "summary.json").resolve()),
            "family_key": "bullet-count-drift:tick 472 baseline=30 case=0|ir",
            "cases": 2,
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
            "6",
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
