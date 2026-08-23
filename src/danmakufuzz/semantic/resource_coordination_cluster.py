from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ..repo import ARTIFACTS_DIR, ensure_directory
from .resource_coordination_common import (
    baseline_trace_for_result,
    campaign_path_for_result,
    coarse_sink_snapshot,
    discover_resource_results,
    first_diff_line,
    load_json_object,
    load_trace_rows,
    sink_signature_from_records,
    trace_sha256,
)


DEFAULT_MEMBER_LIMIT = 8
DEFAULT_MINIMIZED_LIMIT = 8


@dataclass(frozen=True)
class ResourceCase:
    result_path: Path
    case_name: str
    source_kind: str
    family: str
    mutant_name: str
    stage: int | None
    override_keys: tuple[str, ...]
    returncode: int | None
    timed_out: bool
    interesting: bool
    trace_lines: int
    trace_sha256: str | None
    first_diff_line: int | None
    sink_signature: str | None
    sink_snapshot: dict[str, Any] | None
    sink_tick: int | None
    primary_finding_kind: str | None
    primary_finding_detail: str | None
    finding_keys: tuple[str, ...]

    @property
    def override_count(self) -> int:
        return len(self.override_keys)

    @property
    def exact_cluster_key(self) -> str:
        return self.trace_sha256 or f"no-trace:returncode={self.returncode}:timed_out={self.timed_out}"

    @property
    def sink_cluster_key(self) -> str:
        return (
            f"stage={self.stage}|returncode={self.returncode}|timed_out={self.timed_out}"
            f"|trace_lines={self.trace_lines}|sink={self.sink_signature}"
        )

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.override_count,
            self.first_diff_line if self.first_diff_line is not None else 2**31 - 1,
            self.case_name,
            str(self.result_path),
        )


@dataclass(frozen=True)
class MinimizedResourceCase:
    summary_path: Path
    source_result: str
    minimized_override_count: int | None
    minimized_override_keys: tuple[str, ...]

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.minimized_override_count if self.minimized_override_count is not None else 2**31 - 1,
            len(self.minimized_override_keys),
            str(self.summary_path),
        )


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "resource-coordination-clusters" / stamp


def _finding_pair(value: object) -> tuple[str | None, str | None] | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    detail = value.get("detail")
    if not isinstance(kind, str):
        return None
    return kind, detail if isinstance(detail, str) else None


