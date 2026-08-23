from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from danmakufuzz.ecl_ir.model import EclFile, EclSubroutine, RawInstruction
from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl
from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch, sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import run_case
from danmakufuzz.semantic.payload_mutants import PayloadMutant


TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
TARGET_STAGE = 6
TARGET_OPCODE = 77
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
        "instruction_index": 3,
        "loaded": True,
        "script_time": 600,
    },
    "ecl_timeline": {
        "time": 600,
        "next_time": 600,
    },
    "terminal_reason": "tick-limit",
}
SITES = (
    {
        "slug": "s01-i0008",
        "path": (1, 8),
        "sampled_alias": -115,
        "cases": (
            {
                "name": "s01-i0008-neg1",
                "value": -1,
                "patch": "payload_s01_i0008_neg1.json",
                "payload_sha256": "77a2f53437a327ba24877494fd754ea4bd13485a2ba8b87b230edd07713f012c",
                "trace_sha256": "31b6ada04316b5a95ff41b5c53c3bfbed1674ec71d4e939e8863743b873d346e",
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
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
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
            },
            {
                "name": "s01-i0008-0",
                "value": 0,
                "patch": None,
                "payload_sha256": "3f18c9b4189ff5a861c03781e1cbd4c245000275fd03f428414b205578798414",
                "trace_sha256": "46924d1231205279f2e116018622ae244d69ac07b3f2a96ed5d158d53b57fee1",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 153,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [],
            },
            {
                "name": "s01-i0008-1",
                "value": 1,
                "patch": "payload_s01_i0008_1.json",
                "payload_sha256": "46aabdf6ca092c2e0fa9270d0be7c29487c128831ffadef57160cec645518020",
                "trace_sha256": "a04d8992ece329f1fe77acc7b28689ac8128239781b513045174ec6b951e60d4",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 639,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [
                    {"kind": "bullet-count-drift", "detail": "tick 456 baseline=0 case=180"},
                ],
            },
        ),
    },
    {
        "slug": "s02-i0008",
        "path": (2, 8),
        "sampled_alias": 28494,
        "cases": (
            {
                "name": "s02-i0008-neg1",
                "value": -1,
                "patch": "payload_s02_i0008_neg1.json",
                "payload_sha256": "6b94febee109ef87256f3c9cd51d6028affbeb607572c63665216206183ac1eb",
                "trace_sha256": "2d5cf9b25f6a4c1be937b97e69ef1df5829636c9a53fb38d52718361e46491f7",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 124,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [
                    {"kind": "bullet-count-drift", "detail": "tick 484 baseline=48 case=16"},
                ],
            },
            {
                "name": "s02-i0008-0",
                "value": 0,
                "patch": None,
                "payload_sha256": "582db46f318fa98975077bea552786309fffb96ed143adfff2d97e54899b3a41",
                "trace_sha256": "b478cd41d29f33a9bc2dcb98bc53a689e621b3c83f49eaf7913cf07633892ccb",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 145,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [],
            },
            {
                "name": "s02-i0008-1",
                "value": 1,
                "patch": "payload_s02_i0008_1.json",
                "payload_sha256": "717fd20e0f4b9a96cf2f83d7aeb3d5875f23cf80ceb273f6c25b2c7f9d3894ff",
                "trace_sha256": "37f269afda9d5879b1f85d76fd573d4be13af1399dc23380d353590dd5fe80bb",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 635,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [
                    {"kind": "bullet-count-drift", "detail": "tick 472 baseline=30 case=210"},
                ],
            },
        ),
    },
    {
        "slug": "s03-i0008",
        "path": (3, 8),
        "sampled_alias": 94,
        "cases": (
            {
                "name": "s03-i0008-neg1",
                "value": -1,
                "patch": "payload_s03_i0008_neg1.json",
                "payload_sha256": "d90f79312938eff8c757f7de140fb776e405a08f12d5802369acab4b5afa3ee1",
                "trace_sha256": "c1baf94f56387348f5d56ddeb10a719349c08b7aa66f6be3810314fc4b69c4e4",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 143,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [
                    {"kind": "bullet-count-drift", "detail": "tick 475 baseline=39 case=12"},
                ],
            },
            {
                "name": "s03-i0008-0",
                "value": 0,
                "patch": None,
                "payload_sha256": "305b6b8f0fde7ea5129c4a76431d6c3fe0359b362b42cc764458dd2fcc92262b",
                "trace_sha256": "fbceb10bc8ade1358bdbc35617c0ec49b0cdae766e68253ee9104844d73d721b",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 170,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [],
            },
            {
                "name": "s03-i0008-1",
                "value": 1,
                "patch": "payload_s03_i0008_1.json",
                "payload_sha256": "198948130ffb6ec301e5665b107a5eef2f153190cc350ad6b76147dbd7629b92",
                "trace_sha256": "2ae308522f860fb1eee4e75336126319f041cb2f0e521e7d4ba9fa7f057168b2",
                "expected_tail": {
                    "tick": 600,
                    "game_frame": 600,
                    "score": 16270,
                    "lives": 2,
                    "bombs": 3,
                    "power": 128,
                    "enemy_count": 6,
                    "item_count": 14,
                    "bullet_count": 632,
                    "stage_vm": {
                        "instruction_index": 3,
                        "loaded": True,
                        "script_time": 600,
                    },
                    "ecl_timeline": {
                        "time": 600,
                        "next_time": 600,
                    },
                    "terminal_reason": "tick-limit",
                },
                "expected_findings": [
                    {"kind": "bullet-count-drift", "detail": "tick 464 baseline=33 case=147"},
                ],
            },
        ),
    },
)
RETAIL_REPRESENTATIVE_NAME = "s02-i0008-neg1"


