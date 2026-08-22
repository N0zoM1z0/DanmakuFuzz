from __future__ import annotations

import argparse
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
from danmakufuzz.semantic.trace_basins import _first_divergence, _load_normalized_trace, _signature, _sink_snapshot


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
TARGET_OPCODE = 75
TARGET_PATH = (3, 3)
TARGET_ORIGINAL_BULLET_COUNT1 = 9
TARGET_ORIGINAL_BULLET_COUNT2 = 1
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
EXPECTED_FIRST_DIVERGENCE_TICK = 460
EXPECTED_FIRST_DIVERGENCE_KEYS = ["bullet_count"]
EXPECTED_DIVERGENCE_CONTEXT = {
    "score": 60,
    "enemy_count": 3,
    "item_count": 0,
    "next_time": 464,
}
EXPECTED_BASINS = {
    "shared-high-640": {
        "signature": "19af3cb0b64dd1376faec04690f430ba78c0a6cf706501970fb22b2687a280d9",
        "sink_bullet_count": 640,
        "members": [
            "bullet-count-cross-5-2049",
            "bullet-count-cross-10715-29",
        ],
    },
    "shoulder-156": {
        "signature": "a5ead1803c58a88761749433a8a6e24ffdb5725f539890da77ea7ac9c8c8efba",
        "sink_bullet_count": 156,
        "members": [
            "bullet-count-cross-36-4",
        ],
    },
    "shoulder-77": {
        "signature": "a92a1f4c89a935ae285d69476803dd02d45e1cc00ee16b7f501aec5662d7d24b",
        "sink_bullet_count": 77,
        "members": [
            "bullet-count-cross-13-5",
        ],
    },
    "shoulder-48": {
        "signature": "f41cedb0f7a323f866b72ee5841d1df41c79ed70f879fcda2fc4df8b1edb165b",
        "sink_bullet_count": 48,
        "members": [
            "bullet-count-cross-18-2",
        ],
    },
    "shoulder-13": {
        "signature": "b3dc4789334e3be30fba84c1b793f3c1b6b6b274ec59c9d6c6f7e0223e5152bb",
        "sink_bullet_count": 13,
        "members": [
            "bullet-count-cross-1-0",
        ],
    },
}
REPRESENTATIVES = (
    {
        "name": "bullet-count-cross-1-0",
        "left_value": 1,
        "right_value": 0,
        "patch": "payload_bullet_count_cross_1_0.json",
        "payload_sha256": "f20c5624c12ec2b6ecabf04a3e58368d7cba968d92a138fef9a6c5f1fc6ecdb9",
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 475 baseline=39 case=13"},
        ],
        "expected_sink_signature": EXPECTED_BASINS["shoulder-13"]["signature"],
    },
    {
        "name": "bullet-count-cross-5-2049",
        "left_value": 5,
        "right_value": 2049,
        "patch": "payload_bullet_count_cross_5_2049.json",
        "payload_sha256": "1eddf0c3ca22a6bd780296c820a988ae94e77850e7c2003dc9737b12e9058329",
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 475 baseline=39 case=299"},
        ],
        "expected_sink_signature": EXPECTED_BASINS["shared-high-640"]["signature"],
    },
    {
        "name": "bullet-count-cross-13-5",
        "left_value": 13,
        "right_value": 5,
        "patch": "payload_bullet_count_cross_13_5.json",
        "payload_sha256": "dfb9e1d6fee40d566ab4c8cbc0b78e89eb76c49d46b4cb6f8ba4ca56853f92a3",
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 490 baseline=48 case=131"},
        ],
        "expected_sink_signature": EXPECTED_BASINS["shoulder-77"]["signature"],
    },
    {
        "name": "bullet-count-cross-10715-29",
        "left_value": 10715,
        "right_value": 29,
        "patch": "payload_bullet_count_cross_10715_29.json",
        "payload_sha256": "64db73cde4f730ab8ef5551f344b2423eb7d2b0d689e58a7bdf53c4331cad2ba",
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 475 baseline=39 case=299"},
        ],
        "expected_sink_signature": EXPECTED_BASINS["shared-high-640"]["signature"],
    },
    {
        "name": "bullet-count-cross-18-2",
        "left_value": 18,
        "right_value": 2,
        "patch": "payload_bullet_count_cross_18_2.json",
        "payload_sha256": "392112020c5f6a97991e4e589c06928ed8eb4ae41549124072768eb325312765",
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 503 baseline=60 case=133"},
        ],
        "expected_sink_signature": EXPECTED_BASINS["shoulder-48"]["signature"],
    },
    {
        "name": "bullet-count-cross-36-4",
        "left_value": 36,
        "right_value": 4,
        "patch": "payload_bullet_count_cross_36_4.json",
        "payload_sha256": "095befdcfd49fc7c768b83639a4dce4cfc20a25bde667c91824482519cb53d62",
        "expected_findings": [
            {"kind": "bullet-count-drift", "detail": "tick 490 baseline=48 case=257"},
        ],
        "expected_sink_signature": EXPECTED_BASINS["shoulder-156"]["signature"],
    },
)
RETAIL_REPRESENTATIVE_NAME = "bullet-count-cross-18-2"


