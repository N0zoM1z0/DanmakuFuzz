from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from danmakufuzz.corpus.pbg3 import Pbg3Archive
from danmakufuzz.headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    build_command,
    default_headless_binary,
    run_baseline,
)
from danmakufuzz.headless.overrides import materialize_override_bundle, stage_active_override_bundle
from danmakufuzz.interestingness.rules import load_trace_records, score_trace_path_with_baseline
from danmakufuzz.parser.anm import DEFAULT_ARCHIVE, parse_anm
from danmakufuzz.parser.anm_campaign import evaluate_anm_payload
from danmakufuzz.parser.anm_mutants import generate_anm_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import classify_process_result


FINDING_NAME = "runtime/anm-stage7-triad-runtime-sigsegv-basin"
TARGET_STAGE = 7
TARGET_SEED = 7
TARGET_DIFFICULTY = 3
TARGET_CHARACTER = 0
TARGET_SHOT_TYPE = 0
TARGET_MAX_TICKS = 600
EXPECTED_BASELINE_TRACE_SHA256 = "0125465c062ff68652e01c68d5acfd33772bb8e34492df12e9ea0884f21baa78"
EXPECTED_BASELINE_TAIL = {
    "tick": 582,
    "terminal_reason": "physical-hit",
    "game_frame": 582,
    "score": 29110,
    "enemy_count": 2,
    "stage_vm": {
        "loaded": True,
        "script_time": 582,
        "instruction_index": 3,
    },
    "ecl_timeline": {
        "time": 582,
        "next_time": 600,
    },
    "anm_metrics": {
        "suspicious_sprites_loaded": 1,
        "set_active_sprite_failures": 0,
    },
}
TARGET_ENTRIES = ("stg7bg.anm", "stg7enm.anm", "stg7enm2.anm")
TARGET_MUTANTS = {
    "first-sprite-offset-zero": {
        "trace_sha256": "a852bf2b1230dcb2db790c2925ad1b3e8b3cba04fb1167d6b2bdb0cd894b09c7",
        "finding_kinds": {
            "process-signal",
            "anm-set-active-sprite-failure",
            "anm-suspicious-sprite",
            "anm-load-drift",
            "trace-shortfall",
            "terminal-reason-drift",
        },
    },
    "first-script-id-ffff": {
        "trace_sha256": "a00e02aa918e1d2e1d789403f5f1fb13b88153061d5be6ac6ae193fc5ea8ea06",
        "finding_kinds": {
            "process-signal",
            "anm-script-drift",
            "trace-shortfall",
            "terminal-reason-drift",
        },
    },
    "first-script-offset-zero": {
        "trace_sha256": "554c77d3f209f73cdafbef5f3153c74cbe893a39a2ca4ab254220ba56d97f4d2",
        "finding_kinds": {
            "process-signal",
            "anm-script-drift",
            "trace-shortfall",
            "terminal-reason-drift",
        },
    },
    "first-instr-opcode-255": {
        "trace_sha256": "fc493fcaafe8134f172ed1f5407413ca2d77d15f4739d2882adaa4aacb90a25d",
        "finding_kinds": {
            "process-signal",
            "trace-shortfall",
            "terminal-reason-drift",
        },
    },
}


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


