from __future__ import annotations

import argparse
import json
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive
from danmakufuzz.headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    default_headless_binary,
    run_baseline,
)
from danmakufuzz.headless.prepare_worker_game_dir import prepare_worker_game_dir
from danmakufuzz.interestingness.rules import load_trace_records, score_trace_path_with_baseline
from danmakufuzz.parser.anm import DEFAULT_ARCHIVE
from danmakufuzz.parser.anm_mutants import generate_anm_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_ENTRY = "stg1bg.anm"
TARGET_MUTANTS = {
    "name-offset-zero": {"anm-texture-load-failure", "unexpected-terminal", "terminal-reason-drift"},
    "width-neg1": {
        "anm-texture-load-failure",
        "anm-texture-size-mismatch",
        "unexpected-terminal",
        "terminal-reason-drift",
    },
    "height-neg1": {
        "anm-texture-load-failure",
        "anm-texture-size-mismatch",
        "unexpected-terminal",
        "terminal-reason-drift",
    },
    "first-sprite-offset-zero": {
        "anm-load-drift",
        "anm-set-active-sprite-failure",
        "anm-suspicious-sprite",
    },
    "first-script-id-ffff": {"anm-script-drift"},
    "first-script-offset-zero": {"anm-script-drift", "anm-non-finite"},
    "first-instr-argsize-zero": {"anm-script-drift"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 1 background ANM runtime-oracle smoke finding."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "runtime-anm-stage1bg-runtime-oracle-smoke",
    )
    return parser.parse_args()


def _mutant_payloads(archive_path: Path) -> dict[str, bytes]:
    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    seed_payload = archive.extract(TARGET_ENTRY)
    payloads = {
        mutant.name: mutant.payload
        for mutant in generate_anm_mutants(seed_payload)
        if mutant.name in TARGET_MUTANTS
    }
    missing = sorted(set(TARGET_MUTANTS) - set(payloads))
    if missing:
        raise RuntimeError(f"target ANM mutants disappeared: {missing}")
    return payloads


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    game_dir = args.game_dir.resolve()
    headless_bin = args.headless_bin.resolve()
    actions = args.actions.resolve()
    artifact_dir = args.artifact_dir.resolve()

    if not archive_path.is_file():
        raise FileNotFoundError(f"missing archive seed: {archive_path}")
    if not game_dir.is_dir():
        raise FileNotFoundError(f"missing game dir: {game_dir}")
    if not headless_bin.is_file():
        raise FileNotFoundError(f"missing headless binary: {headless_bin}")

    ensure_directory(artifact_dir)
    payloads = _mutant_payloads(archive_path)

    baseline_game_dir = artifact_dir / "worker-baseline"
    baseline_worker_prepare = prepare_worker_game_dir(
        source_game_dir=game_dir,
        destination=baseline_game_dir,
        worker_name="runtime-anm-stage1bg-baseline",
        reuse=True,
    )
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=headless_bin,
        game_dir=baseline_game_dir,
        resource_override_dir=None,
        stage=1,
        seed=7,
        action_file=actions,
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
    baseline_records = load_trace_records(baseline_trace)

    baseline_last = baseline_records[-1] if baseline_records else {}
    if baseline_last.get("terminal_reason") != "physical-hit":
        raise RuntimeError(f"baseline terminal drifted: {baseline_last}")
    if baseline_last.get("tick") != 311:
        raise RuntimeError(f"baseline tick drifted: {baseline_last}")

    cases: list[dict[str, object]] = []
    for mutant_name, expected_kinds in TARGET_MUTANTS.items():
        case_dir = artifact_dir / mutant_name
        worker_game_dir = case_dir / "worker"
        worker_prepare = prepare_worker_game_dir(
            source_game_dir=game_dir,
            destination=worker_game_dir,
            worker_name=f"runtime-anm-stage1bg-{mutant_name}",
            reuse=False,
        )
        override_dir = case_dir / "override"
        ensure_directory(override_dir / "data")
        payload_path = override_dir / "data" / TARGET_ENTRY
        payload_path.write_bytes(payloads[mutant_name])

        metadata = run_baseline(
            binary=headless_bin,
            game_dir=worker_game_dir,
            resource_override_dir=override_dir,
            stage=1,
            seed=7,
            action_file=actions,
            artifact_dir=case_dir,
            difficulty=3,
            character=0,
            shot_type=0,
            max_ticks=600,
            auto_shoot=True,
            continue_after_hit=False,
            dry_run=False,
        )
        trace_path = Path(str(metadata["trace"]))
        findings = score_trace_path_with_baseline(trace_path, baseline_records=baseline_records)
        finding_kinds = {finding.kind for finding in findings}
        missing = sorted(expected_kinds - finding_kinds)
        if missing:
            raise RuntimeError(
                f"{mutant_name} stopped hitting expected runtime findings: missing={missing} got={sorted(finding_kinds)}"
            )
        cases.append(
            {
                "mutant_name": mutant_name,
                "expected_kinds": sorted(expected_kinds),
                "finding_kinds": sorted(finding_kinds),
                "trace": str(trace_path.resolve()),
                "payload_path": str(payload_path.resolve()),
                "worker_game_prepare": worker_prepare,
                "findings": [finding.__dict__ for finding in findings],
            }
        )

    summary = {
        "finding": "runtime/anm-stage1bg-runtime-oracle-smoke",
        "archive": str(archive_path),
        "entry": TARGET_ENTRY,
        "baseline": {
            "trace": str(baseline_trace.resolve()),
            "worker_game_prepare": baseline_worker_prepare,
            "command": baseline_metadata["command"],
        },
        "cases": cases,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
