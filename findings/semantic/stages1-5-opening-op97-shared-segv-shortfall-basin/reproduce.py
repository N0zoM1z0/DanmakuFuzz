from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from danmakufuzz.ecl_ir.model import RawInstruction
from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl
from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch, sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


TARGET_PATH = (0, 0)
TARGET_OPCODE = 97
TARGET_ORIGINAL_TIME = 0
TARGET_ORIGINAL_SKIP = 255
HEADLESS_SEED = 7
MAX_TICKS = 600
TIMEOUT_SECONDS = 5.0
NEGATIVE_CONTROL_STAGE = 6

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

EXPECTED_STAGE_OUTCOMES: dict[int, dict[str, Any]] = {
    1: {
        "findings": [
            {"kind": "process-signal", "detail": "SIGSEGV"},
            {"kind": "trace-shortfall", "detail": "tick_count=128 baseline_tick_count=311"},
        ],
        "returncode": -11,
        "trace_rows": 128,
        "trace_sha256": "f99d5e6907442befae0ab216de3b618520ada9301e83e4b8c8d444e790cd544f",
        "tail": {
            "tick": 128,
            "game_frame": 128,
            "score": 0,
            "lives": 2,
            "bombs": 3,
            "power": 0,
            "enemy_count": 0,
            "item_count": 0,
            "bullet_count": 0,
            "stage_vm": {"loaded": True, "script_time": 128, "instruction_index": 3},
            "ecl_timeline": {"time": 128, "next_time": 128},
            "terminal_reason": None,
        },
    },
    2: {
        "findings": [
            {"kind": "process-signal", "detail": "SIGSEGV"},
            {"kind": "trace-shortfall", "detail": "tick_count=330 baseline_tick_count=535"},
        ],
        "returncode": -11,
        "trace_rows": 330,
        "trace_sha256": "b210dca3f323e9a64fb370bfdbed09a99a4cca3d3c34c0c36864faff86eacca9",
        "tail": {
            "tick": 330,
            "game_frame": 330,
            "score": 0,
            "lives": 2,
            "bombs": 3,
            "power": 64,
            "enemy_count": 0,
            "item_count": 0,
            "bullet_count": 0,
            "stage_vm": {"loaded": True, "script_time": 330, "instruction_index": 3},
            "ecl_timeline": {"time": 330, "next_time": 330},
            "terminal_reason": None,
        },
    },
    3: {
        "findings": [
            {"kind": "process-signal", "detail": "SIGSEGV"},
            {"kind": "trace-shortfall", "detail": "tick_count=400 baseline_tick_count=600"},
        ],
        "returncode": -11,
        "trace_rows": 400,
        "trace_sha256": "7104c804159e5cbd0544a2a06fede5fcfa0e30c5e25171629407a68f4fb596ae",
        "tail": {
            "tick": 400,
            "game_frame": 400,
            "score": 0,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 0,
            "item_count": 0,
            "bullet_count": 0,
            "stage_vm": {"loaded": True, "script_time": 400, "instruction_index": 3},
            "ecl_timeline": {"time": 400, "next_time": 400},
            "terminal_reason": None,
        },
    },
    4: {
        "findings": [
            {"kind": "process-signal", "detail": "SIGSEGV"},
            {"kind": "trace-shortfall", "detail": "tick_count=440 baseline_tick_count=600"},
        ],
        "returncode": -11,
        "trace_rows": 440,
        "trace_sha256": "3de055d51bb31e444f3f163cb2085e0b3bec862ac04365c037de8be0d2bb308f",
        "tail": {
            "tick": 440,
            "game_frame": 440,
            "score": 0,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 0,
            "item_count": 0,
            "bullet_count": 0,
            "stage_vm": {"loaded": True, "script_time": 440, "instruction_index": 3},
            "ecl_timeline": {"time": 440, "next_time": 440},
            "terminal_reason": None,
        },
    },
    5: {
        "findings": [
            {"kind": "process-signal", "detail": "SIGSEGV"},
            {"kind": "trace-shortfall", "detail": "tick_count=440 baseline_tick_count=600"},
        ],
        "returncode": -11,
        "trace_rows": 440,
        "trace_sha256": "301951ec3664ad353b027a9b2fd39c48feeef7cef7b369df815b19c1a6d66ae7",
        "tail": {
            "tick": 440,
            "game_frame": 440,
            "score": 0,
            "lives": 2,
            "bombs": 3,
            "power": 128,
            "enemy_count": 0,
            "item_count": 0,
            "bullet_count": 0,
            "stage_vm": {"loaded": True, "script_time": 440, "instruction_index": 3},
            "ecl_timeline": {"time": 440, "next_time": 440},
            "terminal_reason": None,
        },
    },
}

