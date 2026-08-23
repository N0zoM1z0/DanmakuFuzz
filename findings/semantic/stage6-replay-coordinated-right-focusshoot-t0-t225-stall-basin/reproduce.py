from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from danmakufuzz.headless.actions import (
    action_token_to_input_mask,
    parse_actions_file,
    serialize_mask_actions,
)
from danmakufuzz.headless.baseline import (
    DEFAULT_GAME_DIR,
    build_command,
    default_headless_binary,
    run_baseline,
)
from danmakufuzz.interestingness.rules import load_trace_records
from danmakufuzz.parser.replay import (
    build_replay_with_stage_slots,
    encode_stage_replay_data,
    input_masks_to_replay_bookmarks,
    replay_stage_action_masks,
)
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory
from danmakufuzz.semantic.input_campaign import _filter_findings, _repeat_desync_findings, _run_once


FINDING_NAME = "semantic/stage6-replay-coordinated-right-focusshoot-t0-t225-stall-basin"
TARGET_STAGE = 6
TARGET_SEED = 7
TARGET_DIFFICULTY = 3
TARGET_CHARACTER = 0
TARGET_SHOT_TYPE = 0
TARGET_MAX_TICKS = 1800
EXPECTED_BASELINE_TRACE_SHA256 = "38a75fd1be0435713db30159f4b43b3491916370eabb18f8ba55b7b8aa21bab2"
EXPECTED_MUTANT_TRACE_SHA256 = "783d4b8f1bb48412904e53ab9e2042b81e7f1f59bbdd61622c5f6f9744224e59"
EXPECTED_FINDING_KINDS = {
    "stalled-progress",
    "stalled-frame",
    "stage-script-drift",
    "ecl-timeline-drift",
}
EXPECTED_FINDING_DETAILS = {
    "stalled-progress": (
        "frame=1489 window>=240 tick=1729 game_frame=1489 rng_generation=16322 "
        "stage_vm.loaded=False stage_vm.script_time=1489 stage_vm.instruction_index=4 "
        "ecl_timeline.time=1489 ecl_timeline.next_time=1544"
    ),
    "stalled-frame": "frame 1489 repeated >= 240 times",
    "stage-script-drift": "tick 1505 stage_vm.loaded baseline=True case=False",
    "ecl-timeline-drift": "tick 1505 ecl_timeline.time baseline=1505 case=1489",
}
EXPECTED_BASELINE_TAIL = {
    "tick": 1800,
    "terminal_reason": "tick-limit",
    "game_frame": 1731,
    "score": 1578580,
    "enemy_count": 6,
    "input": 5,
    "lives": 0,
    "bombs": 3,
    "stage_vm": {
        "loaded": False,
        "script_time": 1731,
        "instruction_index": 5,
    },
    "ecl_timeline": {
        "time": 1731,
        "next_time": 1784,
    },
}
EXPECTED_MUTANT_TAIL = {
    "tick": 1800,
    "terminal_reason": "tick-limit",
    "game_frame": 1489,
    "score": 1576650,
    "enemy_count": 4,
    "input": 5,
    "lives": 0,
    "bombs": 3,
    "stage_vm": {
        "loaded": False,
        "script_time": 1489,
        "instruction_index": 4,
    },
    "ecl_timeline": {
        "time": 1489,
        "next_time": 1544,
    },
}


def _here() -> Path:
    return Path(__file__).resolve().parent


def _assert_tail(label: str, record: dict[str, object], expected: dict[str, object]) -> None:
    for key, expected_value in expected.items():
        actual_value = record.get(key)
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict):
                raise RuntimeError(f"{label} tail field {key!r} is not a dict: {actual_value!r}")
            for child_key, child_expected in expected_value.items():
                child_actual = actual_value.get(child_key)
                if child_actual != child_expected:
                    raise RuntimeError(
                        f"{label} tail field {key}.{child_key} drifted: expected {child_expected!r}, got {child_actual!r}"
                    )
            continue
        if actual_value != expected_value:
            raise RuntimeError(
                f"{label} tail field {key!r} drifted: expected {expected_value!r}, got {actual_value!r}"
            )


def _trace_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _masks_from_actions(action_file: Path, *, auto_shoot: bool) -> list[int]:
    stream = parse_actions_file(action_file)
    return [
        action_token_to_input_mask(action, auto_shoot=auto_shoot)
        for action in stream.actions
    ]


