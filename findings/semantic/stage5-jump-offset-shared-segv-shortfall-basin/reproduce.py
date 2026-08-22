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


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata5.ecl"
TARGET_OPCODE = 3
TARGET_PATH = (0, 14)
TARGET_ORIGINAL_OFFSET_VALUE = -224
EXPECTED_FINDINGS = [
    {"kind": "process-signal", "detail": "SIGSEGV"},
    {"kind": "trace-shortfall", "detail": "tick_count=514 baseline_tick_count=600"},
]
EXPECTED_RETURN_CODE = -11
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
EXPECTED_SHARED_TRACE_SHA256 = "86e64cd169c20b0274e9916f370ab18c8d770e0c6a1a97730eb0e64cbe8dfa3f"
EXPECTED_SHARED_TRACE_ROWS = 514
EXPECTED_SHARED_TAIL = {
    "tick": 514,
    "game_frame": 514,
    "score": 1220,
    "lives": 2,
    "bombs": 3,
    "power": 128,
    "enemy_count": 2,
    "item_count": 0,
    "bullet_count": 80,
    "stage_vm": {
        "loaded": True,
        "script_time": 514,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 514,
        "next_time": 690,
    },
    "terminal_reason": None,
}
RETAIL_REPRESENTATIVE_NAME = "jump-offset-neg1073742048"

REPRESENTATIVES = (
    {
        "name": "jump-offset-neg1073742048",
        "value": -1073742048,
        "patch": "payload_jump_offset_neg1073742048.json",
        "payload_sha256": "caf6c363fbb5a93b64040ed857a6aa76dd94a037ba2bb87d4f05fdf15782663d",
    },
    {
        "name": "jump-offset-252821401",
        "value": 252821401,
        "patch": "payload_jump_offset_252821401.json",
        "payload_sha256": "ca115ed102e44d2508dfd27f55d8c64d66165d943f08024468176bb114dd0a92",
    },
    {
        "name": "jump-offset-neg2147483603",
        "value": -2147483603,
        "patch": "payload_jump_offset_neg2147483603.json",
        "payload_sha256": "9ddafad3526cdd66128cbed0b4e8feb710519300cc72bf8abf45e0ce38f5d86f",
    },
    {
        "name": "jump-offset-neg1441649695",
        "value": -1441649695,
        "patch": "payload_jump_offset_neg1441649695.json",
        "payload_sha256": "188febd7e9ef87d54d2995005a6b17ac7efb775ed1addc2e62801bf80a79c839",
    },
)


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
        description="Reproduce the Stage 5 shared jump-offset SIGSEGV shortfall basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage5-jump-offset-shared-segv-shortfall-basin",
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
        worker_name="stage5-jump-offset-shared-segv-shortfall-basin",
        reuse=not args.no_reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        resource_override_dir=None,
        stage=5,
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
    baseline_trace_bytes = baseline_trace.read_bytes().splitlines(True)

    headless_cases: list[dict[str, object]] = []
    retail_result_path: Path | None = None
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
        result = run_case(
            binary=args.headless_bin.resolve(),
            game_dir=worker_game_dir.resolve(),
            stage=5,
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
        ordered_findings = _ordered_findings(result)
        if ordered_findings != EXPECTED_FINDINGS:
            raise RuntimeError(f"{rep['name']} findings drifted: expected {EXPECTED_FINDINGS}, got {ordered_findings}")
        if int(result.get("returncode", 0)) != EXPECTED_RETURN_CODE:
            raise RuntimeError(
                f"{rep['name']} returncode drifted: expected {EXPECTED_RETURN_CODE}, got {result.get('returncode')}"
            )

        result_path = artifact_dir / str(result["case_name"]) / "result.json"
        payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
        trace_path = Path(str(result["trace"]))
        trace_sha256 = _trace_sha256(trace_path)
        if trace_sha256 != EXPECTED_SHARED_TRACE_SHA256:
            raise RuntimeError(
                f"{rep['name']} trace drifted: expected {EXPECTED_SHARED_TRACE_SHA256}, got {trace_sha256}"
            )

        case_rows = _load_trace(trace_path)
        if len(case_rows) != EXPECTED_SHARED_TRACE_ROWS:
            raise RuntimeError(
                f"{rep['name']} trace row count drifted: expected {EXPECTED_SHARED_TRACE_ROWS}, got {len(case_rows)}"
            )
        case_tail = _tail_summary(case_rows)
        if case_tail != EXPECTED_SHARED_TAIL:
            raise RuntimeError(
                f"{rep['name']} tail drifted: expected {EXPECTED_SHARED_TAIL}, got {case_tail}"
            )
        case_trace_bytes = trace_path.read_bytes().splitlines(True)
        if baseline_trace_bytes[:len(case_trace_bytes)] != case_trace_bytes:
            raise RuntimeError(f"{rep['name']} no longer matches the baseline prefix up to crash")

        headless_cases.append(
            {
                "name": rep["name"],
                "value": rep["value"],
                "payload_sha256": rep["payload_sha256"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "result": str(result_path.resolve()),
                "payload_path": str(payload_path.resolve()),
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "trace_rows": len(case_rows),
                "tail": case_tail,
                "findings": ordered_findings,
                "returncode": result["returncode"],
                "command": result["command"],
            }
        )
        if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()

    summary: dict[str, object] = {
        "finding": "semantic/stage5-jump-offset-shared-segv-shortfall-basin",
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
                    "payload_sha256": rep["payload_sha256"],
                    "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                }
                for rep in REPRESENTATIVES
            ],
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "tail": baseline_tail,
            "worker_game_dir": str(worker_game_dir.resolve()),
            "worker_game_prepare": worker_prepare,
            "command": baseline_metadata["command"],
        },
        "headless": {
            "shared_trace_sha256": EXPECTED_SHARED_TRACE_SHA256,
            "shared_trace_rows": EXPECTED_SHARED_TRACE_ROWS,
            "expected_findings": EXPECTED_FINDINGS,
            "expected_returncode": EXPECTED_RETURN_CODE,
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
            "5",
            "--difficulty",
            "3",
            "--timeout-seconds",
            str(args.retail_timeout_seconds),
        ]
        subprocess.run(command, check=True)
        summary["retail"] = {
            "representative": RETAIL_REPRESENTATIVE_NAME,
            "artifact_dir": str(retail_dir.resolve()),
            "report": str((retail_dir / "report.json").resolve()),
            "command": command,
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