POSITIVES = (
    {
        "name": "stage1-instruction-time-4096",
        "stage": 1,
        "patch": "payload_stage1_instruction_time_4096.json",
        "payload_sha256": "0bc0e1257fcc31998352eb59e466fe905318c7991e01a3506c3aa428ff9baf04",
        "updates": {"time": 4096},
        "family": "instruction-time",
    },
    {
        "name": "stage1-instruction-time-2147483602",
        "stage": 1,
        "patch": "payload_stage1_instruction_time_2147483602.json",
        "payload_sha256": "9b603cc674c9306b00c7bd86f890346f094800cbbb8e0695521e0729eba1d9e9",
        "updates": {"time": 2147483602},
        "family": "instruction-time",
    },
    {
        "name": "stage1-difficulty-mask-96",
        "stage": 1,
        "patch": "payload_stage1_difficulty_mask_96.json",
        "payload_sha256": "911b34a11468680f1667925075af5ecd04ddb2c7d5577bfa15ceeeb53e735621",
        "updates": {"skip_for_difficulty": 96},
        "family": "difficulty-mask",
    },
    {
        "name": "stage2-instruction-time-4096",
        "stage": 2,
        "patch": "payload_stage2_instruction_time_4096.json",
        "payload_sha256": "630e82060401335ccd9a9f71bcf59594705d54875d7e213cd2d7365a7e1b15a8",
        "updates": {"time": 4096},
        "family": "instruction-time",
    },
    {
        "name": "stage2-instruction-time-2147483602",
        "stage": 2,
        "patch": "payload_stage2_instruction_time_2147483602.json",
        "payload_sha256": "a29baf5b5f620962e856ad38a533f9d52c4614ab236d4023fe327e542c712c58",
        "updates": {"time": 2147483602},
        "family": "instruction-time",
    },
    {
        "name": "stage2-difficulty-mask-96",
        "stage": 2,
        "patch": "payload_stage2_difficulty_mask_96.json",
        "payload_sha256": "740e942c8b042cc2d7cd1aed7573db0a2496a87e274e15582993e9aef629efb3",
        "updates": {"skip_for_difficulty": 96},
        "family": "difficulty-mask",
    },
    {
        "name": "stage3-instruction-time-4096",
        "stage": 3,
        "patch": "payload_stage3_instruction_time_4096.json",
        "payload_sha256": "bf6b1fd60f4cb4c55408687249059be3f8950328060bed2c9c4a5fad128b8f35",
        "updates": {"time": 4096},
        "family": "instruction-time",
    },
    {
        "name": "stage3-instruction-time-2147483602",
        "stage": 3,
        "patch": "payload_stage3_instruction_time_2147483602.json",
        "payload_sha256": "ee3862cef536a709a53e075b87c06daa6879b03d5554cd4985c5ceec3a914d7d",
        "updates": {"time": 2147483602},
        "family": "instruction-time",
    },
    {
        "name": "stage3-difficulty-mask-96",
        "stage": 3,
        "patch": "payload_stage3_difficulty_mask_96.json",
        "payload_sha256": "7f5dad6dd221233b6aa3e6e4e2a2e90debf66cb39e4bcdce3723f1f1650dfcf5",
        "updates": {"skip_for_difficulty": 96},
        "family": "difficulty-mask",
    },
    {
        "name": "stage4-instruction-time-4096",
        "stage": 4,
        "patch": "payload_stage4_instruction_time_4096.json",
        "payload_sha256": "a9e031fda191167c42c0f9a7de190a40c88f0dcaeeb758097d6d40e3e3369195",
        "updates": {"time": 4096},
        "family": "instruction-time",
    },
    {
        "name": "stage4-instruction-time-2147483602",
        "stage": 4,
        "patch": "payload_stage4_instruction_time_2147483602.json",
        "payload_sha256": "183024cfc626a240421c97c4b11c449f4356f01627743ef70a91e53cbd712887",
        "updates": {"time": 2147483602},
        "family": "instruction-time",
    },
    {
        "name": "stage4-difficulty-mask-96",
        "stage": 4,
        "patch": "payload_stage4_difficulty_mask_96.json",
        "payload_sha256": "b73b50b67b279d1521fb30920344256ccf6f44e1be9db66ea469192b97c0844a",
        "updates": {"skip_for_difficulty": 96},
        "family": "difficulty-mask",
    },
    {
        "name": "stage5-instruction-time-4096",
        "stage": 5,
        "patch": "payload_stage5_instruction_time_4096.json",
        "payload_sha256": "436a85654d2110ebb7c3a00d652bedf3ca60df4fa74871702171b6f3d31838aa",
        "updates": {"time": 4096},
        "family": "instruction-time",
    },
    {
        "name": "stage5-instruction-time-2147483602",
        "stage": 5,
        "patch": "payload_stage5_instruction_time_2147483602.json",
        "payload_sha256": "96ce957cb99e1bf952bd55b2702ab2917247cfd970713ab026f329ec2d7a0209",
        "updates": {"time": 2147483602},
        "family": "instruction-time",
    },
    {
        "name": "stage5-difficulty-mask-96",
        "stage": 5,
        "patch": "payload_stage5_difficulty_mask_96.json",
        "payload_sha256": "aed738887ede86698de5ffe4e1bc62816fd6e0aca910e900aeda5cd333cb9f6e",
        "updates": {"skip_for_difficulty": 96},
        "family": "difficulty-mask",
    },
)

