from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl
from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch, sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import LONG_ACTION_FILE, run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


TARGET_MUTANT_NAME = "call-sub-zero"
TARGET_MUTANT_PATH = (9, 15)
TARGET_CALL_VALUE = 0
TARGET_ORIGINAL_CALL_VALUE = 10
TARGET_SUB_COUNT = 35
TARGET_PAYLOAD_SHA256 = "9f3a049c6c51da360f19287fb0bc37a6ec25209bd61147e2aab48cd50d0e4f74"
TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata3.ecl"
PAYLOAD_PATCH_PATH = Path(__file__).with_name("payload_patch.json")


def _target_mutant() -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    if ecl.sub_count != TARGET_SUB_COUNT:
        raise RuntimeError(f"target sub_count drifted: expected {TARGET_SUB_COUNT}, got {ecl.sub_count}")
    sub_index, instruction_index = TARGET_MUTANT_PATH
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    original_call_value = int.from_bytes(instruction.args[:4], "little", signed=True)
    if original_call_value != TARGET_ORIGINAL_CALL_VALUE:
        raise RuntimeError(
            f"target call value drifted: expected {TARGET_ORIGINAL_CALL_VALUE}, got {original_call_value}"
        )
    if not PAYLOAD_PATCH_PATH.is_file():
        raise FileNotFoundError(f"missing payload patch: {PAYLOAD_PATCH_PATH}")
    canonical_seed_payload = serialize_ecl(ecl)
    payload_patch = load_payload_patch(PAYLOAD_PATCH_PATH)
    payload = apply_payload_patch(canonical_seed_payload, payload_patch)
    payload_sha256 = sha256_bytes(payload)
    if payload_sha256 != TARGET_PAYLOAD_SHA256:
        raise RuntimeError(
            f"target mutant sha256 drifted: expected {TARGET_PAYLOAD_SHA256}, got {payload_sha256}"
        )
    return PayloadMutant(
        name=TARGET_MUTANT_NAME,
        payload=payload,
        source="ir-exact",
        path=TARGET_MUTANT_PATH,
        metadata={
            "family": "call-sub",
            "value": TARGET_CALL_VALUE,
            "original_value": TARGET_ORIGINAL_CALL_VALUE,
            "sub_count": TARGET_SUB_COUNT,
            "strategy": "exact-i32",
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 3 in-range call-sub next-time corruption finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage3-call-sub-zero-a",
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
        worker_name="stage3-call-sub-zero",
        reuse=not args.no_reuse_worker_game_dir,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        resource_override_dir=None,
        stage=3,
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
    mutant = _target_mutant()
    result = run_case(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        stage=3,
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
        case_index=1,
        baseline_trace=baseline_trace,
    )
    result_path = artifact_dir / result["case_name"] / "result.json"
    payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
    summary: dict[str, object] = {
        "finding": "semantic/stage3-call-sub-zero-in-range-next-time-negative",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_mutant": {
            "name": TARGET_MUTANT_NAME,
            "path": {
                "sub_index": TARGET_MUTANT_PATH[0],
                "instruction_index": TARGET_MUTANT_PATH[1],
            },
            "original_call_value": TARGET_ORIGINAL_CALL_VALUE,
            "mutated_call_value": TARGET_CALL_VALUE,
            "sub_count": TARGET_SUB_COUNT,
            "payload_sha256": TARGET_PAYLOAD_SHA256,
            "payload_patch": str(PAYLOAD_PATCH_PATH.resolve()),
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "worker_game_dir": str(worker_game_dir.resolve()),
            "worker_game_prepare": worker_prepare,
            "command": baseline_metadata["command"],
        },
        "headless": {
            "result": str(result_path.resolve()),
            "payload_path": str(payload_path.resolve()),
            "trace": result["trace"],
            "log": result["log"],
            "findings": result["findings"],
            "command": result["command"],
        },
    }

    if args.retail:
        retail_dir = artifact_dir / "retail"
        command = [
            sys.executable,
            "-m",
            "danmakufuzz.retail.confirm_case",
            "--result",
            str(result_path.resolve()),
            "--artifact-dir",
            str(retail_dir.resolve()),
            "--practice-stage",
            "3",
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
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
