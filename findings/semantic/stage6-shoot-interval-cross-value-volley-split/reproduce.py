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
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
TARGET_OPCODE = 77
TARGET_PATH = (1, 8)
TARGET_ORIGINAL_VALUE = 30
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
EXPECTED_SHARED_TRACE_SHA256 = "31b6ada04316b5a95ff41b5c53c3bfbed1674ec71d4e939e8863743b873d346e"
EXPECTED_SHOULDER_TRACE_SHA256 = "66bc46e9d6556decbd0aacfc58ea0cc87c58933593cd078f99229d6a0d4df4c3"
REPRESENTATIVES = (
    {
        "name": "shoot-interval-neg60",
        "value": -60,
        "patch": "payload_shoot_interval_neg60.json",
        "payload_sha256": "98074f1e4d717171aea568fc3de1f6ccfc51f1d96d49fee9a08820cdccd3d589",
        "trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
        "group": "shared",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 16270,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 6,
            "item_count": 14,
            "bullet_count": 151,
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
        },
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 479 baseline=39 case=6"},
        ],
        "expected_first_bullet_diff": {"tick": 464, "baseline": 33, "case": 21},
    },
    {
        "name": "shoot-interval-46",
        "value": 46,
        "patch": "payload_shoot_interval_46.json",
        "payload_sha256": "8e182e6bc40e4144b54b1443e7d0a0ecc718a3aba51dd2399df0b454bd21e6e7",
        "trace_sha256": EXPECTED_SHOULDER_TRACE_SHA256,
        "group": "shoulder",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 16270,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 6,
            "item_count": 14,
            "bullet_count": 183,
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
        },
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 460 baseline=21 case=0"},
        ],
        "expected_first_bullet_diff": {"tick": 442, "baseline": 0, "case": 12},
    },
    {
        "name": "shoot-interval-32798",
        "value": 32798,
        "patch": "payload_shoot_interval_32798.json",
        "payload_sha256": "f89734e090a4829220475fe238d6f932c4cc6b397f916991ef7b1b7f57809d6b",
        "trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
        "group": "shared",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 16270,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 6,
            "item_count": 14,
            "bullet_count": 151,
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
        },
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 479 baseline=39 case=6"},
        ],
        "expected_first_bullet_diff": {"tick": 464, "baseline": 33, "case": 21},
    },
    {
        "name": "shoot-interval-65566",
        "value": 65566,
        "patch": "payload_shoot_interval_65566.json",
        "payload_sha256": "242f5fec355aa9a61b3ad1f1bb68f7e754671e821aa9ce08029f5aaed2dec29b",
        "trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
        "group": "shared",
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 16270,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 6,
            "item_count": 14,
            "bullet_count": 151,
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
        },
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 479 baseline=39 case=6"},
        ],
        "expected_first_bullet_diff": {"tick": 464, "baseline": 33, "case": 21},
    },
)
RETAIL_REPRESENTATIVE_NAME = "shoot-interval-neg60"


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


def _first_bullet_diff(
    baseline_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
) -> dict[str, int] | None:
    for baseline_record, case_record in zip(baseline_rows, case_rows):
        baseline_bullets = len(baseline_record.get("bullets", []))
        case_bullets = len(case_record.get("bullets", []))
        if baseline_bullets != case_bullets:
            return {
                "tick": int(case_record.get("tick", 0)),
                "baseline": baseline_bullets,
                "case": case_bullets,
            }
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 cross-value shoot-interval volley split."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-shoot-interval-cross-value-volley-split",
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
        worker_name="stage6-shoot-interval-volley-split",
        reuse=not args.no_reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
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
    shared_trace_sha: str | None = None
    shoulder_trace_sha: str | None = None
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
        result = run_case(
            binary=args.headless_bin.resolve(),
            game_dir=worker_game_dir.resolve(),
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
        first_bullet_diff = _first_bullet_diff(baseline_rows, rows)
        if first_bullet_diff != rep["expected_first_bullet_diff"]:
            raise RuntimeError(
                f"{rep['name']} first bullet diff drifted: "
                f"expected {rep['expected_first_bullet_diff']}, got {first_bullet_diff}"
            )
        trace_sha = _trace_sha256(trace_path)
        if trace_sha != rep["trace_sha256"]:
            raise RuntimeError(
                f"{rep['name']} trace sha drifted: expected {rep['trace_sha256']}, got {trace_sha}"
            )
        if rep["group"] == "shared":
            if shared_trace_sha is None:
                shared_trace_sha = trace_sha
            elif shared_trace_sha != trace_sha:
                raise RuntimeError(
                    f"shared basin trace mismatch: expected {shared_trace_sha}, got {trace_sha} for {rep['name']}"
                )
        else:
            if shoulder_trace_sha is None:
                shoulder_trace_sha = trace_sha
            elif shoulder_trace_sha != trace_sha:
                raise RuntimeError(
                    f"shoulder trace mismatch: expected {shoulder_trace_sha}, got {trace_sha} for {rep['name']}"
                )
        headless_cases.append(
            {
                "name": rep["name"],
                "group": rep["group"],
                "value": rep["value"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "payload_path": str(payload_path.resolve()),
                "payload_sha256": rep["payload_sha256"],
                "result": str(result_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha,
                "tail": tail,
                "first_bullet_diff": first_bullet_diff,
                "findings": ordered_findings,
                "command": result["command"],
            }
        )
        if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()

    if shared_trace_sha != EXPECTED_SHARED_TRACE_SHA256:
        raise RuntimeError(
            f"shared trace sha drifted: expected {EXPECTED_SHARED_TRACE_SHA256}, got {shared_trace_sha}"
        )
    if shoulder_trace_sha != EXPECTED_SHOULDER_TRACE_SHA256:
        raise RuntimeError(
            f"shoulder trace sha drifted: expected {EXPECTED_SHOULDER_TRACE_SHA256}, got {shoulder_trace_sha}"
        )
    if shared_trace_sha == shoulder_trace_sha:
        raise RuntimeError("shared basin and shoulder unexpectedly collapsed to one trace")

    summary: dict[str, object] = {
        "finding": "semantic/stage6-shoot-interval-cross-value-volley-split",
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
        "trace_groups": {
            "shared": {
                "trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
                "members": [
                    rep["name"]
                    for rep in REPRESENTATIVES
                    if rep["group"] == "shared"
                ],
            },
            "shoulder": {
                "trace_sha256": EXPECTED_SHOULDER_TRACE_SHA256,
                "members": [
                    rep["name"]
                    for rep in REPRESENTATIVES
                    if rep["group"] == "shoulder"
                ],
            },
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
            "6",
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