NEGATIVE_CONTROLS = (
    {"name": "stage6-instruction-time-4096", "updates": {"time": 4096}},
    {"name": "stage6-instruction-time-2147483602", "updates": {"time": 2147483602}},
    {"name": "stage6-difficulty-mask-96", "updates": {"skip_for_difficulty": 96}},
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


def _exact_payload(stage: int, updates: dict[str, int]) -> bytes:
    seed_path = _seed_path(stage)
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
    if instruction.skip_for_difficulty != TARGET_ORIGINAL_SKIP:
        raise RuntimeError(
            f"stage {stage} target difficulty mask drifted: expected {TARGET_ORIGINAL_SKIP}, got {instruction.skip_for_difficulty}"
        )
    mutated = RawInstruction(**{**instruction.__dict__, **updates})
    seed_ecl.subs[sub_index].instructions[instruction_index] = mutated
    return serialize_ecl(seed_ecl)


def _payload_mutant_from_patch(rep: dict[str, object]) -> PayloadMutant:
    stage = int(rep["stage"])
    canonical_seed_payload = serialize_ecl(parse_ecl(_seed_path(stage).read_bytes()))
    expected_payload = _exact_payload(stage, dict(rep["updates"]))
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
    if payload != expected_payload:
        raise RuntimeError(f"{rep['name']} payload patch no longer matches the exact mutation target")
    return PayloadMutant(
        name=str(rep["name"]),
        payload=payload,
        source="ir-exact",
        path=TARGET_PATH,
        metadata={
            "family": str(rep["family"]),
            "updates": json.dumps(rep["updates"], sort_keys=True),
            "strategy": "exact-patch",
            "stage": stage,
        },
    )


def _payload_mutant_exact(stage: int, name: str, updates: dict[str, int], *, family: str) -> PayloadMutant:
    payload = _exact_payload(stage, updates)
    return PayloadMutant(
        name=name,
        payload=payload,
        source="ir-exact",
        path=TARGET_PATH,
        metadata={
            "family": family,
            "updates": json.dumps(updates, sort_keys=True),
            "strategy": "exact-direct",
            "stage": stage,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the shared Stage 1-5 opening opcode97 SIGSEGV shortfall basin."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stages1-5-opening-op97-shared-segv-shortfall-basin",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--no-reuse-worker-game-dir", action="store_true")
    parser.add_argument("--stage", type=int, action="append", choices=range(1, 6))
    parser.add_argument("--no-stage6-negative-controls", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    selected_stages = set(args.stage or [])
    positives = tuple(rep for rep in POSITIVES if not selected_stages or int(rep["stage"]) in selected_stages)
    if not positives:
        raise RuntimeError("no positive representatives selected")

    worker_game_dir = artifact_dir / "worker-game"
    worker_prepare = prepare_worker_game_dir(
        source_game_dir=args.game_dir.resolve(),
        destination=worker_game_dir,
        worker_name="stages1-5-opening-op97-shared-segv-shortfall-basin",
        reuse=not args.no_reuse_worker_game_dir,
    )

    baseline_cache: dict[int, tuple[dict[str, object], list[dict[str, Any]]]] = {}
    baseline_summaries: dict[str, dict[str, Any]] = {}
    positive_runs: list[dict[str, Any]] = []
    negative_runs: list[dict[str, Any]] = []
    cases_dir = artifact_dir / "cases"
    ensure_directory(cases_dir)

    def baseline_for_stage(stage: int) -> tuple[dict[str, object], list[dict[str, Any]]]:
        cached = baseline_cache.get(stage)
        if cached is not None:
            return cached
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
        expected_baseline_tail = EXPECTED_BASELINE_TAILS.get(stage)
        if expected_baseline_tail is not None and baseline_tail != expected_baseline_tail:
            raise RuntimeError(
                f"stage {stage} baseline tail drifted: expected {expected_baseline_tail}, got {baseline_tail}"
            )
        baseline_cache[stage] = (baseline_metadata, baseline_rows)
        baseline_summaries[str(stage)] = {
            "trace": trace_value,
            "tail": baseline_tail,
        }
        return baseline_metadata, baseline_rows

    case_index = 1
    for rep in positives:
        stage = int(rep["stage"])
        baseline_metadata, baseline_rows = baseline_for_stage(stage)
        trace_value = baseline_metadata.get("trace")
        if not isinstance(trace_value, str):
            raise RuntimeError(f"stage {stage} baseline trace path missing")
        mutant = _payload_mutant_from_patch(rep)
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
        case_index += 1

        expected = EXPECTED_STAGE_OUTCOMES[stage]
        if result["returncode"] != expected["returncode"]:
            raise RuntimeError(
                f"{rep['name']} returncode drifted: expected {expected['returncode']}, got {result['returncode']}"
            )
        ordered_findings = _ordered_findings(result)
        if ordered_findings != list(expected["findings"]):
            raise RuntimeError(
                f"{rep['name']} findings drifted: expected {expected['findings']}, got {ordered_findings}"
            )
        trace_path = Path(str(result["trace"]))
        rows = _load_trace(trace_path)
        if len(rows) != int(expected["trace_rows"]):
            raise RuntimeError(
                f"{rep['name']} trace row count drifted: expected {expected['trace_rows']}, got {len(rows)}"
            )
        trace_sha256 = _trace_sha256(trace_path)
        if trace_sha256 != str(expected["trace_sha256"]):
            raise RuntimeError(
                f"{rep['name']} trace sha256 drifted: expected {expected['trace_sha256']}, got {trace_sha256}"
            )
        tail = _tail_summary(rows)
        if tail != dict(expected["tail"]):
            raise RuntimeError(f"{rep['name']} tail drifted: expected {expected['tail']}, got {tail}")

        positive_runs.append(
            {
                "name": rep["name"],
                "stage": stage,
                "patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "payload_sha256": rep["payload_sha256"],
                "updates": rep["updates"],
                "trace": str(trace_path.resolve()),
                "trace_sha256": trace_sha256,
                "trace_rows": len(rows),
                "findings": ordered_findings,
                "tail": tail,
            }
        )

    if not args.no_stage6_negative_controls:
        stage = NEGATIVE_CONTROL_STAGE
        baseline_metadata, baseline_rows = baseline_for_stage(stage)
        trace_value = baseline_metadata.get("trace")
        if not isinstance(trace_value, str):
            raise RuntimeError("stage 6 baseline trace path missing")
        for rep in NEGATIVE_CONTROLS:
            mutant = _payload_mutant_exact(
                stage,
                str(rep["name"]),
                dict(rep["updates"]),
                family="negative-control",
            )
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
            case_index += 1
            ordered_findings = _ordered_findings(result)
            if result["returncode"] != 0:
                raise RuntimeError(f"{rep['name']} negative control drifted: expected returncode 0, got {result['returncode']}")
            if ordered_findings:
                raise RuntimeError(f"{rep['name']} negative control unexpectedly became interesting: {ordered_findings}")
            negative_runs.append(
                {
                    "name": rep["name"],
                    "stage": stage,
                    "updates": rep["updates"],
                    "trace": result["trace"],
                    "returncode": result["returncode"],
                    "findings": ordered_findings,
                }
            )

    summary = {
        "finding": "semantic/stages1-5-opening-op97-shared-segv-shortfall-basin",
        "target_path": {"sub_index": TARGET_PATH[0], "instruction_index": TARGET_PATH[1]},
        "target_opcode": TARGET_OPCODE,
        "target_original_time": TARGET_ORIGINAL_TIME,
        "target_original_skip_for_difficulty": TARGET_ORIGINAL_SKIP,
        "worker_prepare": worker_prepare,
        "baseline_summaries": baseline_summaries,
        "positive_runs": positive_runs,
        "negative_controls": negative_runs,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
