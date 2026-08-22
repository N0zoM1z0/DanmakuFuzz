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
TARGET_OPCODE = 77
EXPECTED_FINDINGS = [
    {"kind": "score-drift", "detail": "tick 528 baseline=4760 case=3570"},
    {"kind": "enemy-count-drift", "detail": "tick 563 baseline=7 case=10"},
    {"kind": "bullet-count-drift", "detail": "tick 567 baseline=176 case=108"},
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
        "instruction_index": 3,
        "loaded": True,
        "script_time": 600,
        "spellcard_state": 0,
        "spellcard_ticks": 0,
        "unpause_flag": 0,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 600,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_SHARED_TRACE_SHA256 = "0cc1e8684ef13cf8709091eaac872d1b8c0f4d6b963ab746e5bccce815171aa6"
EXPECTED_SHARED_TAIL = {
    "tick": 600,
    "game_frame": 600,
    "score": 12740,
    "lives": 2,
    "bombs": 3,
    "power": 128,
    "enemy_count": 9,
    "item_count": 11,
    "bullet_count": 112,
    "stage_vm": {
        "instruction_index": 3,
        "loaded": True,
        "script_time": 600,
        "spellcard_state": 0,
        "spellcard_ticks": 0,
        "unpause_flag": 0,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 600,
    },
    "terminal_reason": "tick-limit",
}
EXPECTED_FIRST_DIFFS = {
    "score": {"tick": 484, "baseline": 1200, "case": 1180},
    "enemy_count": {"tick": 495, "baseline": 5, "case": 6},
    "bullet_count": {"tick": 457, "baseline": 12, "case": 0},
    "item_count": {"tick": 494, "baseline": 2, "case": 1},
}
REPRESENTATIVES = (
    {
        "name": "shoot-interval-cross-16-62",
        "path": (2, 6),
        "opcode": TARGET_OPCODE,
        "original_time": 0,
        "original_interval": 80,
        "left_value": 16,
        "right_value": 62,
        "patch": "payload_shoot_interval_cross_16_62.json",
        "payload_sha256": "3670664a9fc9a9a1ef212bdc1a40eef5abc49db4bb25daa65e1c2ca42530f2d5",
    },
    {
        "name": "shoot-interval-cross-neg1-neg4750",
        "path": (2, 7),
        "opcode": TARGET_OPCODE,
        "original_time": 0,
        "original_interval": 50,
        "left_value": -1,
        "right_value": -4750,
        "patch": "payload_shoot_interval_cross_neg1_neg4750.json",
        "payload_sha256": "b425af7815d2746752b97fbe086e6628c020bc6a9bee56cb0637f257e1bad729",
    },
    {
        "name": "shoot-interval-cross-30-0",
        "path": (2, 8),
        "opcode": TARGET_OPCODE,
        "original_time": 0,
        "original_interval": 30,
        "left_value": 30,
        "right_value": 0,
        "patch": "payload_shoot_interval_cross_30_0.json",
        "payload_sha256": "6453897d288a79e5e93f284b4a32282b01fcade03817fd90badefe9a557044e8",
    },
)
RETAIL_REPRESENTATIVE_NAME = "shoot-interval-cross-30-0"


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = tuple(rep["path"])
    instruction = ecl.subs[int(sub_index)].instructions[int(instruction_index)]
    if instruction.opcode != int(rep["opcode"]):
        raise RuntimeError(
            f"{rep['name']} opcode drifted: expected {rep['opcode']}, got {instruction.opcode}"
        )
    original_interval = int.from_bytes(instruction.args[:4], "little", signed=True)
    if int(instruction.time) != int(rep["original_time"]) or original_interval != int(rep["original_interval"]):
        raise RuntimeError(
            f"{rep['name']} original pair drifted: "
            f"expected ({rep['original_time']}, {rep['original_interval']}), "
            f"got ({instruction.time}, {original_interval})"
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
        path=(int(sub_index), int(instruction_index)),
        metadata={
            "family": "shoot-interval-cross",
            "field_left": "time",
            "field_right": "time",
            "field_name_left": "time",
            "right_offset": 0,
            "left_value": int(rep["left_value"]),
            "right_value": int(rep["right_value"]),
            "original_left_value": int(rep["original_time"]),
            "original_right_value": int(rep["original_interval"]),
            "strategy": "exact-instruction-time-i32-pair",
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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
            "instruction_index": stage_vm.get("instruction_index") if isinstance(stage_vm, dict) else None,
            "loaded": stage_vm.get("loaded") if isinstance(stage_vm, dict) else None,
            "script_time": stage_vm.get("script_time") if isinstance(stage_vm, dict) else None,
            "spellcard_state": stage_vm.get("spellcard_state") if isinstance(stage_vm, dict) else None,
            "spellcard_ticks": stage_vm.get("spellcard_ticks") if isinstance(stage_vm, dict) else None,
            "unpause_flag": stage_vm.get("unpause_flag") if isinstance(stage_vm, dict) else None,
        },
        "ecl_timeline": {
            "time": ecl_timeline.get("time") if isinstance(ecl_timeline, dict) else None,
            "next_time": ecl_timeline.get("next_time") if isinstance(ecl_timeline, dict) else None,
        },
        "terminal_reason": last.get("terminal_reason"),
    }


def _first_diff(
    baseline_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, int] | None:
    for baseline_row, case_row in zip(baseline_rows, case_rows):
        if key == "bullet_count":
            baseline_value = len(baseline_row.get("bullets", []))
            case_value = len(case_row.get("bullets", []))
        elif key == "item_count":
            baseline_value = len(baseline_row.get("items", []))
            case_value = len(case_row.get("items", []))
        else:
            baseline_value = baseline_row.get(key)
            case_value = case_row.get(key)
        if baseline_value != case_value:
            return {
                "tick": int(case_row.get("tick")),
                "baseline": int(baseline_value),
                "case": int(case_value),
            }
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 shoot-interval-cross three-site shared volley basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-shoot-interval-cross-three-site-shared-volley-basin",
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
            raise RuntimeError(
                f"{rep['name']} findings drifted: expected {EXPECTED_FINDINGS}, got {result['findings']}"
            )
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
        first_diffs = {
            key: _first_diff(baseline_rows, case_rows, key=key)
            for key in ("score", "enemy_count", "bullet_count", "item_count")
        }
        if first_diffs != EXPECTED_FIRST_DIFFS:
            raise RuntimeError(
                f"{rep['name']} first diff drifted: expected {EXPECTED_FIRST_DIFFS}, got {first_diffs}"
            )
        if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()
        headless_cases.append(
            {
                "name": rep["name"],
                "path": {
                    "sub_index": rep["path"][0],
                    "instruction_index": rep["path"][1],
                },
                "opcode": rep["opcode"],
                "original_time": rep["original_time"],
                "original_interval": rep["original_interval"],
                "left_value": rep["left_value"],
                "right_value": rep["right_value"],
                "payload_sha256": rep["payload_sha256"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "result": str(result_path.resolve()),
                "payload_path": str(payload_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "findings": result["findings"],
                "tail": case_tail,
                "first_diffs": first_diffs,
                "command": result["command"],
            }
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage6-shoot-interval-cross-three-site-shared-volley-basin",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_sites": [
            {
                "name": rep["name"],
                "path": {
                    "sub_index": rep["path"][0],
                    "instruction_index": rep["path"][1],
                },
                "opcode": rep["opcode"],
                "original_time": rep["original_time"],
                "original_interval": rep["original_interval"],
                "left_value": rep["left_value"],
                "right_value": rep["right_value"],
                "payload_sha256": rep["payload_sha256"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
            }
            for rep in REPRESENTATIVES
        ],
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
            "first_diffs": EXPECTED_FIRST_DIFFS,
            "cases": headless_cases,
        },
        "source_family_sweep": {
            "summary": str((ARTIFACTS_DIR / "semantic-family-sweep" / "20260822T-time-cross-scout-a" / "summary.json").resolve()),
            "cluster_summary": str((ARTIFACTS_DIR / "semantic-clusters" / "20260822T-time-cross-scout-a" / "summary.json").resolve()),
            "family_key": "score-drift:tick 528 baseline=4760 case=3570|ir",
            "cases": 3,
        },
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
