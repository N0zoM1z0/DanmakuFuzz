from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from ..repo import ARTIFACTS_DIR, ensure_directory


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "retail-batch" / stamp


def _load_report(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"retail report is not an object: {path}")
    return value


def _case_label(result_path: Path) -> str:
    if result_path.name == "summary.json":
        return result_path.parent.name
    if result_path.name == "result.json":
        return result_path.parent.name
    return result_path.stem


def _discover_results(result_args: list[Path], from_minimized: bool) -> list[Path]:
    discovered: list[Path] = []
    for item in result_args:
        resolved = item.resolve()
        if resolved.is_file():
            discovered.append(resolved)
            continue
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("summary.json")))
            discovered.extend(sorted(resolved.rglob("result.json")))
            continue
        raise FileNotFoundError(f"retail batch input does not exist: {resolved}")
    if from_minimized:
        discovered.extend(sorted((ARTIFACTS_DIR / "semantic-minimized").glob("*/summary.json")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay multiple semantic/minimized cases through the retail confirmation runner."
    )
    parser.add_argument(
        "--result",
        type=Path,
        action="append",
        default=[],
        help="one result.json / summary.json, or a directory to scan recursively",
    )
    parser.add_argument(
        "--from-minimized",
        action="store_true",
        help="append all artifacts/semantic-minimized/*/summary.json cases",
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--source-game-dir", type=Path)
    parser.add_argument("--practice-stage", type=int, choices=range(1, 7))
    parser.add_argument("--difficulty", type=int, choices=range(4))
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--stop-on-classification",
        action="append",
        default=[],
        help="stop after the first case whose termination_reason matches this value",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.result and not args.from_minimized:
        raise ValueError("retail batch needs at least one --result or --from-minimized")

    results = _discover_results(args.result, args.from_minimized)
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        results = results[:args.limit]
    if not results:
        raise ValueError("retail batch did not find any result.json / summary.json inputs")

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    summary_path = artifact_dir / "summary.json"
    lines_path = artifact_dir / "results.jsonl"

    base_command = [sys.executable, "-m", "danmakufuzz.retail.confirm_case"]
    if args.source_game_dir is not None:
        base_command.extend(["--source-game-dir", str(args.source_game_dir.resolve())])
    if args.practice_stage is not None:
        base_command.extend(["--practice-stage", str(args.practice_stage)])
    if args.difficulty is not None:
        base_command.extend(["--difficulty", str(args.difficulty)])
    if args.timeout_seconds is not None:
        if args.timeout_seconds <= 0:
            raise ValueError("--timeout-seconds must be positive")
        base_command.extend(["--timeout-seconds", str(args.timeout_seconds)])
    if args.prepare_only:
        base_command.append("--prepare-only")
    if args.dry_run:
        base_command.append("--dry-run")

    entries: list[dict[str, object]] = []
    classifications: Counter[str] = Counter()
    stopped_early = False
    stop_set = set(args.stop_on_classification)

    with lines_path.open("w", encoding="utf-8") as lines:
        for index, result_path in enumerate(results, start=1):
            case_name = _case_label(result_path)
            case_artifact_dir = artifact_dir / f"{index:04d}-{case_name}"
            command = [
                *base_command,
                "--result",
                str(result_path),
                "--artifact-dir",
                str(case_artifact_dir),
            ]
            completed = subprocess.run(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            stdout_path = case_artifact_dir / "batch-wrapper.stdout"
            ensure_directory(case_artifact_dir)
            stdout_path.write_text(completed.stdout, encoding="utf-8")

            report_path = case_artifact_dir / "report.json"
            report = _load_report(report_path) if report_path.is_file() else None
            termination_reason = None
            oracle_classification = None
            if isinstance(report, dict):
                run = report.get("run")
                if isinstance(run, dict):
                    termination_reason = run.get("termination_reason")
                    control = run.get("control")
                    if isinstance(control, dict):
                        oracle = control.get("oracle")
                        if isinstance(oracle, dict):
                            oracle_classification = oracle.get("classification")
            classification = (
                str(termination_reason)
                if isinstance(termination_reason, str)
                else str(oracle_classification)
                if isinstance(oracle_classification, str)
                else "unknown"
            )
            classifications[classification] += 1
            entry = {
                "index": index,
                "case_name": case_name,
                "result": str(result_path),
                "artifact_dir": str(case_artifact_dir),
                "report": str(report_path) if report_path.is_file() else None,
                "stdout": str(stdout_path),
                "returncode": completed.returncode,
                "classification": classification,
                "report_present": report_path.is_file(),
            }
            entries.append(entry)
            lines.write(json.dumps(entry, sort_keys=True) + "\n")
            lines.flush()
            if classification in stop_set:
                stopped_early = True
                break

    summary = {
        "schema": "danmakufuzz-retail-batch-v1",
        "artifact_dir": str(artifact_dir),
        "results_jsonl": str(lines_path),
        "inputs": [str(path) for path in results],
        "cases_attempted": len(entries),
        "classifications": dict(sorted(classifications.items())),
        "stopped_early": stopped_early,
        "entries": entries,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
