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


@dataclass(frozen=True)
class QueueItem:
    result_path: Path
    case_name: str
    finding_key: str
    cluster_key: str | None
    family_key: str | None
    source_kind: str
    preferred_handoff_kind: str | None
    existing_minimized_summary: Path | None
    existing_minimized_source: str | None
    order_index: int

    @property
    def runnable(self) -> bool:
        return self.existing_minimized_summary is None

    def summary(self) -> dict[str, object]:
        return {
            "case_name": self.case_name,
            "result": str(self.result_path),
            "finding_key": self.finding_key,
            "cluster_key": self.cluster_key,
            "family_key": self.family_key,
            "source_kind": self.source_kind,
            "preferred_handoff_kind": self.preferred_handoff_kind,
            "existing_minimized_summary": (
                {
                    "path": str(self.existing_minimized_summary),
                    "source": self.existing_minimized_source,
                }
                if self.existing_minimized_summary is not None
                else None
            ),
            "runnable": self.runnable,
            "order_index": self.order_index,
        }


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-batch-minimize" / stamp


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json payload is not an object: {path}")
    return value


def _finding_key(finding: object) -> str:
    if not isinstance(finding, dict):
        return "unknown"
    kind = finding.get("kind")
    detail = finding.get("detail")
    if not isinstance(kind, str):
        return "unknown"
    return f"{kind}:{detail}" if isinstance(detail, str) and detail else kind


def _result_case_name(result_path: Path) -> str:
    return result_path.parent.name if result_path.name == "result.json" else result_path.stem


def _default_minimized_summary_for_result(result_path: Path) -> Path:
    return ARTIFACTS_DIR / "semantic-minimized" / result_path.parent.name / "summary.json"


def _discover_results(result_args: list[Path]) -> list[Path]:
    discovered: list[Path] = []
    for item in result_args:
        resolved = item.resolve()
        if resolved.is_file():
            if resolved.name != "result.json":
                raise ValueError(f"batch minimization direct --result must be a result.json: {resolved}")
            discovered.append(resolved)
            continue
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("result.json")))
            continue
        raise FileNotFoundError(f"batch minimization input does not exist: {resolved}")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _discover_cluster_summaries(cluster_args: list[Path]) -> list[Path]:
    discovered: list[Path] = []
    for item in cluster_args:
        resolved = item.resolve()
        if resolved.is_file():
            discovered.append(resolved)
            continue
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("summary.json")))
            continue
        raise FileNotFoundError(f"cluster summary input does not exist: {resolved}")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _queue_from_cluster_summary(path: Path) -> list[QueueItem]:
    data = _load_json(path)
    if data.get("schema") != "danmakufuzz-semantic-clusters-v1":
        raise ValueError(f"unsupported cluster summary schema: {path}")
    clusters = data.get("clusters")
    if not isinstance(clusters, list):
        raise ValueError(f"cluster summary is missing clusters: {path}")
    queue: list[QueueItem] = []
    for index, row in enumerate(clusters, start=1):
        if not isinstance(row, dict):
            continue
        representative = row.get("representative")
        preferred_handoff = row.get("preferred_handoff")
        finding = row.get("finding")
        if not isinstance(representative, dict):
            continue
        result_path_value = representative.get("result")
        case_name = representative.get("case_name")
        source_kind = row.get("source_kind")
        if (
            not isinstance(result_path_value, str)
            or not isinstance(case_name, str)
            or not isinstance(source_kind, str)
        ):
            continue
        result_path = Path(result_path_value).resolve()
        if not result_path.is_file():
            raise FileNotFoundError(f"cluster representative result.json is missing: {result_path}")
        existing_summary: Path | None = None
        existing_source: str | None = None
        preferred_kind = None
        if isinstance(preferred_handoff, dict):
            preferred_kind = preferred_handoff.get("kind") if isinstance(preferred_handoff.get("kind"), str) else None
            preferred_path = preferred_handoff.get("path")
            if preferred_kind == "minimized-summary" and isinstance(preferred_path, str):
                existing_summary = Path(preferred_path).resolve()
                existing_source = "cluster-preferred"
        if existing_summary is None:
            discovered_summary = _default_minimized_summary_for_result(result_path)
            if discovered_summary.is_file():
                existing_summary = discovered_summary.resolve()
                existing_source = "default-minimized-dir"
        queue.append(
            QueueItem(
                result_path=result_path,
                case_name=case_name,
                finding_key=_finding_key(finding),
                cluster_key=row.get("cluster_key") if isinstance(row.get("cluster_key"), str) else None,
                family_key=row.get("family_key") if isinstance(row.get("family_key"), str) else None,
                source_kind=source_kind,
                preferred_handoff_kind=preferred_kind,
                existing_minimized_summary=existing_summary,
                existing_minimized_source=existing_source,
                order_index=index,
            )
        )
    return queue


