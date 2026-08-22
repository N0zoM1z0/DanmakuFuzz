from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl
from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch, sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


TARGET_PATH = (0, 1)
TARGET_OPCODE = 103
TARGET_ORIGINAL_TIME = 0
TARGET_MUTATED_TIME = 3
NEGATIVE_CONTROL_STAGE = 6
NEGATIVE_CONTROL_EXPECTED_OPCODE = 132
HEADLESS_SEED = 7
MAX_TICKS = 600
TIMEOUT_SECONDS = 5.0

EXPECTED_BASELINE_TAILS: dict[int, dict[str, Any]] = {
    1: {
        "tick": 311,
        "game_frame": 311,
        "score": 2450,
        "lives": 2,
        "bombs": 3,
        "power": 0,
        "enemy_count": 4,
        "item_count": 1,
        "bullet_count": 6,
        "stage_vm": {"loaded": True, "script_time": 311, "instruction_index": 3},
        "ecl_timeline": {"time": 311, "next_time": 320},
        "terminal_reason": "physical-hit",
    },
    2: {
        "tick": 535,
        "game_frame": 535,
        "score": 17240,
        "lives": 2,
        "bombs": 3,
        "power": 64,
        "enemy_count": 11,
        "item_count": 19,
        "bullet_count": 100,
        "stage_vm": {"loaded": True, "script_time": 535, "instruction_index": 3},
        "ecl_timeline": {"time": 535, "next_time": 540},
        "terminal_reason": "physical-hit",
    },
    3: {
        "tick": 600,
        "game_frame": 600,
        "score": 13000,
        "lives": 2,
        "bombs": 3,
        "power": 128,
        "enemy_count": 2,
        "item_count": 7,
        "bullet_count": 19,
        "stage_vm": {"loaded": True, "script_time": 600, "instruction_index": 3},
        "ecl_timeline": {"time": 600, "next_time": 600},
        "terminal_reason": "tick-limit",
    },
    4: {
        "tick": 600,
        "game_frame": 600,
        "score": 4380,
        "lives": 2,
        "bombs": 3,
        "power": 128,
        "enemy_count": 11,
        "item_count": 1,
        "bullet_count": 450,
        "stage_vm": {"loaded": True, "script_time": 600, "instruction_index": 3},
        "ecl_timeline": {"time": 600, "next_time": 1004},
        "terminal_reason": "tick-limit",
    },
    5: {
        "tick": 600,
        "game_frame": 600,
        "score": 5150,
        "lives": 2,
        "bombs": 3,
        "power": 128,
        "enemy_count": 1,
        "item_count": 1,
        "bullet_count": 328,
        "stage_vm": {"loaded": True, "script_time": 600, "instruction_index": 3},
        "ecl_timeline": {"time": 600, "next_time": 690},
        "terminal_reason": "tick-limit",
    },
}