def _selected_mutants(archive_path: Path) -> dict[str, dict[str, bytes]]:
    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    selected: dict[str, dict[str, bytes]] = {name: {} for name in TARGET_MUTANTS}
    for entry_name in TARGET_ENTRIES:
        payload = archive.extract(entry_name)
        baseline = parse_anm(payload, max_script_instructions=4096)
        mutants = {mutant.name: mutant for mutant in generate_anm_mutants(payload)}
        for mutant_name in TARGET_MUTANTS:
            mutant = mutants.get(mutant_name)
            if mutant is None:
                raise RuntimeError(f"{entry_name} lost target mutant {mutant_name}")
            evaluation = evaluate_anm_payload(mutant.payload, baseline, max_script_instructions=4096)
            if evaluation["classification"] != "accepted" or not bool(evaluation.get("interesting")):
                raise RuntimeError(
                    f"{entry_name}/{mutant_name} no longer accepted-interesting: {evaluation}"
                )
            selected[mutant_name][entry_name] = mutant.payload
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 7 coordinated ANM-triad SIGSEGV basin."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "runtime-anm-stage7-triad-runtime-sigsegv-basin",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    game_dir = args.game_dir.resolve()
    binary = args.headless_bin.resolve()
    actions = args.actions.resolve()
    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    selected = _selected_mutants(archive_path)

    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=binary,
        game_dir=game_dir,
        resource_override_dir=None,
        stage=TARGET_STAGE,
        seed=TARGET_SEED,
        action_file=actions,
        artifact_dir=baseline_dir,
        difficulty=TARGET_DIFFICULTY,
        character=TARGET_CHARACTER,
        shot_type=TARGET_SHOT_TYPE,
        max_ticks=TARGET_MAX_TICKS,
        auto_shoot=True,
        continue_after_hit=False,
        trace_compact_counts=False,
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

    cases: list[dict[str, object]] = []
    for index, (mutant_name, expectations) in enumerate(TARGET_MUTANTS.items(), start=1):
        case_dir = artifact_dir / f"{index:04d}-{mutant_name}"
        ensure_directory(case_dir)
        override_payloads = selected[mutant_name]
        override_dir = materialize_override_bundle(case_dir, override_payloads)
        active_override_dir = stage_active_override_bundle(
            game_dir,
            override_payloads,
            namespace=f"finding-stage7-triad-{mutant_name}",
        )
        trace_path = case_dir / "trace.jsonl"
        log_path = case_dir / "run.log"
        command = build_command(
            binary=binary,
            game_dir=game_dir,
            stage=TARGET_STAGE,
            seed=TARGET_SEED,
            actions=actions,
            trace=trace_path,
            difficulty=TARGET_DIFFICULTY,
            character=TARGET_CHARACTER,
            shot_type=TARGET_SHOT_TYPE,
            max_ticks=TARGET_MAX_TICKS,
            auto_shoot=True,
            continue_after_hit=False,
            trace_compact_counts=False,
        )
        run_env = dict(os.environ)
        run_env["DANMAKUFUZZ_OVERRIDE_DIR"] = str(active_override_dir.resolve())
        with log_path.open("w", encoding="utf-8") as log_handle:
            completed = subprocess.run(
                command,
                cwd=game_dir,
                env=run_env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        findings = classify_process_result(completed.returncode, timed_out=False)
        findings.extend(score_trace_path_with_baseline(trace_path, baseline_records=baseline_records))
        finding_rows = [{"kind": finding.kind, "detail": finding.detail} for finding in findings]
        finding_kinds = {row["kind"] for row in finding_rows}

        if completed.returncode != -11:
            raise RuntimeError(f"{mutant_name} returncode drifted: expected -11, got {completed.returncode}")
        if not trace_path.is_file() or trace_path.stat().st_size == 0:
            raise RuntimeError(f"{mutant_name} stopped producing a partial trace")
        trace_records = load_trace_records(trace_path)
        if len(trace_records) != 440:
            raise RuntimeError(
                f"{mutant_name} trace length drifted: expected 440, got {len(trace_records)}"
            )
        trace_sha256 = str(expectations["trace_sha256"])
        actual_trace_sha256 = _trace_sha256(trace_path)
        if actual_trace_sha256 != trace_sha256:
            raise RuntimeError(
                f"{mutant_name} trace hash drifted: expected {trace_sha256}, got {actual_trace_sha256}"
            )
        expected_kinds = set(expectations["finding_kinds"])
        if finding_kinds != expected_kinds:
            raise RuntimeError(
                f"{mutant_name} finding kinds drifted: expected {sorted(expected_kinds)}, got {sorted(finding_kinds)}"
            )

        cases.append(
            {
                "mutant_name": mutant_name,
                "command": command,
                "returncode": completed.returncode,
                "trace": str(trace_path.resolve()),
                "trace_lines": len(trace_records),
                "trace_sha256": actual_trace_sha256,
                "log": str(log_path.resolve()),
                "override_dir": str(override_dir.resolve()),
                "active_override_dir": str(active_override_dir.resolve()),
                "finding_kinds": sorted(finding_kinds),
                "findings": finding_rows,
            }
        )

    summary = {
        "finding": FINDING_NAME,
        "archive": str(archive_path),
        "entries": list(TARGET_ENTRIES),
        "baseline_trace_sha256": baseline_trace_sha256,
        "baseline": baseline_metadata,
        "cases": cases,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
