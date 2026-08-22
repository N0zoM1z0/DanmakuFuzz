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
from .signatures import normalize_wine_primary_signature, retail_signature_key


FINDING_SEVERITY = {
    "process-signal": 0,
    "timeout": 1,
    "trace-shortfall": 2,
    "process-exit": 2,
    "missing-returncode": 3,
    "non-finite": 4,
    "stalled-frame": 5,
    "life-drift": 6,
    "bomb-drift": 6,
    "score-drift": 6,
    "bullet-count-drift": 7,
    "laser-count-drift": 8,
    "enemy-count-drift": 9,
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


@dataclass(frozen=True)
class RetailHistoryCase:
    origin_path: str
    case_name: str | None
    source_keys: tuple[str, ...]
    primary_finding_key: str | None
    classification: str
    retail_signature_key: str
    wine_log_primary_signature: str | None


@dataclass(frozen=True)
class RetailHistoryIndex:
    cases: tuple[RetailHistoryCase, ...]
    by_source: dict[str, tuple[RetailHistoryCase, ...]]
    by_finding: dict[str, tuple[RetailHistoryCase, ...]]


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


def _queue_source_keys(case: QueueCase) -> tuple[str, ...]:
    ordered: list[str] = [str(case.result_path)]
    if case.source_result is not None:
        ordered.append(case.source_result)
    unique: list[str] = []
    seen: set[str] = set()
    for key in ordered:
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)
    return tuple(unique)


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


def _discover_history_files(history_args: list[Path]) -> list[Path]:
    discovered: list[Path] = []
    for item in history_args:
        resolved = item.resolve()
        if resolved.is_file():
            discovered.append(resolved)
            continue
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("summary.json")))
            discovered.extend(sorted(resolved.rglob("report.json")))
            continue
        raise FileNotFoundError(f"retail history input does not exist: {resolved}")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _history_case(
    *,
    origin_path: Path,
    case_name: str | None,
    source_keys: list[str],
    primary_finding_key: str | None,
    classification: str | None,
    primary_signature: str | None,
) -> RetailHistoryCase | None:
    if not isinstance(classification, str) or not classification:
        return None
    unique_source_keys: list[str] = []
    seen: set[str] = set()
    for key in source_keys:
        if not key or key in seen:
            continue
        seen.add(key)
        unique_source_keys.append(key)
    return RetailHistoryCase(
        origin_path=str(origin_path),
        case_name=case_name,
        source_keys=tuple(unique_source_keys),
        primary_finding_key=primary_finding_key,
        classification=classification,
        retail_signature_key=retail_signature_key(classification, primary_signature),
        wine_log_primary_signature=normalize_wine_primary_signature(primary_signature),
    )


def _history_cases_from_batch_summary(path: Path, data: dict[str, object]) -> list[RetailHistoryCase]:
    if data.get("schema") != "danmakufuzz-retail-batch-v1":
        return []
    entries = data.get("entries")
    if not isinstance(entries, list):
        return []
    history_cases: list[RetailHistoryCase] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        primary = entry.get("primary_finding")
        primary_finding_key = primary.get("key") if isinstance(primary, dict) and isinstance(primary.get("key"), str) else None
        wine_log = entry.get("wine_log")
        primary_signature = (
            wine_log.get("primary_signature")
            if isinstance(wine_log, dict) and isinstance(wine_log.get("primary_signature"), str)
            else None
        )
        source_keys = [
            value
            for value in (
                entry.get("result"),
                entry.get("source_result"),
            )
            if isinstance(value, str)
        ]
        history_case = _history_case(
            origin_path=path,
            case_name=entry.get("case_name") if isinstance(entry.get("case_name"), str) else None,
            source_keys=source_keys,
            primary_finding_key=primary_finding_key,
            classification=entry.get("classification") if isinstance(entry.get("classification"), str) else None,
            primary_signature=primary_signature,
        )
        if history_case is not None:
            history_cases.append(history_case)
    return history_cases


def _history_cases_from_retail_report(path: Path, data: dict[str, object]) -> list[RetailHistoryCase]:
    run = data.get("run")
    if not isinstance(run, dict):
        return []
    wine_log = run.get("wine_log")
    primary_signature = (
        wine_log.get("primary_signature")
        if isinstance(wine_log, dict) and isinstance(wine_log.get("primary_signature"), str)
        else None
    )
    classification = run.get("termination_reason")
    if not isinstance(classification, str):
        oracle = run.get("oracle")
        if isinstance(oracle, dict) and isinstance(oracle.get("classification"), str):
            classification = oracle["classification"]
        else:
            classification = None
    source_keys = [
        value
        for value in (
            data.get("source_result"),
            data.get("semantic_source_result"),
        )
        if isinstance(value, str)
    ]
    history_case = _history_case(
        origin_path=path,
        case_name=path.parent.name,
        source_keys=source_keys,
        primary_finding_key=None,
        classification=classification,
        primary_signature=primary_signature,
    )
    return [history_case] if history_case is not None else []


