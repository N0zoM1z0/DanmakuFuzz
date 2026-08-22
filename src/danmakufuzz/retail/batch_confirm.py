from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from ..repo import ARTIFACTS_DIR, ensure_directory


FINDING_SEVERITY = {
    "process-signal": 0,
    "timeout": 1,
    "process-exit": 2,
    "missing-returncode": 3,
    "non-finite": 4,
    "stalled-frame": 5,
    "unexpected-terminal": 6,
    "bullet-explosion": 7,
    "laser-explosion": 8,
    "enemy-explosion": 9,
    "empty-trace": 10,
}


@dataclass(frozen=True)
class QueueCase:
    result_path: Path
    case_name: str
    source_kind: str
    source_result: str | None
    interesting: bool
    primary_finding_kind: str | None
    primary_finding_detail: str | None
    finding_keys: tuple[str, ...]
    payload_size: int | None
    order_index: int

    @property
    def primary_finding_key(self) -> str:
        return _finding_key(self.primary_finding_kind, self.primary_finding_detail)

    def priority_key(self) -> tuple[object, ...]:
        return (
            0 if self.interesting else 1,
            FINDING_SEVERITY.get(self.primary_finding_kind or "", 99),
            0 if self.source_kind == "minimized-summary" else 1,
            self.payload_size if self.payload_size is not None else sys.maxsize,
            self.case_name,
            str(self.result_path),
        )

    def to_summary(self) -> dict[str, object]:
        return {
            "case_name": self.case_name,
            "result": str(self.result_path),
            "source_kind": self.source_kind,
            "source_result": self.source_result,
            "interesting": self.interesting,
            "primary_finding": {
                "kind": self.primary_finding_kind,
                "detail": self.primary_finding_detail,
                "key": self.primary_finding_key,
            },
            "finding_keys": list(self.finding_keys),
            "payload_size": self.payload_size,
            "order_index": self.order_index,
        }


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


def _finding_key(kind: str | None, detail: str | None) -> str:
    normalized_kind = kind or "unknown"
    return f"{normalized_kind}:{detail}" if detail else normalized_kind


def _finding_pair(value: object) -> tuple[str | None, str | None] | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    detail = value.get("detail")
    if not isinstance(kind, str):
        return None
    return kind, detail if isinstance(detail, str) else None


