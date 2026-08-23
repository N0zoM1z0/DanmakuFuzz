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


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata5.ecl"
TARGET_OPCODE = 48
TARGET_PATH = (0, 3)
TARGET_ORIGINAL_TIME = 40
EXPECTED_BASELINE_TAIL = {
    "tick": 600,
    "game_frame": 600,
    "score": 5150,
    "lives": 2,
    "bombs": 3,
    "power": 128,
    "enemy_count": 1,
    "item_count": 1,
    "bullet_count": 328,
    "stage_vm": {
        "loaded": True,
        "script_time": 600,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 690,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_SHARED_TRACE_SHA256 = "b9ed7f3fcfffd8c6cf983b54ecd84568a1267cdf614b2b2803ac359f6adff742"
EXPECTED_ZERO_TRACE_SHA256 = "3ddafa4399243549193456a6da2f2de909b3188e3b112bf860c8634e4811af6d"
EXPECTED_ONE_TRACE_SHA256 = "120ca1ebf1ef2aa153026cf90fe76e4c99fa27fcfe52c47dbd1d7e34ff10ead4"
REPRESENTATIVES = (
    {
        "name": "instruction-time-neg1",
        "value": -1,
        "patch": "payload_instruction_time_neg1.json",
        "payload_sha256": "41389a184d1f22c216ac8a693ec513a4484025e88d35afe770d38708e0023af5",
        "trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
        "group": "shared-wrapped",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 7260,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 0,
            "item_count": 2,
            "bullet_count": 0,
            "stage_vm": {
                "loaded": True,
                "script_time": 600,
                "instruction_index": 3,
            },
            "ecl_timeline": {
                "time": 600,
                "next_time": 690,
            },
            "terminal_reason": "tick-limit",
        },
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 525 baseline=320 case=0"},
            {"kind": "score-drift", "detail": "tick 534 baseline=1670 case=1870"},
        ],
    },
    {
        "name": "instruction-time-0",
        "value": 0,
        "patch": "payload_instruction_time_0.json",
        "payload_sha256": "adac78b64324e56a89a622381e997aa0a09750d698331969ab286a3a4adca787",
        "trace_sha256": EXPECTED_ZERO_TRACE_SHA256,
        "group": "zero-shadow",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 0,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 2,
            "item_count": 0,
            "bullet_count": 0,
            "stage_vm": {
                "loaded": True,
                "script_time": 600,
                "instruction_index": 3,
            },
            "ecl_timeline": {
                "time": 600,
                "next_time": 690,
            },
            "terminal_reason": "tick-limit",
        },
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 487 baseline=490 case=0"},
            {"kind": "bullet-count-drift", "detail": "tick 540 baseline=560 case=240"},
        ],
    },
    {
        "name": "instruction-time-1",
        "value": 1,
        "patch": "payload_instruction_time_1.json",
        "payload_sha256": "7e82d312e4c34997c1244603314f3ed5fd6ffee509599bba869a99996ccc9ad8",
        "trace_sha256": EXPECTED_ONE_TRACE_SHA256,
        "group": "one-shadow",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 0,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 2,
            "item_count": 0,
            "bullet_count": 0,
            "stage_vm": {
                "loaded": True,
                "script_time": 600,
                "instruction_index": 3,
            },
            "ecl_timeline": {
                "time": 600,
                "next_time": 690,
            },
            "terminal_reason": "tick-limit",
        },
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 487 baseline=490 case=0"},
            {"kind": "bullet-count-drift", "detail": "tick 540 baseline=560 case=240"},
        ],
    },
    {
        "name": "instruction-time-1064",
        "value": 1064,
        "patch": "payload_instruction_time_1064.json",
        "payload_sha256": "8eee3fa3dc107627a4e79e65b3a892b198b99bb0c35c3c847b60d06038acc5af",
        "trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
        "group": "shared-wrapped",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 7260,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 0,
            "item_count": 2,
            "bullet_count": 0,
            "stage_vm": {
                "loaded": True,
                "script_time": 600,
                "instruction_index": 3,
            },
            "ecl_timeline": {
                "time": 600,
                "next_time": 690,
            },
            "terminal_reason": "tick-limit",
        },
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 525 baseline=320 case=0"},
            {"kind": "score-drift", "detail": "tick 534 baseline=1670 case=1870"},
        ],
    },
)
RETAIL_REPRESENTATIVE_NAME = "instruction-time-neg1"


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_PATH
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if instruction.opcode != TARGET_OPCODE:
        raise RuntimeError(f"target opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}")
    if int(instruction.time) != TARGET_ORIGINAL_TIME:
        raise RuntimeError(
            f"target instruction.time drifted: expected {TARGET_ORIGINAL_TIME}, got {instruction.time}"
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
            "family": "instruction-time",
            "field_name": "time",
            "value": int(rep["value"]),
            "original_value": TARGET_ORIGINAL_TIME,
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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_expected_findings(actual: list[dict[str, object]], expected: list[dict[str, str]], *, name: str) -> None:
    for finding in expected:
        if finding not in actual:
            raise RuntimeError(f"{name} finding drifted: missing expected finding {finding!r}")


def _first_trace_diff(left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]]) -> dict[str, Any]:
    for left, right in zip(left_rows, right_rows):
        if left == right:
            continue
        diff: dict[str, Any] = {}
        for key in sorted(set(left.keys()) | set(right.keys())):
            if left.get(key) != right.get(key):
                diff[key] = {
                    "left": left.get(key),
                    "right": right.get(key),
                }
        return {
            "tick": left.get("tick"),
            "diff": diff,
        }
    if len(left_rows) != len(right_rows):
        return {
            "tick": None,
            "diff": {
                "length": {
                    "left": len(left_rows),
                    "right": len(right_rows),
                }
            },
        }
    raise RuntimeError("expected traces to differ, but they were identical")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 5 instruction-time three-basin score-wipe fork finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage5-instruction-time-three-basin-score-wipe-fork",
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
        stage=5,
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
            f"baseline tail drifted: expected {EXPECTED_BASELINE_TAIL!r}, got {baseline_tail!r}"
        )

    case_summaries: list[dict[str, object]] = []
    retail_result_path: Path | None = None
    traces_by_name: dict[str, list[dict[str, Any]]] = {}
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
        result = run_case(
            binary=args.headless_bin.resolve(),
            game_dir=args.game_dir.resolve(),
            stage=5,
            seed=7,
            action_file=DEFAULT_ACTION_FILE,
            difficulty=3,
            character=0,
            shot_type=0,
            max_ticks=600,
            auto_shoot=True,
            continue_after_hit=False,
            timeout_seconds=10.0,
            campaign_dir=artifact_dir,
            seed_name=TARGET_SEED.name,
            mutant=mutant,
            case_index=case_index,
            baseline_trace=baseline_trace,
            baseline_records=baseline_rows,
        )
        result_path = artifact_dir / result["case_name"] / "result.json"
        trace_path = Path(str(result["trace"]))
        trace_sha256 = _trace_sha256(trace_path)
        expected_trace_sha256 = str(rep["trace_sha256"])
        if trace_sha256 != expected_trace_sha256:
            raise RuntimeError(
                f"{rep['name']} trace sha256 drifted: expected {expected_trace_sha256}, got {trace_sha256}"
            )
        rows = _load_trace(trace_path)
        traces_by_name[str(rep["name"])] = rows
        tail = _tail_summary(rows)
        expected_tail = dict(rep["expected_tail"])
        if tail != expected_tail:
            raise RuntimeError(f"{rep['name']} tail drifted: expected {expected_tail!r}, got {tail!r}")
        actual_findings = result["findings"]
        if not isinstance(actual_findings, list):
            raise RuntimeError(f"{rep['name']} findings payload is not a list")
        expected_findings = list(rep["expected_findings"])
        _assert_expected_findings(actual_findings, expected_findings, name=str(rep["name"]))
        payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
        payload_sha256 = sha256_bytes(payload_path.read_bytes())
        expected_payload_sha256 = str(rep["payload_sha256"])
        if payload_sha256 != expected_payload_sha256:
            raise RuntimeError(
                f"{rep['name']} payload sha256 drifted in case override: "
                f"expected {expected_payload_sha256}, got {payload_sha256}"
            )
        if rep["name"] == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()
        case_summaries.append(
            {
                "name": rep["name"],
                "group": rep["group"],
                "value": rep["value"],
                "patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "payload_sha256": payload_sha256,
                "trace_sha256": trace_sha256,
                "expected_findings": expected_findings,
                "result": str(result_path.resolve()),
                "payload_path": str(payload_path.resolve()),
                "trace": str(trace_path.resolve()),
                "log": result["log"],
                "command": result["command"],
                "tail": tail,
            }
        )

    zero_vs_one_first_diff = _first_trace_diff(
        traces_by_name["instruction-time-0"],
        traces_by_name["instruction-time-1"],
    )

    summary: dict[str, object] = {
        "finding": "semantic/stage5-instruction-time-three-basin-score-wipe-fork",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_site": {
            "sub_index": TARGET_PATH[0],
            "instruction_index": TARGET_PATH[1],
            "opcode": TARGET_OPCODE,
            "original_time": TARGET_ORIGINAL_TIME,
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "tail": baseline_tail,
            "command": baseline_metadata["command"],
        },
        "cases": case_summaries,
        "zero_vs_one_first_trace_diff": zero_vs_one_first_diff,
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
            "5",
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