def _build_seed_replay(stage_masks: list[int]) -> bytes:
    stage_payload = encode_stage_replay_data(
        input_bookmarks=input_masks_to_replay_bookmarks(stage_masks),
        random_seed=7,
        power=0,
        lives_remaining=2,
        bombs_remaining=3,
        rank=0,
    )
    stage_slots: list[bytes | None] = [None] * 7
    stage_slots[TARGET_STAGE - 1] = stage_payload
    return build_replay_with_stage_slots(
        shottype_chara=(TARGET_CHARACTER * 2) + TARGET_SHOT_TYPE,
        difficulty=TARGET_DIFFICULTY,
        stage_payloads_by_slot=stage_slots,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 replay coordinated right/focus/shoot stall basin."
    )
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument(
        "--baseline-actions",
        type=Path,
        default=Path("config/headless_baseline_actions_1800.txt"),
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR
        / "findings"
        / "semantic-stage6-replay-coordinated-right-focusshoot-t0-t225-stall-basin",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    binary = args.headless_bin.resolve()
    game_dir = args.game_dir.resolve()
    baseline_actions_source = args.baseline_actions.resolve()
    payload_actions = (_here() / "payload_actions.txt").resolve()

    baseline_masks = _masks_from_actions(baseline_actions_source, auto_shoot=True)
    baseline_actions_path = artifact_dir / "baseline-actions.txt"
    baseline_actions_path.write_text(
        serialize_mask_actions(baseline_masks[:TARGET_MAX_TICKS]),
        encoding="utf-8",
    )

    payload_masks = _masks_from_actions(payload_actions, auto_shoot=False)
    if len(payload_masks) != TARGET_MAX_TICKS:
        raise RuntimeError(
            f"payload length drifted: expected {TARGET_MAX_TICKS}, got {len(payload_masks)}"
        )
    replay_payload = _build_seed_replay(payload_masks)
    replay_path = artifact_dir / "input.rpy"
    replay_path.write_bytes(replay_payload)
    roundtrip_masks = replay_stage_action_masks(replay_payload, TARGET_STAGE, max_frames=TARGET_MAX_TICKS)
    if roundtrip_masks != payload_masks:
        raise RuntimeError("replay roundtrip drifted away from payload masks")

    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=binary,
        game_dir=game_dir,
        resource_override_dir=None,
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        action_file=baseline_actions_path,
        artifact_dir=baseline_dir,
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=False,
        continue_after_hit=True,
        trace_compact_counts=True,
        log_path=baseline_dir / "run.log",
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_trace_sha256 = _trace_sha256(baseline_trace)
    if baseline_trace_sha256 != EXPECTED_BASELINE_TRACE_SHA256:
        raise RuntimeError(
            "baseline trace hash drifted: "
            f"expected {EXPECTED_BASELINE_TRACE_SHA256}, got {baseline_trace_sha256}"
        )
    baseline_records = load_trace_records(baseline_trace)
    _assert_tail("baseline", baseline_records[-1], EXPECTED_BASELINE_TAIL)

    run_a = _run_once(
        binary=binary,
        game_dir=game_dir,
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        action_file=payload_actions,
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=False,
        continue_after_hit=True,
        timeout_seconds=8.0,
        trace_compact_counts=True,
        trace_path=artifact_dir / "trace-a.jsonl",
        log_path=artifact_dir / "run-a.log",
        baseline_records=baseline_records,
    )
    run_b = _run_once(
        binary=binary,
        game_dir=game_dir,
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        action_file=payload_actions,
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=False,
        continue_after_hit=True,
        timeout_seconds=8.0,
        trace_compact_counts=True,
        trace_path=artifact_dir / "trace-b.jsonl",
        log_path=artifact_dir / "run-b.log",
        baseline_records=baseline_records,
    )
    if int(run_a["returncode"]) != 0 or int(run_b["returncode"]) != 0:
        raise RuntimeError(f"mutant run failed: run_a={run_a['returncode']} run_b={run_b['returncode']}")
    if str(run_a["trace_sha256"]) != str(run_b["trace_sha256"]):
        raise RuntimeError(
            f"repeat trace hash drifted: {run_a['trace_sha256']} != {run_b['trace_sha256']}"
        )
    if str(run_a["trace_sha256"]) != EXPECTED_MUTANT_TRACE_SHA256:
        raise RuntimeError(
            "mutant trace hash drifted: "
            f"expected {EXPECTED_MUTANT_TRACE_SHA256}, got {run_a['trace_sha256']}"
        )

    mutant_records = load_trace_records(Path(str(run_a["trace"])))
    _assert_tail("mutant", mutant_records[-1], EXPECTED_MUTANT_TAIL)

    findings = list(run_a["findings"])
    findings.extend(_repeat_desync_findings(run_a, run_b))
    filtered = _filter_findings(findings)
    finding_rows = [{"kind": finding.kind, "detail": finding.detail} for finding in filtered]
    finding_kinds = {row["kind"] for row in finding_rows}
    if finding_kinds != EXPECTED_FINDING_KINDS:
        raise RuntimeError(f"finding kinds drifted: expected {EXPECTED_FINDING_KINDS}, got {finding_kinds}")
    finding_map = {row["kind"]: row["detail"] for row in finding_rows}
    for kind, expected_detail in EXPECTED_FINDING_DETAILS.items():
        if finding_map.get(kind) != expected_detail:
            raise RuntimeError(
                f"{kind} detail drifted: expected {expected_detail!r}, got {finding_map.get(kind)!r}"
            )

    summary = {
        "finding": FINDING_NAME,
        "payload_actions": str(payload_actions),
        "baseline_actions": str(baseline_actions_source),
        "generated_replay": str(replay_path),
        "baseline_trace_sha256": baseline_trace_sha256,
        "baseline": baseline_metadata,
        "run_a": {key: value for key, value in run_a.items() if key != "findings"},
        "run_b": {key: value for key, value in run_b.items() if key != "findings"},
        "findings": finding_rows,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