REPRESENTATIVES = (
    {
        "name": "stage1-instruction-time-3",
        "stage": 1,
        "patch": "payload_stage1_instruction_time_3.json",
        "payload_sha256": "5bedd1be68d4b81fd0cb7729adab24121f31b6db8c62286ee1d1672874e49070",
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 263 baseline=780 case=0"},
            {"kind": "enemy-count-drift", "detail": "tick 274 baseline=4 case=7"},
        ],
        "expected_trace_sha256": "7ceec03eedb3c8c5f3a3a8ded939ab60390b003a87ed7fa765f5ed219195191f",
        "expected_trace_rows": 600,
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 1280,
            "lives": 2,
            "bombs": 3,
            "power": 0,
            "enemy_count": 29,
            "item_count": 0,
            "bullet_count": 15,
            "stage_vm": {"loaded": True, "script_time": 600, "instruction_index": 3},
            "ecl_timeline": {"time": 600, "next_time": 640},
            "terminal_reason": "tick-limit",
        },
    },
    {
        "name": "stage2-instruction-time-3",
        "stage": 2,
        "patch": "payload_stage2_instruction_time_3.json",
        "payload_sha256": "4b19b14fbe0ad7c0548b6119c5e2bacad83a4d0079688e91133322b183f14628",
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 367 baseline=860 case=90"},
            {"kind": "bullet-count-drift", "detail": "tick 375 baseline=28 case=0"},
            {"kind": "enemy-count-drift", "detail": "tick 409 baseline=8 case=12"},
        ],
        "expected_trace_sha256": "85979550a2cec6d247c897c3e3684c0d772b026891442ea39d84990677abae3b",
        "expected_trace_rows": 513,
        "expected_tail": {
            "tick": 513,
            "game_frame": 513,
            "score": 12170,
            "lives": 2,
            "bombs": 3,
            "power": 64,
            "enemy_count": 15,
            "item_count": 14,
            "bullet_count": 78,
            "stage_vm": {"loaded": True, "script_time": 513, "instruction_index": 3},
            "ecl_timeline": {"time": 513, "next_time": 516},
            "terminal_reason": "physical-hit",
        },
    },
    {
        "name": "stage3-instruction-time-3",
        "stage": 3,
        "patch": "payload_stage3_instruction_time_3.json",
        "payload_sha256": "7e36d22523f5324675a335ef7e14ca422853cf23cd2a0e2afa71ba02fccd5257",
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 442 baseline=1710 case=1130"},
            {"kind": "enemy-count-drift", "detail": "tick 460 baseline=2 case=5"},
        ],
        "expected_trace_sha256": "c6b274700dfccf85febb1e797801b769b58ce7f090a5904761ae61ff514cb63a",
        "expected_trace_rows": 600,
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 6860,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 13,
            "item_count": 4,
            "bullet_count": 8,
            "stage_vm": {"loaded": True, "script_time": 600, "instruction_index": 3},
            "ecl_timeline": {"time": 600, "next_time": 600},
            "terminal_reason": "tick-limit",
        },
    },
    {
        "name": "stage4-instruction-time-3",
        "stage": 4,
        "patch": "payload_stage4_instruction_time_3.json",
        "payload_sha256": "390e1b421c77d19b698464b82e1558cd5ebb8ca627afaad721d0bb23052c4318",
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 502 baseline=290 case=0"},
            {"kind": "enemy-count-drift", "detail": "tick 525 baseline=8 case=6"},
            {"kind": "bullet-count-drift", "detail": "tick 554 baseline=96 case=0"},
        ],
        "expected_trace_sha256": "2c8d0f0ee98c93168ae6365e36e21a64ff80605a79e0157b0de9318d02fcf6e7",
        "expected_trace_rows": 600,
        "expected_tail": {
            "tick": 600,
            "game_frame": 600,
            "score": 5430,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 4,
            "item_count": 2,
            "bullet_count": 0,
            "stage_vm": {"loaded": True, "script_time": 600, "instruction_index": 3},
            "ecl_timeline": {"time": 600, "next_time": 1004},
            "terminal_reason": "tick-limit",
        },
    },
    {
        "name": "stage5-instruction-time-3",
        "stage": 5,
        "patch": "payload_stage5_instruction_time_3.json",
        "payload_sha256": "0d5f78596abf3508d43e07437f321e513a05e77f655a89bb50d2001ce5bdfc08",
        "expected_findings": [
            {"kind": "score-drift", "detail": "tick 487 baseline=490 case=0"},
            {"kind": "bullet-count-drift", "detail": "tick 525 baseline=320 case=0"},
        ],
        "expected_trace_sha256": "f7116fa659f4fc5c2fe3b8dac2d2f86b478651dbdce702f730e74e3020617a89",
        "expected_trace_rows": 600,
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
            "stage_vm": {"loaded": True, "script_time": 600, "instruction_index": 3},
            "ecl_timeline": {"time": 600, "next_time": 690},
            "terminal_reason": "tick-limit",
        },
    },
)