def _queue_from_direct_results(results: list[Path], offset: int) -> list[QueueItem]:
    queue: list[QueueItem] = []
    for index, result_path in enumerate(results, start=offset):
        data = _load_json(result_path)
        findings = data.get("findings")
        finding_key = "unknown"
        if isinstance(findings, list) and findings:
            finding_key = _finding_key(findings[0])
        source_value = data.get("source")
        existing_summary = _default_minimized_summary_for_result(result_path)
        queue.append(
            QueueItem(
                result_path=result_path,
                case_name=_result_case_name(result_path),
                finding_key=finding_key,
                cluster_key=None,
                family_key=None,
                source_kind=source_value if isinstance(source_value, str) else "direct-result",
                preferred_handoff_kind=None,
                existing_minimized_summary=existing_summary.resolve() if existing_summary.is_file() else None,
                existing_minimized_source="default-minimized-dir" if existing_summary.is_file() else None,
                order_index=index,
            )
        )
    return queue


def _select_queue(items: list[QueueItem], args: argparse.Namespace) -> list[QueueItem]:
    queue = list(items)
    if args.finding_kind:
        allowed = set(args.finding_kind)
        queue = [item for item in queue if item.finding_key.split(":", 1)[0] in allowed]
    if args.only_missing:
        queue = [item for item in queue if item.runnable]
    queue.sort(
        key=lambda item: (
            0 if item.runnable else 1,
            item.finding_key,
            item.source_kind,
            item.case_name,
            item.order_index,
        )
    )
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        queue = queue[:args.limit]
    return queue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the semantic minimizer over clustered representative cases."
    )
    parser.add_argument("--cluster-summary", type=Path, action="append", default=[])
    parser.add_argument("--result", type=Path, action="append", default=[])
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--finding-kind", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--game-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--max-evaluations", type=int)
    return parser.parse_args()


def _summary_payload(
    *,
    artifact_dir: Path,
    args: argparse.Namespace,
    cluster_inputs: list[str],
    direct_inputs: list[str],
    queue_items: list[QueueItem],
    entries: list[dict[str, object]],
) -> dict[str, object]:
    classifications = Counter(
        entry.get("status")
        for entry in entries
        if isinstance(entry.get("status"), str)
    )
    return {
        "schema": "danmakufuzz-semantic-batch-minimize-v1",
        "artifact_dir": str(artifact_dir),
        "inputs": {
            "cluster_summaries": cluster_inputs,
            "direct_results": direct_inputs,
        },
        "options": {
            "finding_kind": args.finding_kind,
            "limit": args.limit,
            "only_missing": args.only_missing,
            "dry_run": args.dry_run,
            "timeout_seconds": args.timeout_seconds,
            "max_evaluations": args.max_evaluations,
        },
        "cases_selected": len(queue_items),
        "cases_runnable": sum(1 for item in queue_items if item.runnable),
        "status_counts": dict(sorted(classifications.items())),
        "queue": [item.summary() for item in queue_items],
        "entries": entries,
    }


def main() -> int:
    args = parse_args()
    if not args.cluster_summary and not args.result:
        raise ValueError("batch minimization needs at least one --cluster-summary or --result")

    cluster_paths = _discover_cluster_summaries(args.cluster_summary)
    direct_results = _discover_results(args.result)
    queue_items: list[QueueItem] = []
    for cluster_path in cluster_paths:
        queue_items.extend(_queue_from_cluster_summary(cluster_path))
    queue_items.extend(_queue_from_direct_results(direct_results, offset=len(queue_items) + 1))
    queue_items = _select_queue(queue_items, args)

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    summary_path = artifact_dir / "summary.json"

    entries: list[dict[str, object]] = []
    if not args.dry_run:
        base_command = [sys.executable, "-m", "danmakufuzz.semantic.minimize_case"]
        if args.game_dir is not None:
            base_command.extend(["--game-dir", str(args.game_dir.resolve())])
        if args.timeout_seconds is not None:
            if args.timeout_seconds <= 0:
                raise ValueError("--timeout-seconds must be positive")
            base_command.extend(["--timeout-seconds", str(args.timeout_seconds)])
        if args.max_evaluations is not None:
            if args.max_evaluations <= 0:
                raise ValueError("--max-evaluations must be positive")
            base_command.extend(["--max-evaluations", str(args.max_evaluations)])

        for index, item in enumerate(queue_items, start=1):
            case_artifact_dir = artifact_dir / f"{index:04d}-{item.case_name}"
            if item.existing_minimized_summary is not None:
                entries.append(
                    {
                        **item.summary(),
                        "artifact_dir": str(case_artifact_dir),
                        "status": "existing-minimized",
                        "summary": str(item.existing_minimized_summary),
                    }
                )
                continue
            command = [
                *base_command,
                "--result",
                str(item.result_path),
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
            minimized_summary = case_artifact_dir / "summary.json"
            entries.append(
                {
                    **item.summary(),
                    "artifact_dir": str(case_artifact_dir),
                    "status": "ran-minimizer" if minimized_summary.is_file() and completed.returncode == 0 else "minimizer-failed",
                    "returncode": completed.returncode,
                    "stdout": str(stdout_path),
                    "summary": str(minimized_summary) if minimized_summary.is_file() else None,
                }
            )
    summary = _summary_payload(
        artifact_dir=artifact_dir,
        args=args,
        cluster_inputs=[str(path) for path in cluster_paths],
        direct_inputs=[str(path) for path in direct_results],
        queue_items=queue_items,
        entries=entries,
    )
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