def _load_history_index(history_args: list[Path]) -> tuple[RetailHistoryIndex, list[str]]:
    files = _discover_history_files(history_args)
    parsed_cases: list[RetailHistoryCase] = []
    for path in files:
        data = _load_report(path)
        parsed_cases.extend(_history_cases_from_batch_summary(path, data))
        parsed_cases.extend(_history_cases_from_retail_report(path, data))
    deduped_cases: dict[tuple[tuple[str, ...], str, str], RetailHistoryCase] = {}
    for case in parsed_cases:
        fingerprint = (
            case.source_keys,
            case.classification,
            case.retail_signature_key,
        )
        existing = deduped_cases.get(fingerprint)
        if existing is None:
            deduped_cases[fingerprint] = case
            continue
        if existing.primary_finding_key is None and case.primary_finding_key is not None:
            deduped_cases[fingerprint] = case
    unique_cases = list(deduped_cases.values())
    by_source: dict[str, list[RetailHistoryCase]] = {}
    by_finding: dict[str, list[RetailHistoryCase]] = {}
    for case in unique_cases:
        for source_key in case.source_keys:
            by_source.setdefault(source_key, []).append(case)
        if case.primary_finding_key is not None:
            by_finding.setdefault(case.primary_finding_key, []).append(case)
    return (
        RetailHistoryIndex(
            cases=tuple(unique_cases),
            by_source={key: tuple(value) for key, value in by_source.items()},
            by_finding={key: tuple(value) for key, value in by_finding.items()},
        ),
        [str(path) for path in files],
    )


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
    parser.add_argument(
        "--history",
        type=Path,
        action="append",
        default=[],
        help="retail summary.json / report.json, or a directory to scan recursively for prior retail outcomes",
    )
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
    parser.add_argument(
        "--skip-known-source",
        action="store_true",
        help="skip queue cases whose semantic/minimized source already appears in retail history",
    )
    parser.add_argument(
        "--skip-known-finding",
        action="store_true",
        help="skip queue cases whose primary headless finding already appears in prior retail batch history",
    )
    parser.add_argument(
        "--skip-known-signature",
        action="store_true",
        help="skip queue cases whose source/finding history predicts one stable known retail signature",
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


def _history_subset(
    *,
    hits: tuple[RetailHistoryCase, ...],
    limit: int = 3,
) -> dict[str, object]:
    classifications: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    examples: list[dict[str, object]] = []
    for hit in hits:
        classifications[hit.classification] += 1
        signatures[hit.retail_signature_key] += 1
        if len(examples) < limit:
            examples.append(
                {
                    "case_name": hit.case_name,
                    "origin_path": hit.origin_path,
                    "classification": hit.classification,
                    "retail_signature_key": hit.retail_signature_key,
                }
            )
    return {
        "hits": len(hits),
        "classifications": dict(sorted(classifications.items())),
        "retail_signatures": dict(sorted(signatures.items())),
        "examples": examples,
    }


def _history_summary_for_case(case: QueueCase, history: RetailHistoryIndex) -> dict[str, object]:
    source_hits_collected: list[RetailHistoryCase] = []
    seen_source_hits: set[tuple[str, str, str]] = set()
    for key in _queue_source_keys(case):
        for hit in history.by_source.get(key, ()):
            fingerprint = (hit.origin_path, hit.case_name or "", hit.retail_signature_key)
            if fingerprint in seen_source_hits:
                continue
            seen_source_hits.add(fingerprint)
            source_hits_collected.append(hit)
    finding_hits = history.by_finding.get(case.primary_finding_key, ())
    source_signature_counts = Counter(hit.retail_signature_key for hit in source_hits_collected)
    finding_signature_counts = Counter(hit.retail_signature_key for hit in finding_hits)
    signature_prediction = {
        "available": False,
        "stable": False,
        "basis": None,
        "retail_signature_key": None,
        "candidate_count": 0,
        "candidates": {},
    }
    if source_signature_counts:
        signature_prediction = {
            "available": True,
            "stable": len(source_signature_counts) == 1,
            "basis": "source",
            "retail_signature_key": (
                next(iter(source_signature_counts))
                if len(source_signature_counts) == 1
                else None
            ),
            "candidate_count": len(source_signature_counts),
            "candidates": dict(sorted(source_signature_counts.items())),
        }
    elif finding_signature_counts:
        signature_prediction = {
            "available": True,
            "stable": len(finding_signature_counts) == 1,
            "basis": "finding",
            "retail_signature_key": (
                next(iter(finding_signature_counts))
                if len(finding_signature_counts) == 1
                else None
            ),
            "candidate_count": len(finding_signature_counts),
            "candidates": dict(sorted(finding_signature_counts.items())),
        }
    return {
        "source": _history_subset(hits=tuple(source_hits_collected)),
        "finding": _history_subset(hits=finding_hits),
        "signature_prediction": signature_prediction,
    }


def _queue_case_summary(case: QueueCase, history: RetailHistoryIndex) -> dict[str, object]:
    summary = case.to_summary()
    summary["history"] = _history_summary_for_case(case, history)
    return summary


def _select_queue_cases(results: list[Path], args: argparse.Namespace, history: RetailHistoryIndex) -> list[QueueCase]:
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
    if args.skip_known_source:
        queue = [
            case
            for case in queue
            if not any(history.by_source.get(key) for key in _queue_source_keys(case))
        ]
    if args.skip_known_finding:
        queue = [
            case
            for case in queue
            if not history.by_finding.get(case.primary_finding_key)
        ]
    if args.skip_known_signature:
        filtered: list[QueueCase] = []
        for case in queue:
            history_summary = _history_summary_for_case(case, history)
            prediction = history_summary.get("signature_prediction")
            if (
                isinstance(prediction, dict)
                and prediction.get("available") is True
                and prediction.get("stable") is True
            ):
                continue
            filtered.append(case)
        queue = filtered
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


def _headless_retail_matrix(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for entry in entries:
        primary = entry.get("primary_finding")
        if isinstance(primary, dict) and isinstance(primary.get("key"), str):
            headless_key = primary["key"]
        else:
            headless_key = "unknown"
        retail_classification = (
            entry.get("classification") if isinstance(entry.get("classification"), str) else "unknown"
        )
        group = grouped.setdefault(
            headless_key,
            {
                "headless_finding": headless_key,
                "cases": 0,
                "retail_classifications": Counter(),
                "examples": [],
            },
        )
        group["cases"] += 1
        group["retail_classifications"][retail_classification] += 1
        examples = group["examples"]
        if isinstance(examples, list) and len(examples) < 3:
            examples.append(
                {
                    "case_name": entry.get("case_name"),
                    "classification": retail_classification,
                    "artifact_dir": entry.get("artifact_dir"),
                }
            )
    rows: list[dict[str, object]] = []
    for key in sorted(grouped):
        group = grouped[key]
        classifications = group["retail_classifications"]
        rows.append(
            {
                "headless_finding": key,
                "cases": group["cases"],
                "retail_classifications": dict(sorted(classifications.items())),
                "examples": group["examples"],
            }
        )
    return rows


def _retail_signature_matrix(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for entry in entries:
        retail_signature_key = (
            entry.get("retail_signature_key")
            if isinstance(entry.get("retail_signature_key"), str)
            else entry.get("classification")
            if isinstance(entry.get("classification"), str)
            else "unknown"
        )
        group = grouped.setdefault(
            retail_signature_key,
            {
                "retail_signature_key": retail_signature_key,
                "cases": 0,
                "headless_findings": Counter(),
                "examples": [],
            },
        )
        group["cases"] += 1
        primary = entry.get("primary_finding")
        if isinstance(primary, dict) and isinstance(primary.get("key"), str):
            group["headless_findings"][primary["key"]] += 1
        else:
            group["headless_findings"]["unknown"] += 1
        examples = group["examples"]
        if isinstance(examples, list) and len(examples) < 3:
            examples.append(
                {
                    "case_name": entry.get("case_name"),
                    "classification": entry.get("classification"),
                    "artifact_dir": entry.get("artifact_dir"),
                }
            )
    rows: list[dict[str, object]] = []
    for key in sorted(grouped):
        group = grouped[key]
        rows.append(
            {
                "retail_signature_key": key,
                "cases": group["cases"],
                "headless_findings": dict(sorted(group["headless_findings"].items())),
                "examples": group["examples"],
            }
        )
    return rows


def _queue_options_dict(args: argparse.Namespace) -> dict[str, object]:
    return {
        "priority_order": args.priority_order,
        "interesting_only": args.interesting_only,
        "finding_kind": args.finding_kind,
        "max_per_finding": args.max_per_finding,
        "limit": args.limit,
        "skip_known_source": args.skip_known_source,
        "skip_known_finding": args.skip_known_finding,
        "skip_known_signature": args.skip_known_signature,
        "list_only": args.list_only,
    }


def _write_summary(
    *,
    summary_path: Path,
    artifact_dir: Path,
    results: list[Path],
    args: argparse.Namespace,
    history_files: list[str],
    history_case_count: int,
    queue_summary: list[dict[str, object]],
    entries: list[dict[str, object]],
    classifications: dict[str, int],
    stopped_early: bool,
    results_jsonl: str | None,
) -> None:
    summary = {
        "schema": "danmakufuzz-retail-batch-v1",
        "artifact_dir": str(artifact_dir),
        "results_jsonl": results_jsonl,
        "inputs": [str(path) for path in results],
        "queue_options": _queue_options_dict(args),
        "history": {
            "inputs": history_files,
            "cases_loaded": history_case_count,
        },
        "cases_selected": len(queue_summary),
        "cases_attempted": len(entries),
        "classifications": classifications,
        "stopped_early": stopped_early,
        "headless_retail_matrix": _headless_retail_matrix(entries),
        "retail_signature_matrix": _retail_signature_matrix(entries),
        "queue": queue_summary,
        "entries": entries,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main() -> int:
    args = parse_args()
    if not args.result and not args.from_minimized:
        raise ValueError("retail batch needs at least one --result or --from-minimized")

    results = _discover_results(args.result, args.from_minimized)
    if not results:
        raise ValueError("retail batch did not find any result.json / summary.json inputs")
    history, history_files = _load_history_index(args.history)
    queue = _select_queue_cases(results, args, history)

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

    queue_summary = [_queue_case_summary(case, history) for case in queue]
    if not queue:
        _write_summary(
            summary_path=summary_path,
            artifact_dir=artifact_dir,
            results=results,
            args=args,
            history_files=history_files,
            history_case_count=len(history.cases),
            queue_summary=queue_summary,
            entries=[],
            classifications={},
            stopped_early=False,
            results_jsonl=None,
        )
        return 0
    if args.list_only:
        _write_summary(
            summary_path=summary_path,
            artifact_dir=artifact_dir,
            results=results,
            args=args,
            history_files=history_files,
            history_case_count=len(history.cases),
            queue_summary=queue_summary,
            entries=[],
            classifications={},
            stopped_early=False,
            results_jsonl=None,
        )
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
            run_oracle = None
            wine_log = None
            if isinstance(report, dict):
                run = report.get("run")
                if isinstance(run, dict):
                    termination_reason = run.get("termination_reason")
                    run_oracle = run.get("oracle") if isinstance(run.get("oracle"), dict) else None
                    wine_log = run.get("wine_log") if isinstance(run.get("wine_log"), dict) else None
                    control = run.get("control")
                    if isinstance(control, dict):
                        oracle = control.get("oracle")
                        if isinstance(oracle, dict):
                            oracle_classification = oracle.get("classification")
                    if run_oracle is not None and isinstance(run_oracle.get("classification"), str):
                        oracle_classification = run_oracle.get("classification")
            classification = (
                str(termination_reason)
                if isinstance(termination_reason, str)
                else str(oracle_classification)
                if isinstance(oracle_classification, str)
                else "unknown"
            )
            primary_signature = (
                wine_log.get("primary_signature")
                if isinstance(wine_log, dict) and isinstance(wine_log.get("primary_signature"), str)
                else None
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
                "retail_signature_key": retail_signature_key(classification, primary_signature),
                "report_present": report_path.is_file(),
                "history": _history_summary_for_case(case, history),
            }
            if isinstance(run_oracle, dict):
                entry["retail_oracle"] = run_oracle
            if isinstance(wine_log, dict):
                entry["wine_log"] = {
                    "classification": wine_log.get("classification"),
                    "primary_signature": wine_log.get("primary_signature"),
                    "normalized_primary_signature": wine_log.get("normalized_primary_signature"),
                }
            entries.append(entry)
            lines.write(json.dumps(entry, sort_keys=True) + "\n")
            lines.flush()
            if classification in stop_set:
                stopped_early = True
                break

    _write_summary(
        summary_path=summary_path,
        artifact_dir=artifact_dir,
        results=results,
        args=args,
        history_files=history_files,
        history_case_count=len(history.cases),
        queue_summary=queue_summary,
        entries=entries,
        classifications=dict(sorted(classifications.items())),
        stopped_early=stopped_early,
        results_jsonl=str(lines_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