def _ordered_findings(data: dict[str, object]) -> list[tuple[str | None, str | None]]:
    ordered: list[tuple[str | None, str | None]] = []
    for key in ("target",):
        pair = _finding_pair(data.get(key))
        if pair is not None:
            ordered.append(pair)
    for key in ("final_findings", "findings"):
        value = data.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            pair = _finding_pair(item)
            if pair is not None:
                ordered.append(pair)
    unique: list[tuple[str | None, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for pair in ordered:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    return unique


def _payload_size_for_case(data: dict[str, object], result_path: Path) -> int | None:
    for key in ("minimized_size", "original_size", "payload_size"):
        value = data.get(key)
        if isinstance(value, int) and value >= 0:
            if key == "original_size" and isinstance(data.get("minimized_size"), int):
                continue
            return value
    final_payload = data.get("final_payload")
    if isinstance(final_payload, str):
        payload_path = Path(final_payload)
        if payload_path.is_file():
            return payload_path.stat().st_size
    override_dir = data.get("override_dir")
    seed_name = data.get("seed_name")
    if isinstance(override_dir, str) and isinstance(seed_name, str):
        payload_path = Path(override_dir) / "data" / seed_name
        if payload_path.is_file():
            return payload_path.stat().st_size
    payload_path = data.get("payload_path")
    if isinstance(payload_path, str):
        candidate = Path(payload_path)
        if candidate.is_file():
            return candidate.stat().st_size
    return None


def _source_kind_from_data(data: dict[str, object], result_path: Path) -> str:
    override_dir = data.get("override_dir")
    seed_name = data.get("seed_name")
    if isinstance(override_dir, str) and isinstance(seed_name, str):
        return "semantic-result"
    final_payload = data.get("final_payload")
    if isinstance(final_payload, str):
        return "minimized-summary"
    raise ValueError(
        "unsupported retail batch input "
        f"(expected semantic result.json or minimizer summary.json): {result_path}"
    )


def _queue_case_from_result(result_path: Path, order_index: int) -> QueueCase:
    data = _load_report(result_path)
    source_kind = _source_kind_from_data(data, result_path)
    findings = _ordered_findings(data)
    primary = findings[0] if findings else (None, None)
    interesting_value = data.get("interesting")
    if isinstance(interesting_value, bool):
        interesting = interesting_value
    else:
        interesting = bool(findings) or source_kind == "minimized-summary"
    source_result = data.get("source_result")
    return QueueCase(
        result_path=result_path,
        case_name=_case_label(result_path),
        source_kind=source_kind,
        source_result=source_result if isinstance(source_result, str) else None,
        interesting=interesting,
        primary_finding_kind=primary[0],
        primary_finding_detail=primary[1],
        finding_keys=tuple(_finding_key(kind, detail) for kind, detail in findings),
        payload_size=_payload_size_for_case(data, result_path),
        order_index=order_index,
    )


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
    parser.add_argument(
        "--priority-order",
        choices=("input", "priority"),
        default="priority",
        help="queue ordering: preserve discovered order or sort by headless interestingness/finding severity",
    )
    parser.add_argument(
        "--interesting-only",
        action="store_true",
        help="replay only source cases already marked interesting by the semantic lane",
    )
    parser.add_argument(
        "--finding-kind",
        action="append",
        default=[],
        help="replay only cases whose headless findings contain this kind",
    )
    parser.add_argument(
        "--max-per-finding",
        type=int,
        help="cap how many queued cases may share the same primary headless finding key",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="print the selected replay queue and write summary.json without launching retail workers",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--stop-on-classification",
        action="append",
        default=[],
        help="stop after the first case whose termination_reason matches this value",
    )
    return parser.parse_args()


def _select_queue_cases(results: list[Path], args: argparse.Namespace) -> list[QueueCase]:
    queue = [_queue_case_from_result(path, index) for index, path in enumerate(results, start=1)]
    if args.interesting_only:
        queue = [case for case in queue if case.interesting]
    if args.finding_kind:
        allowed = set(args.finding_kind)
        queue = [
            case
            for case in queue
            if any(key.split(":", 1)[0] in allowed for key in case.finding_keys)
        ]
    if args.priority_order == "priority":
        queue = sorted(queue, key=lambda case: case.priority_key())
    else:
        queue = sorted(queue, key=lambda case: case.order_index)
    if args.max_per_finding is not None:
        if args.max_per_finding <= 0:
            raise ValueError("--max-per-finding must be positive")
        limited: list[QueueCase] = []
        seen: Counter[str] = Counter()
        for case in queue:
            key = case.primary_finding_key
            if seen[key] >= args.max_per_finding:
                continue
            seen[key] += 1
            limited.append(case)
        queue = limited
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        queue = queue[:args.limit]
    return queue


def main() -> int:
    args = parse_args()
    if not args.result and not args.from_minimized:
        raise ValueError("retail batch needs at least one --result or --from-minimized")

    results = _discover_results(args.result, args.from_minimized)
    if not results:
        raise ValueError("retail batch did not find any result.json / summary.json inputs")
    queue = _select_queue_cases(results, args)
    if not queue:
        raise ValueError("retail batch filters removed every discovered result")

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

    queue_summary = [case.to_summary() for case in queue]
    if args.list_only:
        summary = {
            "schema": "danmakufuzz-retail-batch-v1",
            "artifact_dir": str(artifact_dir),
            "results_jsonl": None,
            "inputs": [str(path) for path in results],
            "queue_options": {
                "priority_order": args.priority_order,
                "interesting_only": args.interesting_only,
                "finding_kind": args.finding_kind,
                "max_per_finding": args.max_per_finding,
                "limit": args.limit,
                "list_only": True,
            },
            "cases_selected": len(queue),
            "cases_attempted": 0,
            "classifications": {},
            "stopped_early": False,
            "queue": queue_summary,
            "entries": [],
        }
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0

    entries: list[dict[str, object]] = []
    classifications: Counter[str] = Counter()
    stopped_early = False
    stop_set = set(args.stop_on_classification)

    with lines_path.open("w", encoding="utf-8") as lines:
        for index, case in enumerate(queue, start=1):
            result_path = case.result_path
            case_name = case.case_name
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
                "source_kind": case.source_kind,
                "source_result": case.source_result,
                "interesting": case.interesting,
                "primary_finding": {
                    "kind": case.primary_finding_kind,
                    "detail": case.primary_finding_detail,
                    "key": case.primary_finding_key,
                },
                "finding_keys": list(case.finding_keys),
                "payload_size": case.payload_size,
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
        "queue_options": {
            "priority_order": args.priority_order,
            "interesting_only": args.interesting_only,
            "finding_kind": args.finding_kind,
            "max_per_finding": args.max_per_finding,
            "limit": args.limit,
            "list_only": False,
        },
        "cases_selected": len(queue),
        "cases_attempted": len(entries),
        "classifications": dict(sorted(classifications.items())),
        "stopped_early": stopped_early,
        "queue": queue_summary,
        "entries": entries,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