def _seed_path(stage: int) -> Path:
    return REFERENCE_DIR / "corpus" / "ecl" / "original" / f"ecldata{stage}.ecl"


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


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    stage = int(rep["stage"])
    seed_path = _seed_path(stage)
    if not seed_path.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {seed_path}")
    canonical_seed_payload = serialize_ecl(parse_ecl(seed_path.read_bytes()))
    seed_ecl = parse_ecl(canonical_seed_payload)
    sub_index, instruction_index = TARGET_PATH
    instruction = seed_ecl.subs[sub_index].instructions[instruction_index]
    if instruction.opcode != TARGET_OPCODE:
        raise RuntimeError(
            f"stage {stage} target opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}"
        )
    if instruction.time != TARGET_ORIGINAL_TIME:
        raise RuntimeError(
            f"stage {stage} target time drifted: expected {TARGET_ORIGINAL_TIME}, got {instruction.time}"
        )

    patch_path = Path(__file__).with_name(str(rep["patch"]))
    if not patch_path.is_file():
        raise FileNotFoundError(f"missing payload patch: {patch_path}")
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
            "value": TARGET_MUTATED_TIME,
            "original_value": TARGET_ORIGINAL_TIME,
            "strategy": "exact-instruction-i32",
            "stage": stage,
        },
    )


