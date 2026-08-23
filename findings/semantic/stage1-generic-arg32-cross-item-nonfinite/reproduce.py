from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl
from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch, sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.interestingness.rules import load_trace_records
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


FINDING_NAME = "semantic/stage1-generic-arg32-cross-item-nonfinite"
TARGET_SEED_ECL = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata1.ecl"
TARGET_STAGE = 1
TARGET_SEED = 7
TARGET_DIFFICULTY = 3
TARGET_CHARACTER = 0
TARGET_SHOT_TYPE = 0
TARGET_MAX_TICKS = 600
EXPECTED_TARGET_SHA256 = "4d6e7938054d48b137127fd3e1021a6c3d370920ed17a87f580e5bf6604dc3a6"
EXPECTED_FINDING_KINDS = {
    "non-finite",
    "score-drift",
    "enemy-count-drift",
}
EXPECTED_TAIL = {
    "tick": 257,
    "terminal_reason": "physical-hit",
    "game_frame": 257,
    "score": 2650,
    "enemy_count": 1,
    "stage_vm": {
        "loaded": True,
        "script_time": 257,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 257,
        "next_time": 272,
    },
    "entity_metrics": {
        "items_non_finite": 1,
        "bullets_non_finite": 0,
        "lasers_non_finite": 0,
    },
}


def _here() -> Path:
    return Path(__file__).resolve().parent


def _target_mutant() -> PayloadMutant:
    seed_payload = TARGET_SEED_ECL.read_bytes()
    ecl = parse_ecl(seed_payload)
    instruction = ecl.subs[0].instructions[3]
    canonical_seed_payload = serialize_ecl(ecl)
    patch = load_payload_patch(_here() / "payload_generic_arg32_cross_neg3692_64.json")
    payload = apply_payload_patch(canonical_seed_payload, patch)
    payload_sha256 = sha256_bytes(payload)
    if payload_sha256 != EXPECTED_TARGET_SHA256:
        raise RuntimeError(
            f"target sha256 drifted: expected {EXPECTED_TARGET_SHA256}, got {payload_sha256}"
        )
    return PayloadMutant(
        name="generic-arg32-cross-neg3692-64",
        payload=payload,
        source="ir-exact",
        path=(0, 3),
        metadata={
            "family": "generic-arg32-cross",
            "field_left": "generic",
            "field_right": "generic",
            "left_offset": 0,
            "right_offset": 4,
            "left_value": -3692,
            "right_value": 64,
            "opcode": instruction.opcode,
            "strategy": "exact-i32-pair",
        },
    )


def _assert_tail(record: dict[str, object], expected: dict[str, object]) -> None:
    for key, expected_value in expected.items():
        actual_value = record.get(key)
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict):
                raise RuntimeError(f"tail field {key!r} is not a dict: {actual_value!r}")
            _assert_tail(actual_value, expected_value)
            continue
        if actual_value != expected_value:
            raise RuntimeError(f"tail field {key!r} drifted: expected {expected_value!r}, got {actual_value!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 1 generic arg32-cross item non-finite finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage1-generic-arg32-cross-item-nonfinite",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--no-reuse-worker-game-dir", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    worker_game_dir = artifact_dir / "worker-game"
    worker_manifest = prepare_worker_game_dir(
        source_game_dir=args.game_dir.resolve(),
        destination=worker_game_dir,
        worker_name="finding-stage1-generic-arg32-cross-item-nonfinite",
        reuse=not args.no_reuse_worker_game_dir,
    )

    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        resource_override_dir=None,
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        action_file=DEFAULT_ACTION_FILE.resolve(),
        artifact_dir=baseline_dir,
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=True,
        continue_after_hit=False,
        trace_compact_counts=True,
        log_path=baseline_dir / "run.log",
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_records = load_trace_records(baseline_trace)

    result = run_case(
        binary=args.headless_bin.resolve(),
        game_dir=worker_game_dir.resolve(),
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        action_file=DEFAULT_ACTION_FILE.resolve(),
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=True,
        continue_after_hit=False,
        timeout_seconds=5.0,
        trace_compact_counts=True,
        campaign_dir=artifact_dir,
        seed_name=TARGET_SEED_ECL.name,
        mutant=_target_mutant(),
        case_index=1,
        baseline_trace=baseline_trace,
        baseline_records=baseline_records,
    )

    finding_kinds = {str(entry["kind"]) for entry in result["findings"]}  # type: ignore[index]
    missing = sorted(EXPECTED_FINDING_KINDS - finding_kinds)
    if missing:
        raise RuntimeError(f"missing expected findings: {missing}")
    if result["returncode"] != 0 or bool(result["timed_out"]):
        raise RuntimeError(f"unexpected process result: returncode={result['returncode']} timed_out={result['timed_out']}")

    trace_records = load_trace_records(Path(str(result["trace"])))
    non_finite_records = [
        record
        for record in trace_records
        if isinstance(record.get("entity_metrics"), dict)
        and int(record["entity_metrics"].get("items_non_finite", 0)) > 0  # type: ignore[index]
    ]
    if not non_finite_records:
        raise RuntimeError("trace did not contain any item non-finite records")
    _assert_tail(trace_records[-1], EXPECTED_TAIL)

    summary = {
        "finding": FINDING_NAME,
        "worker_manifest": worker_manifest,
        "baseline_trace": str(baseline_trace.resolve()),
        "case_result": result,
        "first_non_finite_record": non_finite_records[0],
        "tail": trace_records[-1],
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