def _load_seed_ecl() -> EclFile:
    if not TARGET_SEED.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {TARGET_SEED}")
    return parse_ecl(TARGET_SEED.read_bytes())


def _validate_target_sites(ecl: EclFile) -> None:
    for site in SITES:
        sub_index, instruction_index = tuple(site["path"])
        instruction = ecl.subs[int(sub_index)].instructions[int(instruction_index)]
        if instruction.opcode != TARGET_OPCODE:
            raise RuntimeError(
                f"{site['slug']} opcode drifted: expected {TARGET_OPCODE}, got {instruction.opcode}"
            )
        original_value = int.from_bytes(instruction.args[:4], "little", signed=True)
        if original_value != TARGET_ORIGINAL_VALUE:
            raise RuntimeError(
                f"{site['slug']} original shoot-interval drifted: "
                f"expected {TARGET_ORIGINAL_VALUE}, got {original_value}"
            )


def _exact_payload(seed_ecl: EclFile, *, sub_index: int, instruction_index: int, value: int) -> bytes:
    subs = list(seed_ecl.subs)
    sub = subs[sub_index]
    instructions = list(sub.instructions)
    instruction = instructions[instruction_index]
    args = bytearray(instruction.args)
    args[0:4] = int(value).to_bytes(4, "little", signed=True)
    instructions[instruction_index] = RawInstruction(**{**instruction.__dict__, "args": bytes(args)})
    subs[sub_index] = EclSubroutine(file_offset=sub.file_offset, instructions=instructions)
    mutated = EclFile(
        sub_count=seed_ecl.sub_count,
        main_count=seed_ecl.main_count,
        timeline_offsets=seed_ecl.timeline_offsets,
        timeline=seed_ecl.timeline,
        subs=subs,
    )
    return serialize_ecl(mutated)