def _ordered_findings(data: dict[str, object]) -> list[tuple[str | None, str | None]]:
    findings = data.get("findings")
    if not isinstance(findings, list):
        return []
    ordered: list[tuple[str | None, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for item in findings:
        pair = _finding_pair(item)
        if pair is None or pair in seen:
            continue
        seen.add(pair)
        ordered.append(pair)
    return ordered


def _mutant_name(data: dict[str, object]) -> str:
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        family = metadata.get("family")
        if isinstance(family, str):
            if family == "anm-ecl":
                anm = metadata.get("anm_mutant_name")
                ecl = metadata.get("ecl_mutant_name")
                if isinstance(anm, str) and isinstance(ecl, str):
                    return f"{anm}__{ecl}"
            name = metadata.get("mutant_name")
            if isinstance(name, str):
                return name
    case_name = data.get("case_name")
    if isinstance(case_name, str):
        parts = case_name.split("-", 1)
        return parts[1] if len(parts) == 2 else case_name
    return "unknown"


def _load_minimized_index(minimized_dir: Path) -> dict[str, list[MinimizedResourceCase]]:
    index: dict[str, list[MinimizedResourceCase]] = defaultdict(list)
    if not minimized_dir.is_dir():
        return {}
    for path in sorted(minimized_dir.glob("*/summary.json")):
        data = load_json_object(path)
        if data.get("schema") != "danmakufuzz-resource-coordination-minimized-v1":
            continue
        source_result = data.get("source_result")
        if not isinstance(source_result, str):
            continue
        keys = data.get("minimized_override_keys")
        minimized = MinimizedResourceCase(
            summary_path=path.resolve(),
            source_result=source_result,
            minimized_override_count=data.get("minimized_override_count")
            if isinstance(data.get("minimized_override_count"), int)
            else None,
            minimized_override_keys=tuple(key for key in keys if isinstance(key, str)) if isinstance(keys, list) else (),
        )
        index[source_result].append(minimized)
    for values in index.values():
        values.sort(key=lambda item: item.sort_key())
    return dict(index)


def _load_case(path: Path) -> ResourceCase:
    data = load_json_object(path)
    case_name = data.get("case_name")
    source_kind = data.get("source")
    if not isinstance(case_name, str) or not isinstance(source_kind, str):
        raise ValueError(f"resource result is missing case_name/source: {path}")
    metadata = data.get("metadata")
    family = metadata.get("family") if isinstance(metadata, dict) and isinstance(metadata.get("family"), str) else source_kind
    trace_path = Path(str(data.get("trace"))).resolve() if isinstance(data.get("trace"), str) else None
    trace_rows = load_trace_rows(trace_path) if trace_path is not None else []
    baseline_rows = []
    baseline_trace = baseline_trace_for_result(path)
    if baseline_trace is not None:
        baseline_rows = load_trace_rows(baseline_trace)
    trace_hash = trace_sha256(trace_path) if trace_path is not None else None
    sink_signature, sink_snapshot, sink_tick = sink_signature_from_records(trace_rows)
    ordered_findings = _ordered_findings(data)
    primary = ordered_findings[0] if ordered_findings else (None, None)
    override_keys = data.get("override_keys")
    return ResourceCase(
        result_path=path.resolve(),
        case_name=case_name,
        source_kind=source_kind,
        family=family,
        mutant_name=_mutant_name(data),
        stage=data.get("stage") if isinstance(data.get("stage"), int) else None,
        override_keys=tuple(key for key in override_keys if isinstance(key, str)) if isinstance(override_keys, list) else (),
        returncode=data.get("returncode") if isinstance(data.get("returncode"), int) else None,
        timed_out=bool(data.get("timed_out")),
        interesting=bool(data.get("interesting")),
        trace_lines=data.get("trace_lines") if isinstance(data.get("trace_lines"), int) else len(trace_rows),
        trace_sha256=trace_hash,
        first_diff_line=first_diff_line(baseline_rows, trace_rows) if baseline_rows and trace_rows else None,
        sink_signature=sink_signature,
        sink_snapshot=sink_snapshot,
        sink_tick=sink_tick,
        primary_finding_kind=primary[0],
        primary_finding_detail=primary[1],
        finding_keys=tuple(f"{kind}:{detail}" if detail else str(kind) for kind, detail in ordered_findings),
    )


def _case_summary(case: ResourceCase) -> dict[str, object]:
    return {
        "case_name": case.case_name,
        "result": str(case.result_path),
        "source_kind": case.source_kind,
        "family": case.family,
        "mutant_name": case.mutant_name,
        "stage": case.stage,
        "override_keys": list(case.override_keys),
        "override_count": case.override_count,
        "returncode": case.returncode,
        "timed_out": case.timed_out,
        "trace_lines": case.trace_lines,
        "trace_sha256": case.trace_sha256,
        "first_diff_line": case.first_diff_line,
        "sink_signature": case.sink_signature,
        "sink_tick": case.sink_tick,
        "primary_finding": {
            "kind": case.primary_finding_kind,
            "detail": case.primary_finding_detail,
        },
    }


def _minimized_summary(case: MinimizedResourceCase) -> dict[str, object]:
    return {
        "summary": str(case.summary_path),
        "source_result": case.source_result,
        "minimized_override_count": case.minimized_override_count,
        "minimized_override_keys": list(case.minimized_override_keys),
    }


def _preferred_handoff(
    members: list[ResourceCase],
    minimized_index: dict[str, list[MinimizedResourceCase]],
) -> dict[str, object]:
    for case in sorted(members, key=lambda item: item.sort_key()):
        minimized = minimized_index.get(str(case.result_path), [])
        if minimized:
            best = minimized[0]
            return {
                "kind": "minimized-summary",
                "path": str(best.summary_path),
                "minimized_override_count": best.minimized_override_count,
                "source_result": best.source_result,
            }
    representative = min(members, key=lambda item: item.sort_key())
    return {
        "kind": "result-json",
        "path": str(representative.result_path),
        "override_count": representative.override_count,
    }


def _exact_cluster_summary(
    key: str,
    members: list[ResourceCase],
    minimized_index: dict[str, list[MinimizedResourceCase]],
    *,
    member_limit: int,
    minimized_limit: int,
) -> dict[str, object]:
    members_sorted = sorted(members, key=lambda item: item.sort_key())
    representative = members_sorted[0]
    minimized_matches: list[MinimizedResourceCase] = []
    for case in members_sorted:
        minimized_matches.extend(minimized_index.get(str(case.result_path), []))
    return {
        "cluster_key": key,
        "cluster_kind": "exact-trace",
        "cases": len(members_sorted),
        "stage": representative.stage,
        "trace_sha256": representative.trace_sha256,
        "trace_lines": representative.trace_lines,
        "returncode": representative.returncode,
        "timed_out": representative.timed_out,
        "sink_signatures": sorted({case.sink_signature for case in members_sorted}),
        "source_kinds": sorted({case.source_kind for case in members_sorted}),
        "families": sorted({case.family for case in members_sorted}),
        "mutant_names": sorted({case.mutant_name for case in members_sorted}),
        "first_diff_lines": sorted({case.first_diff_line for case in members_sorted}),
        "representative": _case_summary(representative),
        "preferred_handoff": _preferred_handoff(members_sorted, minimized_index),
        "members": [_case_summary(case) for case in members_sorted[:member_limit]],
        "truncated_members": max(0, len(members_sorted) - member_limit),
        "minimized": [_minimized_summary(item) for item in minimized_matches[:minimized_limit]],
        "truncated_minimized": max(0, len(minimized_matches) - minimized_limit),
    }


def _sink_cluster_summary(
    key: str,
    members: list[ResourceCase],
    minimized_index: dict[str, list[MinimizedResourceCase]],
    *,
    member_limit: int,
    minimized_limit: int,
) -> dict[str, object]:
    members_sorted = sorted(members, key=lambda item: item.sort_key())
    representative = members_sorted[0]
    minimized_matches: list[MinimizedResourceCase] = []
    for case in members_sorted:
        minimized_matches.extend(minimized_index.get(str(case.result_path), []))
    return {
        "cluster_key": key,
        "cluster_kind": "coarse-sink",
        "cases": len(members_sorted),
        "stage": representative.stage,
        "returncode": representative.returncode,
        "timed_out": representative.timed_out,
        "trace_lines": representative.trace_lines,
        "sink_signature": representative.sink_signature,
        "sink_tick": representative.sink_tick,
        "sink_snapshot": representative.sink_snapshot,
        "trace_sha256s": sorted({case.trace_sha256 for case in members_sorted}),
        "source_kinds": sorted({case.source_kind for case in members_sorted}),
        "families": sorted({case.family for case in members_sorted}),
        "mutant_names": sorted({case.mutant_name for case in members_sorted}),
        "first_diff_lines": sorted({case.first_diff_line for case in members_sorted}),
        "representative": _case_summary(representative),
        "preferred_handoff": _preferred_handoff(members_sorted, minimized_index),
        "members": [_case_summary(case) for case in members_sorted[:member_limit]],
        "truncated_members": max(0, len(members_sorted) - member_limit),
        "minimized": [_minimized_summary(item) for item in minimized_matches[:minimized_limit]],
        "truncated_minimized": max(0, len(minimized_matches) - minimized_limit),
    }


def build_resource_coordination_clusters(
    result_paths: list[Path],
    *,
    minimized_dir: Path,
    include_non_interesting: bool,
    member_limit: int,
    minimized_limit: int,
) -> dict[str, object]:
    cases = [_load_case(path) for path in result_paths]
    if not include_non_interesting:
        cases = [case for case in cases if case.interesting]
    minimized_index = _load_minimized_index(minimized_dir.resolve())

    exact_groups: dict[str, list[ResourceCase]] = defaultdict(list)
    sink_groups: dict[str, list[ResourceCase]] = defaultdict(list)
    for case in cases:
        exact_groups[case.exact_cluster_key].append(case)
        sink_groups[case.sink_cluster_key].append(case)

    exact_clusters = [
        _exact_cluster_summary(
            key,
            members,
            minimized_index,
            member_limit=member_limit,
            minimized_limit=minimized_limit,
        )
        for key, members in exact_groups.items()
    ]
    sink_clusters = [
        _sink_cluster_summary(
            key,
            members,
            minimized_index,
            member_limit=member_limit,
            minimized_limit=minimized_limit,
        )
        for key, members in sink_groups.items()
    ]
    exact_clusters.sort(key=lambda row: (-int(row["cases"]), str(row["cluster_key"])))
    sink_clusters.sort(key=lambda row: (-int(row["cases"]), str(row["cluster_key"])))

    campaign_paths = sorted(
        {
            str(candidate.resolve())
            for case in cases
            for candidate in [campaign_path_for_result(case.result_path)]
            if candidate is not None
        }
    )
    return {
        "schema": "danmakufuzz-resource-coordination-clusters-v1",
        "cases": len(cases),
        "campaigns": campaign_paths,
        "minimized_dir": str(minimized_dir.resolve()),
        "exact_clusters": exact_clusters,
        "sink_clusters": sink_clusters,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster coordinated resource runtime cases by exact trace and by coarse sink signature."
    )
    parser.add_argument(
        "--result",
        type=Path,
        action="append",
        default=[],
        help="resource result.json, summary.jsonl, campaign.json, or a directory to scan recursively",
    )
    parser.add_argument("--from-artifacts", action="store_true")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--minimized-dir", type=Path, default=ARTIFACTS_DIR / "resource-coordination-minimized")
    parser.add_argument("--include-non-interesting", action="store_true")
    parser.add_argument("--member-limit", type=int, default=DEFAULT_MEMBER_LIMIT)
    parser.add_argument("--minimized-limit", type=int, default=DEFAULT_MINIMIZED_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.result and not args.from_artifacts:
        raise ValueError("resource coordination clustering needs at least one --result or --from-artifacts")
    if args.member_limit <= 0 or args.minimized_limit <= 0:
        raise ValueError("member/minimized limits must be positive")
    result_paths = discover_resource_results(args.result, args.from_artifacts)
    if not result_paths:
        raise ValueError("resource coordination clustering did not find any result.json inputs")

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    payload = build_resource_coordination_clusters(
        result_paths,
        minimized_dir=args.minimized_dir,
        include_non_interesting=args.include_non_interesting,
        member_limit=args.member_limit,
        minimized_limit=args.minimized_limit,
    )
    output_path = artifact_dir / "summary.json"
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
