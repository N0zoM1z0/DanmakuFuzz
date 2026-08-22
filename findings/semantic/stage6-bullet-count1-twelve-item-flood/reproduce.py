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


TARGET_MUTANT_NAME = "bullet-count1-twelve"
TARGET_MUTANT_PATH = (2, 3)
TARGET_COUNT1_VALUE = 12
TARGET_ORIGINAL_COUNT1_VALUE = 6
TARGET_ORIGINAL_COUNT2_VALUE = 2
TARGET_OPCODE = 75
TARGET_PAYLOAD_SHA256 = "4cb4090a7201fe3133323e8e7ed0cbba893b9a6e7267839d675e4bda73d5ddcc"
TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
PAYLOAD_PATCH_PATH = Path(__file__).with_name("payload_patch.json")


def _target_mutant() -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_MUTANT_PATH
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
            "family": "bullet-count1",
            "value": TARGET_COUNT1_VALUE,
            "original_value": TARGET_ORIGINAL_COUNT1_VALUE,
            "strategy": "exact-i32",
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 bullet-count1=12 item-flood finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-bullet-count1-twelve-item-flood",
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
        worker_name="stage6-bullet-count1-twelve",
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
    mutant = _target_mutant()
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
        case_index=1,
        baseline_trace=baseline_trace,
    )
    result_path = artifact_dir / result["case_name"] / "result.json"
    payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
    summary: dict[str, object] = {
        "finding": "semantic/stage6-bullet-count1-twelve-item-flood",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_mutant": {
            "name": TARGET_MUTANT_NAME,
            "path": {
                "sub_index": TARGET_MUTANT_PATH[0],
                "instruction_index": TARGET_MUTANT_PATH[1],
            },
            "opcode": TARGET_OPCODE,
            "original_bullet_count1": TARGET_ORIGINAL_COUNT1_VALUE,
            "original_bullet_count2": TARGET_ORIGINAL_COUNT2_VALUE,
            "mutated_bullet_count1": TARGET_COUNT1_VALUE,
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
        }

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