def _selected_representatives(selected_stages: set[int] | None) -> tuple[dict[str, object], ...]:
    if not selected_stages:
        return REPRESENTATIVES
    return tuple(rep for rep in REPRESENTATIVES if int(rep["stage"]) in selected_stages)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the shared Stage 1-5 opening instruction-time route-skew finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stages1-5-opening-instruction-time-three-route-skew",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--no-reuse-worker-game-dir", action="store_true")
    parser.add_argument("--stage", type=int, action="append", choices=range(1, 6))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    negative_control_instruction = parse_ecl(serialize_ecl(parse_ecl(_seed_path(NEGATIVE_CONTROL_STAGE).read_bytes()))).subs[0].instructions[1]
    if negative_control_instruction.opcode != NEGATIVE_CONTROL_EXPECTED_OPCODE:
        raise RuntimeError(
            "stage 6 negative-control opcode drifted: "
            f"expected {NEGATIVE_CONTROL_EXPECTED_OPCODE}, got {negative_control_instruction.opcode}"
        )

    worker_game_dir = artifact_dir / "worker-game"
    worker_prepare = prepare_worker_game_dir(
        source_game_dir=args.game_dir.resolve(),
        destination=worker_game_dir,
        worker_name="stages1-5-opening-instruction-time-three-route-skew",
        reuse=not args.no_reuse_worker_game_dir,
    )

    selected = _selected_representatives(set(args.stage or []))
    if not selected:
        raise RuntimeError("no representatives selected")

    baseline_cache: dict[int, tuple[dict[str, object], list[dict[str, Any]]]] = {}
    baseline_summaries: dict[str, dict[str, Any]] = {}
    runs: list[dict[str, Any]] = []
    cases_dir = artifact_dir / "cases"
    ensure_directory(cases_dir)

    for case_index, rep in enumerate(selected, start=1):
        stage = int(rep["stage"])
        if stage not in baseline_cache:
            baseline_dir = artifact_dir / f"baseline-stage{stage}"
            baseline_metadata = run_baseline(
                binary=args.headless_bin.resolve(),
                game_dir=worker_game_dir.resolve(),
                resource_override_dir=None,
                stage=stage,
                seed=HEADLESS_SEED,
                action_file=DEFAULT_ACTION_FILE,
                artifact_dir=baseline_dir.resolve(),
                difficulty=3,
                character=0,
                shot_type=0,
                max_ticks=MAX_TICKS,
                auto_shoot=True,
                continue_after_hit=False,
                log_path=baseline_dir / "run.log",
                dry_run=False,
            )
            trace_value = baseline_metadata.get("trace")
            if not isinstance(trace_value, str):
                raise RuntimeError(f"stage {stage} baseline trace path missing")
            baseline_rows = _load_trace(Path(trace_value))
            baseline_tail = _tail_summary(baseline_rows)
            if baseline_tail != EXPECTED_BASELINE_TAILS[stage]:
                raise RuntimeError(
                    f"stage {stage} baseline tail drifted: expected {EXPECTED_BASELINE_TAILS[stage]}, got {baseline_tail}"
                )
            baseline_cache[stage] = (baseline_metadata, baseline_rows)
            baseline_summaries[str(stage)] = {
                "trace": trace_value,
                "tail": baseline_tail,
            }

        baseline_metadata, baseline_rows = baseline_cache[stage]
        trace_value = baseline_metadata.get("trace")
        if not isinstance(trace_value, str):
            raise RuntimeError(f"stage {stage} baseline trace path missing")

        mutant = _target_mutant(rep)
        result = run_case(
            binary=args.headless_bin.resolve(),
            game_dir=worker_game_dir.resolve(),
            stage=stage,
            seed=HEADLESS_SEED,
            action_file=DEFAULT_ACTION_FILE,
            difficulty=3,
            character=0,
            shot_type=0,
            max_ticks=MAX_TICKS,
            auto_shoot=True,
            continue_after_hit=False,
            timeout_seconds=TIMEOUT_SECONDS,
            campaign_dir=cases_dir.resolve(),
            seed_name=_seed_path(stage).name,
            mutant=mutant,
            case_index=case_index,
            baseline_trace=Path(trace_value),
            baseline_records=baseline_rows,
        )

        if result["returncode"] != 0:
            raise RuntimeError(f"{rep['name']} returncode drifted: expected 0, got {result['returncode']}")
        if result["timed_out"]:
            raise RuntimeError(f"{rep['name']} unexpectedly timed out")

        ordered_findings = _ordered_findings(result)
        expected_findings = list(rep["expected_findings"])
        if ordered_findings != expected_findings:
            raise RuntimeError(
                f"{rep['name']} findings drifted: expected {expected_findings}, got {ordered_findings}"
            )

        trace_path = Path(str(result["trace"]))
        rows = _load_trace(trace_path)
        if len(rows) != int(rep["expected_trace_rows"]):
            raise RuntimeError(
                f"{rep['name']} trace row count drifted: expected {rep['expected_trace_rows']}, got {len(rows)}"
            )
        trace_sha256 = _trace_sha256(trace_path)
        if trace_sha256 != str(rep["expected_trace_sha256"]):
            raise RuntimeError(
                f"{rep['name']} trace sha256 drifted: expected {rep['expected_trace_sha256']}, got {trace_sha256}"
            )
        tail = _tail_summary(rows)
        expected_tail = dict(rep["expected_tail"])
        if tail != expected_tail:
            raise RuntimeError(f"{rep['name']} tail drifted: expected {expected_tail}, got {tail}")

        runs.append(
            {
                "name": rep["name"],
                "stage": stage,
                "seed": str(_seed_path(stage)),
                "patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "payload_sha256": rep["payload_sha256"],
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "trace_rows": len(rows),
                "findings": ordered_findings,
                "tail": tail,
            }
        )

    summary = {
        "finding": "semantic/stages1-5-opening-instruction-time-three-route-skew",
        "target_path": {"sub_index": TARGET_PATH[0], "instruction_index": TARGET_PATH[1]},
        "target_opcode": TARGET_OPCODE,
        "target_original_time": TARGET_ORIGINAL_TIME,
        "target_mutated_time": TARGET_MUTATED_TIME,
        "negative_control_stage6_opcode": negative_control_instruction.opcode,
        "worker_prepare": worker_prepare,
        "baseline_summaries": baseline_summaries,
        "runs": runs,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
