from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl
from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch, sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import LONG_ACTION_FILE, run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant
from danmakufuzz.semantic.trace_basins import (
    _first_divergence,
    _first_negative_next_time,
    _load_normalized_trace,
    _signature,
    _sink_snapshot,
)


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata3.ecl"
EXPECTED_SHARED_SIGNATURE = "83214f07b8e735a3dc4dc894c562c44385e3cc9680ca4a7983f10539b8e5a6f1"
EXPECTED_SHARED_SINK_TICK = 1347
EXPECTED_SHARED_SINK_TIME = 1345
EXPECTED_SHARED_NEXT_TIME = -9163
DEFAULT_ARTIFACT_DIR_CANDIDATES = (
    ARTIFACTS_DIR / "tmp-stage3-generic-basin-retry-bc2",
    ARTIFACTS_DIR / "tmp-stage3-generic-basin-retry",
    ARTIFACTS_DIR / "tmp-stage3-generic-basin-retry-b",
)

REPRESENTATIVES = (
    {
        "name": "bullet-count1-four",
        "path": (0, 3),
        "patch": "payload_bullet_count1_four.json",
        "target_sha256": "74ecede0d084e78043548fc3fd32f92df921e58968e87f9778891e88e1173c48",
        "checks": {
            "opcode": 67,
            "field_offset": 4,
            "original_value": 1,
            "mutated_value": 4,
            "field_name": "bullet_count1",
            "family": "bullet-count1",
        },
    },
    {
        "name": "bullet-count2-eight",
        "path": (1, 3),
        "patch": "payload_bullet_count2_eight.json",
        "target_sha256": "848ca71719a34bfce786faf0bfa2321678fea76718a138bd7feadfc6fd2196a1",
        "checks": {
            "opcode": 67,
            "field_offset": 8,
            "original_value": 1,
            "mutated_value": 8,
            "field_name": "bullet_count2",
            "family": "bullet-count2",
        },
    },
    {
        "name": "shoot-interval-sixtyfour",
        "path": (0, 6),
        "patch": "payload_shoot_interval_sixtyfour.json",
        "target_sha256": "bd530ac2c6fae09c52280f68cc8618905597d71b279188ac08ee0a0e802fa963",
        "checks": {
            "opcode": 76,
            "field_offset": 0,
            "original_value": 60,
            "mutated_value": 64,
            "field_name": "interval",
            "family": "shoot-interval",
        },
    },
)


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = rep["path"]  # type: ignore[misc]
    checks = rep["checks"]  # type: ignore[assignment]
    assert isinstance(checks, dict)
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    expected_opcode = int(checks["opcode"])
    if instruction.opcode != expected_opcode:
        raise RuntimeError(f"{rep['name']} opcode drifted: expected {expected_opcode}, got {instruction.opcode}")
    field_offset = int(checks["field_offset"])
    original_value = int.from_bytes(instruction.args[field_offset:field_offset + 4], "little", signed=True)
    expected_original = int(checks["original_value"])
    if original_value != expected_original:
        raise RuntimeError(
            f"{rep['name']} original value drifted: expected {expected_original}, got {original_value}"
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

    return PayloadMutant(
        name=str(rep["name"]),
        payload=payload,
        source="ir-exact",
        path=(sub_index, instruction_index),
        metadata={
            "family": str(checks["family"]),
            "field_name": str(checks["field_name"]),
            "value": int(checks["mutated_value"]),
            "original_value": expected_original,
            "strategy": "exact-i32",
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 3 generic cross-family negative-next-time basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--no-reuse-worker-game-dir", action="store_true")
    parser.add_argument("--max-attempts-per-case", type=int, default=6)
    return parser.parse_args()


def _case_sink_summary(*, baseline_trace: Path, case_trace: Path) -> dict[str, object]:
    baseline_rows = _load_normalized_trace(baseline_trace, pos_round=4)
    case_rows = _load_normalized_trace(case_trace, pos_round=4)
    first_divergence_record, first_divergence_keys = _first_divergence(baseline_rows, case_rows)
    sink_record = _first_negative_next_time(case_rows)
    if sink_record is None:
        raise RuntimeError(f"case did not reach a negative next_time sink: {case_trace}")
    sink_snapshot = _sink_snapshot(sink_record)
    signature = _signature(sink_snapshot)
    timeline = sink_record.get("ecl_timeline")
    sink_time = timeline.get("time") if isinstance(timeline, dict) else None
    sink_next_time = timeline.get("next_time") if isinstance(timeline, dict) else None
    return {
        "first_divergence_tick": first_divergence_record["tick"] if first_divergence_record is not None else None,
        "first_divergence_keys": list(first_divergence_keys or []),
        "sink_signature": signature,
        "sink_tick": sink_record["tick"],
        "sink_time": sink_time,
        "sink_next_time": sink_next_time,
    }


def _run_once(*, artifact_dir: Path, args: argparse.Namespace) -> dict[str, object]:
    ensure_directory(artifact_dir)
    baseline_worker_game_dir = artifact_dir / "worker-baseline"
    baseline_worker_prepare = prepare_worker_game_dir(
        source_game_dir=args.game_dir.resolve(),
        destination=baseline_worker_game_dir,
        worker_name="tmp-generic-baseline",
        reuse=not args.no_reuse_worker_game_dir,
    )

    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=baseline_worker_game_dir.resolve(),
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

    cases: list[dict[str, object]] = []
    for case_index, rep in enumerate(REPRESENTATIVES, start=1):
        mutant = _target_mutant(rep)
        success: dict[str, object] | None = None
        failures: list[dict[str, object]] = []
        for attempt_index in range(1, args.max_attempts_per_case + 1):
            attempt_dir = artifact_dir / f"attempt-{case_index:02d}-{attempt_index:02d}"
            ensure_directory(attempt_dir)
            case_worker_game_dir = attempt_dir / f"worker-{case_index}"
            case_worker_prepare = prepare_worker_game_dir(
                source_game_dir=args.game_dir.resolve(),
                destination=case_worker_game_dir,
                worker_name=f"tmp-generic-{case_index}-a{attempt_index}",
                reuse=not args.no_reuse_worker_game_dir,
            )
            result = run_case(
                binary=args.headless_bin.resolve(),
                game_dir=case_worker_game_dir.resolve(),
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
                campaign_dir=attempt_dir,
                seed_name=TARGET_SEED.name,
                mutant=mutant,
                case_index=case_index,
                baseline_trace=baseline_trace,
            )
            result_path = attempt_dir / result["case_name"] / "result.json"
            trace_path = Path(str(result["trace"]))
            try:
                sink = _case_sink_summary(baseline_trace=baseline_trace, case_trace=trace_path)
            except RuntimeError as exc:
                failures.append(
                    {
                        "attempt": attempt_index,
                        "result": str(result_path.resolve()),
                        "trace": str(trace_path.resolve()),
                        "reason": str(exc),
                    }
                )
                continue
            if (
                sink["sink_signature"] == EXPECTED_SHARED_SIGNATURE
                and sink["sink_tick"] == EXPECTED_SHARED_SINK_TICK
                and sink["sink_time"] == EXPECTED_SHARED_SINK_TIME
                and sink["sink_next_time"] == EXPECTED_SHARED_NEXT_TIME
            ):
                success = {
                    "attempt": attempt_index,
                    "result": result,
                    "result_path": result_path,
                    "trace_path": trace_path,
                    "worker_game_dir": case_worker_game_dir,
                    "worker_game_prepare": case_worker_prepare,
                    "sink": sink,
                }
                break
            failures.append(
                {
                    "attempt": attempt_index,
                    "result": str(result_path.resolve()),
                    "trace": str(trace_path.resolve()),
                    "reason": (
                        f"unexpected sink signature={sink['sink_signature']} "
                        f"tick={sink['sink_tick']} time={sink['sink_time']} next_time={sink['sink_next_time']}"
                    ),
                }
            )
        if success is None:
            raise RuntimeError(
                f"{rep['name']} did not reach the expected shared sink after "
                f"{args.max_attempts_per_case} attempts: {json.dumps(failures, indent=2)}"
            )
        result = success["result"]
        assert isinstance(result, dict)
        result_path = success["result_path"]
        trace_path = success["trace_path"]
        case_worker_game_dir = success["worker_game_dir"]
        case_worker_prepare = success["worker_game_prepare"]
        sink = success["sink"]
        cases.append(
            {
                "representative": rep["name"],
                "path": {
                    "sub_index": mutant.path[0],
                    "instruction_index": mutant.path[1],
                },
                "mutation_metadata": mutant.metadata,
                "result": str(result_path.resolve()),
                "trace": str(trace_path.resolve()),
                "log": result["log"],
                "findings": result["findings"],
                "attempts_used": success["attempt"],
                "attempt_failures": failures,
                "worker_game_dir": str(case_worker_game_dir.resolve()),
                "worker_game_prepare": case_worker_prepare,
                "sink": sink,
            }
        )

    signature_set = {str(case["sink"]["sink_signature"]) for case in cases}  # type: ignore[index]
    if signature_set != {EXPECTED_SHARED_SIGNATURE}:
        raise RuntimeError(f"representatives did not converge on one shared signature: {sorted(signature_set)}")

    summary = {
        "finding": "semantic/stage3-next-time-negative-cross-family-basin",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "worker_game_dir": str(baseline_worker_game_dir.resolve()),
            "worker_game_prepare": baseline_worker_prepare,
            "command": baseline_metadata["command"],
        },
        "expected_shared_sink": {
            "signature": EXPECTED_SHARED_SIGNATURE,
            "tick": EXPECTED_SHARED_SINK_TICK,
            "time": EXPECTED_SHARED_SINK_TIME,
            "next_time": EXPECTED_SHARED_NEXT_TIME,
        },
        "cases": cases,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    if not TARGET_SEED.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {TARGET_SEED}")

    artifact_dirs = (
        [args.artifact_dir.resolve()]
        if args.artifact_dir is not None
        else [path.resolve() for path in DEFAULT_ARTIFACT_DIR_CANDIDATES]
    )
    failures: list[dict[str, object]] = []
    for artifact_dir in artifact_dirs:
        try:
            summary = _run_once(artifact_dir=artifact_dir, args=args)
        except RuntimeError as exc:
            if args.artifact_dir is not None:
                raise
            failures.append(
                {
                    "artifact_dir": str(artifact_dir),
                    "reason": str(exc),
                }
            )
            continue
        if failures:
            summary["artifact_dir_fallback_failures"] = failures
            summary_path = artifact_dir / "summary.json"
            summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    raise RuntimeError(
        "stage3 cross-family reproducer exhausted default artifact roots without reaching the shared sink: "
        + json.dumps(failures, indent=2)
    )


if __name__ == "__main__":
    raise SystemExit(main())