def _basin_name_from_signature(signature: str) -> str:
    for basin_name, basin in EXPECTED_BASINS.items():
        if basin["signature"] == signature:
            return basin_name
    raise RuntimeError(f"unexpected sink signature: {signature}")


def _target_mutant(rep: dict[str, object]) -> PayloadMutant:
    seed_payload = TARGET_SEED.read_bytes()
    ecl = parse_ecl(seed_payload)
    sub_index, instruction_index = TARGET_PATH
    instruction = ecl.subs[sub_index].instructions[instruction_index]
    if instruction.opcode != TARGET_OPCODE:
        raise RuntimeError(f"target opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}")
    bullet_count1 = int.from_bytes(instruction.args[4:8], "little", signed=True)
    bullet_count2 = int.from_bytes(instruction.args[8:12], "little", signed=True)
    if bullet_count1 != TARGET_ORIGINAL_BULLET_COUNT1 or bullet_count2 != TARGET_ORIGINAL_BULLET_COUNT2:
        raise RuntimeError(
            "target bullet-count pair drifted: "
            f"expected ({TARGET_ORIGINAL_BULLET_COUNT1}, {TARGET_ORIGINAL_BULLET_COUNT2}), "
            f"got ({bullet_count1}, {bullet_count2})"
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
            "family": "bullet-count-cross",
            "field_left": "count",
            "field_right": "count",
            "left_value": int(rep["left_value"]),
            "right_value": int(rep["right_value"]),
            "original_left_value": TARGET_ORIGINAL_BULLET_COUNT1,
            "original_right_value": TARGET_ORIGINAL_BULLET_COUNT2,
            "strategy": "exact-i32-pair",
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
        description="Reproduce the Stage 6 bullet-count cross-field five-basin early-volley split."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-bullet-count-cross-five-basin-early-volley-split",
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
        worker_name="stage6-bullet-count-cross-five-basin-early-volley-split",
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

    normalized_baseline = _load_normalized_trace(baseline_trace, pos_round=4)
    headless_cases: list[dict[str, object]] = []
    actual_members_by_signature: dict[str, list[str]] = {}
    sink_snapshots: dict[str, dict[str, Any]] = {}
    retail_result_path: Path | None = None
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

        trace_path = Path(str(result["trace"]))
        payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
        result_path = artifact_dir / str(result["case_name"]) / "result.json"
        ordered_findings = _ordered_findings(result)
        if ordered_findings != list(rep["expected_findings"]):
            raise RuntimeError(
                f"{rep['name']} findings drifted: expected {rep['expected_findings']}, got {ordered_findings}"
            )

        normalized_case = _load_normalized_trace(trace_path, pos_round=4)
        divergence_record, divergence_keys = _first_divergence(normalized_baseline, normalized_case)
        if divergence_record is None or divergence_keys is None:
            raise RuntimeError(f"{rep['name']} no longer diverges from the baseline")
        divergence_tick = int(divergence_record["tick"])
        if divergence_tick != EXPECTED_FIRST_DIVERGENCE_TICK:
            raise RuntimeError(
                f"{rep['name']} first divergence tick drifted: "
                f"expected {EXPECTED_FIRST_DIVERGENCE_TICK}, got {divergence_tick}"
            )
        if divergence_keys != EXPECTED_FIRST_DIVERGENCE_KEYS:
            raise RuntimeError(
                f"{rep['name']} first divergence keys drifted: "
                f"expected {EXPECTED_FIRST_DIVERGENCE_KEYS}, got {divergence_keys}"
            )

        sink_snapshot = _sink_snapshot(divergence_record)
        sink_signature = _signature(sink_snapshot)
        expected_sink_signature = str(rep["expected_sink_signature"])
        if sink_signature != expected_sink_signature:
            raise RuntimeError(
                f"{rep['name']} sink signature drifted: expected {expected_sink_signature}, got {sink_signature}"
            )
        basin_name = _basin_name_from_signature(sink_signature)
        basin = EXPECTED_BASINS[basin_name]
        sink_bullet_count = int(sink_snapshot["bullet_count"])
        if sink_bullet_count != int(basin["sink_bullet_count"]):
            raise RuntimeError(
                f"{rep['name']} sink bullet count drifted: "
                f"expected {basin['sink_bullet_count']}, got {sink_bullet_count}"
            )
        if int(sink_snapshot["score"]) != EXPECTED_DIVERGENCE_CONTEXT["score"]:
            raise RuntimeError(
                f"{rep['name']} sink score drifted: "
                f"expected {EXPECTED_DIVERGENCE_CONTEXT['score']}, got {sink_snapshot['score']}"
            )
        if int(sink_snapshot["enemy_count"]) != EXPECTED_DIVERGENCE_CONTEXT["enemy_count"]:
            raise RuntimeError(
                f"{rep['name']} sink enemy count drifted: "
                f"expected {EXPECTED_DIVERGENCE_CONTEXT['enemy_count']}, got {sink_snapshot['enemy_count']}"
            )
        if int(sink_snapshot["item_count"]) != EXPECTED_DIVERGENCE_CONTEXT["item_count"]:
            raise RuntimeError(
                f"{rep['name']} sink item count drifted: "
                f"expected {EXPECTED_DIVERGENCE_CONTEXT['item_count']}, got {sink_snapshot['item_count']}"
            )
        sink_next_time = sink_snapshot.get("ecl_timeline", {}).get("next_time")
        if int(sink_next_time) != EXPECTED_DIVERGENCE_CONTEXT["next_time"]:
            raise RuntimeError(
                f"{rep['name']} sink next_time drifted: "
                f"expected {EXPECTED_DIVERGENCE_CONTEXT['next_time']}, got {sink_next_time}"
            )

        case_rows = _load_trace(trace_path)
        case_tail = _tail_summary(case_rows)
        headless_cases.append(
            {
                "name": rep["name"],
                "left_value": rep["left_value"],
                "right_value": rep["right_value"],
                "payload_patch": str(Path(__file__).with_name(str(rep["patch"])).resolve()),
                "payload_path": str(payload_path.resolve()),
                "payload_sha256": rep["payload_sha256"],
                "result": str(result_path.resolve()),
                "trace": str(trace_path.resolve()),
                "findings": ordered_findings,
                "first_divergence": {
                    "tick": divergence_tick,
                    "keys": divergence_keys,
                },
                "sink_signature": sink_signature,
                "sink_basin": basin_name,
                "sink_snapshot": sink_snapshot,
                "tail": case_tail,
                "command": result["command"],
            }
        )
        actual_members_by_signature.setdefault(sink_signature, []).append(str(rep["name"]))
        sink_snapshots.setdefault(sink_signature, sink_snapshot)
        if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
            retail_result_path = result_path.resolve()

    expected_members_by_signature = {
        str(basin["signature"]): sorted(str(member) for member in basin["members"])
        for basin in EXPECTED_BASINS.values()
    }
    normalized_actual_members = {
        signature: sorted(members)
        for signature, members in actual_members_by_signature.items()
    }
    if normalized_actual_members != expected_members_by_signature:
        raise RuntimeError(
            "basin membership drifted: "
            f"expected {expected_members_by_signature}, got {normalized_actual_members}"
        )
    if len(normalized_actual_members) != len(EXPECTED_BASINS):
        raise RuntimeError(
            f"expected {len(EXPECTED_BASINS)} basins, got {len(normalized_actual_members)}"
        )

    basins: list[dict[str, object]] = []
    for basin_name, basin in EXPECTED_BASINS.items():
        signature = str(basin["signature"])
        basins.append(
            {
                "name": basin_name,
                "signature": signature,
                "members": normalized_actual_members[signature],
                "sink_bullet_count": basin["sink_bullet_count"],
                "sink_snapshot": sink_snapshots[signature],
                "first_divergence": {
                    "tick": EXPECTED_FIRST_DIVERGENCE_TICK,
                    "keys": EXPECTED_FIRST_DIVERGENCE_KEYS,
                },
            }
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage6-bullet-count-cross-five-basin-early-volley-split",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_site": {
            "path": {
                "sub_index": TARGET_PATH[0],
                "instruction_index": TARGET_PATH[1],
            },
            "opcode": TARGET_OPCODE,
            "original_pair": {
                "bullet_count1": TARGET_ORIGINAL_BULLET_COUNT1,
                "bullet_count2": TARGET_ORIGINAL_BULLET_COUNT2,
            },
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "tail": baseline_tail,
            "worker_game_dir": str(worker_game_dir.resolve()),
            "worker_game_prepare": worker_prepare,
            "command": baseline_metadata["command"],
        },
        "headless_cases": headless_cases,
        "basins": basins,
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
