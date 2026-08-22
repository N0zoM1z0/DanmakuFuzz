from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from danmakufuzz.findings.payload_patch import apply_payload_patch, load_payload_patch
from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from danmakufuzz.interestingness.rules import score_trace
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from danmakufuzz.semantic.ecl_campaign import LONG_ACTION_FILE


FINDING_DIR = Path(__file__).resolve().parent
TARGET_PATCH = FINDING_DIR / "payload_patch.json"
TARGET_SEED = REFERENCE_DIR / "corpus" / "ecl" / "original" / "ecldata2.ecl"


def _target_payload() -> tuple[bytes, dict[str, object]]:
    seed_payload = TARGET_SEED.read_bytes()
    patch = load_payload_patch(TARGET_PATCH)
    return apply_payload_patch(seed_payload, patch), patch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce the Stage 2 time-set-zero headless stall finding.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-stage2-time-set-zero-stall",
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
    if not TARGET_PATCH.is_file():
        raise FileNotFoundError(f"missing payload patch: {TARGET_PATCH}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    override_dir = artifact_dir / "override"
    ensure_directory(override_dir / "data")
    payload, patch = _target_payload()
    payload_path = override_dir / "data" / TARGET_SEED.name
    payload_path.write_bytes(payload)

    headless_dir = artifact_dir / "headless"
    metadata = run_baseline(
        binary=args.headless_bin.resolve(),
        game_dir=args.game_dir.resolve(),
        resource_override_dir=override_dir,
        stage=2,
        seed=7,
        action_file=LONG_ACTION_FILE,
        artifact_dir=headless_dir,
        difficulty=3,
        character=0,
        shot_type=0,
        max_ticks=1800,
        auto_shoot=True,
        continue_after_hit=True,
        dry_run=False,
    )
    trace_path = Path(str(metadata["trace"]))
    findings = [{"kind": finding.kind, "detail": finding.detail} for finding in score_trace(trace_path)]
    summary: dict[str, object] = {
        "finding": "semantic/stage2-time-set-zero-stall",
        "seed_ecl": str(TARGET_SEED.resolve()),
        "payload_patch": str(TARGET_PATCH.resolve()),
        "payload_sha256": patch["target_sha256"],
        "payload_path": str(payload_path.resolve()),
        "headless": {
            "artifact_dir": str(headless_dir.resolve()),
            "trace": str(trace_path.resolve()),
            "findings": findings,
            "command": metadata["command"],
        },
    }

    if args.retail:
        synthetic_result = artifact_dir / "synthetic-result.json"
        synthetic_result.write_text(
            json.dumps(
                {
                    "case_name": "finding-stage2-time-set-zero-stall",
                    "mutant_name": "tracked-payload-patch",
                    "seed_name": TARGET_SEED.name,
                    "override_dir": str(override_dir.resolve()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        retail_dir = artifact_dir / "retail"
        command = [
            sys.executable,
            "-m",
            "danmakufuzz.retail.confirm_case",
            "--result",
            str(synthetic_result.resolve()),
            "--artifact-dir",
            str(retail_dir.resolve()),
            "--practice-stage",
            "2",
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
