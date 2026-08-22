from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from danmakufuzz.findings.payload_patch import sha256_bytes
from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import LONG_ACTION_FILE, run_case, select_mutants


TARGET_MUTANT_NAME = "jump-offset-large-forward"
TARGET_MUTANT_PATH = (0, 13)
TARGET_PAYLOAD_SHA256 = "a89ae5bf17eab351e0b165814fbc0208424807074b666e225b9248a7a22d893d"
TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata6.ecl"
HEADLESS_TIMEOUT_SECONDS = 20.0


def _target_mutant():
    seed_payload = TARGET_SEED.read_bytes()
    mutants = select_mutants(
        seed_payload,
        include_structural=False,
        name_filters=["jump-offset-"],
    )
    for mutant in mutants:
        if mutant.name == TARGET_MUTANT_NAME and mutant.path == TARGET_MUTANT_PATH:
            mutant_sha256 = sha256_bytes(mutant.payload)
            if mutant_sha256 != TARGET_PAYLOAD_SHA256:
                raise RuntimeError(
                    f"target mutant sha256 drifted: expected {TARGET_PAYLOAD_SHA256}, got {mutant_sha256}"
                )
            return mutant
    raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME} at {TARGET_MUTANT_PATH}")


def _trace_tail_summary(trace_path: Path) -> dict[str, object]:
    last_record: dict[str, object] | None = None
    tick_count = 0
    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            tick_count += 1
            last_record = json.loads(line)
    if last_record is None:
        return {"tick_count": 0}
    stage_vm = last_record.get("stage_vm")
    ecl_timeline = last_record.get("ecl_timeline")
    return {
        "tick_count": tick_count,
        "last_tick": last_record.get("tick"),
        "last_game_frame": last_record.get("game_frame"),
        "stage_vm_loaded": stage_vm.get("loaded") if isinstance(stage_vm, dict) else None,
        "stage_vm_script_time": stage_vm.get("script_time") if isinstance(stage_vm, dict) else None,
        "stage_vm_instruction_index": stage_vm.get("instruction_index") if isinstance(stage_vm, dict) else None,
        "ecl_timeline_time": ecl_timeline.get("time") if isinstance(ecl_timeline, dict) else None,
        "ecl_timeline_next_time": ecl_timeline.get("next_time") if isinstance(ecl_timeline, dict) else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 jump-offset-large-forward headless-wedge finding."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage6-jump-offset-large-forward-headless-wedge",
    )
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--retail", action="store_true")
    parser.add_argument("--retail-timeout-seconds", type=float, default=35.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not TARGET_SEED.is_file():
        raise FileNotFoundError(f"missing seed corpus entry: {TARGET_SEED}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    baseline_dir = artifact_dir / "baseline"
    baseline_metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=None,
        stage=6,
        seed=7,
        action_file=LONG_ACTION_FILE,
        artifact_dir=baseline_dir,
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
        game_dir=args.game_dir.resolve(),
        stage=6,
        seed=7,
        action_file=LONG_ACTION_FILE,
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=1800,
        auto_shoot=True,
        continue_after_hit=True,
        timeout_seconds=HEADLESS_TIMEOUT_SECONDS,
        campaign_dir=artifact_dir,
        seed_name=TARGET_SEED.name,
        mutant=mutant,
        case_index=1,
        baseline_trace=baseline_trace,
    )
    result_path = artifact_dir / result["case_name"] / "result.json"
    payload_path = Path(str(result["override_dir"])) / "data" / TARGET_SEED.name
    trace_tail = _trace_tail_summary(Path(str(result["trace"])))
    summary: dict[str, object] = {
        "finding": "semantic/stage6-jump-offset-large-forward-headless-wedge",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "target_mutant": {
            "name": TARGET_MUTANT_NAME,
            "path": {
                "sub_index": TARGET_MUTANT_PATH[0],
                "instruction_index": TARGET_MUTANT_PATH[1],
            },
            "payload_sha256": TARGET_PAYLOAD_SHA256,
        },
        "baseline": {
            "artifact_dir": str(baseline_dir.resolve()),
            "trace": str(baseline_trace.resolve()),
            "command": baseline_metadata["command"],
        },
        "headless": {
            "timeout_seconds": HEADLESS_TIMEOUT_SECONDS,
            "result": str(result_path.resolve()),
            "payload_path": str(payload_path.resolve()),
            "trace": result["trace"],
            "log": result["log"],
            "findings": result["findings"],
            "command": result["command"],
            "trace_tail": trace_tail,
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
