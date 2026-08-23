from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from danmakufuzz.headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary
from danmakufuzz.interestingness.rules import load_trace_records
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory
from danmakufuzz.semantic.replay_desync_campaign import run_replay_desync_campaign


FINDING_NAME = "semantic/replay-native-first-bookmark-cut-tail-input-error-basin"
EXPECTED_MUTANT_NAME = "bookmark-cut-tail-i001-t1"
EXPECTED_FINDING_KINDS = {"process-exit", "replay-stable-trace-drift"}
EXPECTED_TERMINAL_REASON = "input-error"
EXPECTED_TICK = 3


def _here() -> Path:
    return Path(__file__).resolve().parent


def _load_cases() -> dict[str, object]:
    return json.loads((_here() / "cases.json").read_text(encoding="utf-8"))


def _ensure_public_replays(replay_dir: Path, cases: list[dict[str, object]]) -> None:
    missing = [
        str(case["public_replay"])
        for case in cases
        if not (replay_dir / str(case["filename"])).is_file()
    ]
    if not missing:
        return
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC_DIR}:{existing_pythonpath}" if existing_pythonpath else str(SRC_DIR)
    command = [
        sys.executable,
        "-m",
        "danmakufuzz.corpus.fetch_public_replays",
        "--manifest",
        str((REPO_ROOT / "reference/corpus/replay/public/th06/manifest.json").resolve()),
        "--output-dir",
        str(replay_dir.resolve()),
    ]
    for name in missing:
        command.extend(["--only", name])
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=env)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the replay-native first-bookmark cut-tail input-error basin."
    )
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument(
        "--replay-dir",
        type=Path,
        default=ARTIFACTS_DIR / "replay-corpus-public" / "th06",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-replay-native-first-bookmark-cut-tail-input-error-basin",
    )
    return parser.parse_args()


def _assert_runtime(actual: dict[str, object], expected: dict[str, object], *, label: str) -> None:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if actual_value != expected_value:
            raise RuntimeError(
                f"{label} runtime field {key!r} drifted: expected {expected_value!r}, got {actual_value!r}"
            )


def main() -> int:
    args = parse_args()
    config = _load_cases()
    if str(config.get("mutant_name")) != EXPECTED_MUTANT_NAME:
        raise RuntimeError("cases.json mutant_name drifted")
    cases = config.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("cases.json is missing non-empty cases")

    replay_dir = args.replay_dir.resolve()
    replay_dir.mkdir(parents=True, exist_ok=True)
    _ensure_public_replays(replay_dir, cases)

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)
    actions_path = args.actions.resolve()
    game_dir = args.game_dir.resolve()
    binary = args.headless_bin.resolve()

    reports: list[dict[str, object]] = []
    for case in cases:
        if not isinstance(case, dict):
            raise RuntimeError("cases.json entry is not an object")
        case_name = str(case["name"])
        replay_path = replay_dir / str(case["filename"])
        if not replay_path.is_file():
            raise FileNotFoundError(f"missing replay after fetch: {replay_path}")
        case_artifact_dir = artifact_dir / case_name
        report = run_replay_desync_campaign(
            artifact_dir=case_artifact_dir,
            input_path=replay_path.resolve(),
            actions_path=actions_path,
            game_dir=game_dir,
            headless_bin=binary,
            stage=int(case["stage"]),
            seed=None,
            difficulty=None,
            character=None,
            shot_type=None,
            max_ticks=int(case["max_ticks"]),
            timeout_seconds=8.0,
            auto_shoot=True,
            continue_after_hit=bool(config["continue_after_hit"]),
            trace_compact_counts=bool(config["trace_compact_counts"]),
            random_seed=int(config["random_seed"]),
            samples_per_site=int(config["samples_per_site"]),
            limit=1,
            mutant_profile=str(config["mutant_profile"]),
            name_filters=[EXPECTED_MUTANT_NAME],
            emit_stdout=False,
        )
        summary_path = Path(str(report["summary"]))
        rows = [json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) != 1:
            raise RuntimeError(f"{case_name} expected exactly one replay mutant row, got {len(rows)}")
        row = rows[0]
        if row.get("mutant_name") != EXPECTED_MUTANT_NAME:
            raise RuntimeError(
                f"{case_name} mutant drifted: expected {EXPECTED_MUTANT_NAME}, got {row.get('mutant_name')}"
            )
        findings = row.get("findings")
        if not isinstance(findings, list):
            raise RuntimeError(f"{case_name} findings missing")
        finding_kinds = {str(finding.get('kind')) for finding in findings if isinstance(finding, dict)}
        if not EXPECTED_FINDING_KINDS.issubset(finding_kinds):
            raise RuntimeError(
                f"{case_name} findings drifted: expected at least {sorted(EXPECTED_FINDING_KINDS)}, got {sorted(finding_kinds)}"
            )
        runtime = row.get("runtime")
        if not isinstance(runtime, dict):
            raise RuntimeError(f"{case_name} runtime metadata missing")
        _assert_runtime(runtime, dict(case["expected_runtime"]), label=case_name)
        if row.get("run_a", {}).get("returncode") != 1 or row.get("run_b", {}).get("returncode") != 1:
            raise RuntimeError(
                f"{case_name} expected returncode 1/1, got {row.get('run_a', {}).get('returncode')} / {row.get('run_b', {}).get('returncode')}"
            )
        trace_path = Path(str(row["run_a"]["trace"]))
        trace_rows = load_trace_records(trace_path)
        if not trace_rows:
            raise RuntimeError(f"{case_name} trace is empty")
        tail = trace_rows[-1]
        if tail.get("terminal_reason") != EXPECTED_TERMINAL_REASON:
            raise RuntimeError(
                f"{case_name} terminal_reason drifted: expected {EXPECTED_TERMINAL_REASON!r}, got {tail.get('terminal_reason')!r}"
            )
        if tail.get("tick") != EXPECTED_TICK:
            raise RuntimeError(
                f"{case_name} tail tick drifted: expected {EXPECTED_TICK}, got {tail.get('tick')}"
            )
        actual_trace_sha = str(row["run_a"]["trace_sha256"])
        expected_trace_sha = str(case["expected_trace_sha256"])
        if actual_trace_sha != expected_trace_sha:
            raise RuntimeError(
                f"{case_name} trace sha drifted: expected {expected_trace_sha}, got {actual_trace_sha}"
            )
        if str(row["run_b"]["trace_sha256"]) != expected_trace_sha:
            raise RuntimeError(
                f"{case_name} repeat trace sha drifted: expected {expected_trace_sha}, got {row['run_b']['trace_sha256']}"
            )
        reports.append(
            {
                "name": case_name,
                "replay": str(replay_path),
                "stage": case["stage"],
                "mutant_name": row["mutant_name"],
                "trace_sha256": actual_trace_sha,
                "terminal_reason": tail.get("terminal_reason"),
                "tick": tail.get("tick"),
                "findings": findings,
                "artifact_dir": str(case_artifact_dir.resolve()),
            }
        )

    summary = {
        "finding": FINDING_NAME,
        "mutant_name": EXPECTED_MUTANT_NAME,
        "cases": reports,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