def _build_mutant(
    seed_ecl: EclFile,
    *,
    site: dict[str, object],
    rep: dict[str, object],
) -> PayloadMutant:
    canonical_seed_payload = serialize_ecl(seed_ecl)
    sub_index, instruction_index = tuple(site["path"])
    if rep["patch"] is None:
        payload = _exact_payload(
            seed_ecl,
            sub_index=int(sub_index),
            instruction_index=int(instruction_index),
            value=int(rep["value"]),
        )
    else:
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
        path=(int(sub_index), int(instruction_index)),
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
    last = rows[-1]
    stage_vm = last.get("stage_vm")
    ecl_timeline = last.get("ecl_timeline")
    return {
        "tick": last.get("tick"),
        "game_frame": last.get("game_frame"),
        "score": last.get("score"),
        "lives": last.get("lives"),
        "bombs": last.get("bombs"),
        "power": last.get("power"),
        "enemy_count": last.get("enemy_count"),
        "item_count": len(last.get("items", [])),
        "bullet_count": len(last.get("bullets", [])),
        "stage_vm": {
            "instruction_index": stage_vm.get("instruction_index") if isinstance(stage_vm, dict) else None,
            "loaded": stage_vm.get("loaded") if isinstance(stage_vm, dict) else None,
            "script_time": stage_vm.get("script_time") if isinstance(stage_vm, dict) else None,
        },
        "ecl_timeline": {
            "time": ecl_timeline.get("time") if isinstance(ecl_timeline, dict) else None,
            "next_time": ecl_timeline.get("next_time") if isinstance(ecl_timeline, dict) else None,
        },
        "terminal_reason": last.get("terminal_reason"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 shoot-interval three-site sign basin cluster."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-shoot-interval-three-site-sign-basin-cluster",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--retail", action="store_true")
    parser.add_argument("--retail-timeout-seconds", type=float, default=35.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_ecl = _load_seed_ecl()
    _validate_target_sites(seed_ecl)

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=TARGET_STAGE,
        seed=7,
        action_file=DEFAULT_ACTION_FILE,
        artifact_dir=baseline_dir,
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
    case_index = 0
    for site in SITES:
        site_cases: list[dict[str, object]] = []
        for rep in site["cases"]:
            case_index += 1
            mutant = _build_mutant(seed_ecl, site=site, rep=rep)
            result = run_case(
                binary=args.headless_bin.resolve(),
                game_dir=args.game_dir.resolve(),
                stage=TARGET_STAGE,
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
            expected_findings = list(rep["expected_findings"])
            if result["findings"] != expected_findings:
                raise RuntimeError(
                    f"{rep['name']} findings drifted: expected {expected_findings}, got {result['findings']}"
                )
            result_path = artifact_dir / result["case_name"] / "result.json"
            payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
            trace_path = Path(str(result["trace"]))
            trace_sha256 = _trace_sha256(trace_path)
            if trace_sha256 != str(rep["trace_sha256"]):
                raise RuntimeError(
                    f"{rep['name']} trace drifted: expected {rep['trace_sha256']}, got {trace_sha256}"
                )
            case_rows = _load_trace(trace_path)
            case_tail = _tail_summary(case_rows)
            expected_tail = dict(rep["expected_tail"])
            if case_tail != expected_tail:
                raise RuntimeError(
                    f"{rep['name']} tail drifted: expected {expected_tail}, got {case_tail}"
                )
            if str(rep["name"]) == RETAIL_REPRESENTATIVE_NAME:
                retail_result_path = result_path.resolve()
            site_cases.append(
                {
                    "name": rep["name"],
                    "value": rep["value"],
                    "payload_sha256": rep["payload_sha256"],
                    "payload_patch": (
                        str(Path(__file__).with_name(str(rep["patch"])).resolve())
                        if rep["patch"] is not None
                        else None
                    ),
                    "result": str(result_path.resolve()),
                    "payload_path": str(payload_path.resolve()),
                    "trace": str(trace_path.resolve()),
                    "trace_sha256": trace_sha256,
                    "findings": result["findings"],
                    "tail": case_tail,
                    "command": result["command"],
                }
            )
        headless_cases.append(
            {
                "slug": site["slug"],
                "path": {
                    "sub_index": site["path"][0],
                    "instruction_index": site["path"][1],
                },
                "opcode": TARGET_OPCODE,
                "original_value": TARGET_ORIGINAL_VALUE,
                "sampled_alias": site["sampled_alias"],
                "cases": site_cases,
            }
        )

    summary: dict[str, object] = {
        "finding": "semantic/stage6-shoot-interval-three-site-sign-basin-cluster",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "command": baseline_metadata["command"],
            "tail": baseline_tail,
        },
        "headless": {
            "sites": headless_cases,
        },
        "source_artifacts": {
            "smoke_campaign": str((ARTIFACTS_DIR / "_smoke" / "20260823-stage6-shoot-interval-new-sampler" / "campaign.json").resolve()),
            "hotspots": str((ARTIFACTS_DIR / "semantic-hotspots" / "20260823T010443Z" / "summary.json").resolve()),
            "basin_harvest": str((ARTIFACTS_DIR / "_smoke" / "20260823-stage6-shoot-interval-new-sampler-basin" / "summary.json").resolve()),
        },
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
            str(TARGET_STAGE),
            "--difficulty",
            "3",
            "--timeout-seconds",
            str(args.retail_timeout_seconds),
        ]
        subprocess.run(command, check=True)
        report_path = retail_dir / "report.json"
        summary["retail"] = {
            "representative": RETAIL_REPRESENTATIVE_NAME,
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
