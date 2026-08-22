from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from ..repo import ARTIFACTS_DIR, ensure_directory


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
DEFAULT_MEMBER_LIMIT = 8
DEFAULT_MINIMIZED_LIMIT = 8


@dataclass(frozen=True)
class SemanticCase:
    result_path: Path
    case_name: str
    mutant_name: str
    source_kind: str
    primary_finding_kind: str | None
    primary_finding_detail: str | None
    finding_keys: tuple[str, ...]
    payload_size: int | None
    stage: int | None
    seed_name: str | None
    path_sub_index: int | None
    path_instruction_index: int | None
    returncode: int | None
    timed_out: bool
    interesting: bool

    @property
    def primary_finding_key(self) -> str:
        return _finding_key(self.primary_finding_kind, self.primary_finding_detail)

    @property
    def family_key(self) -> str:
        return f"{self.primary_finding_key}|{self.source_kind}"

    @property
    def cluster_key(self) -> str:
        return f"{self.family_key}|{self.mutant_name}"

    def representative_sort_key(self) -> tuple[object, ...]:
        return (
            self.payload_size if self.payload_size is not None else 2**63 - 1,
            self.path_sub_index if self.path_sub_index is not None else 2**31 - 1,
            self.path_instruction_index if self.path_instruction_index is not None else 2**31 - 1,
            self.case_name,
            str(self.result_path),
        )


@dataclass(frozen=True)
class MinimizedCase:
    summary_path: Path
    source_result: str
    target_kind: str | None
    target_detail: str | None
    minimized_size: int | None

    @property
    def target_key(self) -> str:
        return _finding_key(self.target_kind, self.target_detail)

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.minimized_size if self.minimized_size is not None else 2**63 - 1,
            str(self.summary_path),
        )


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-clusters" / stamp


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


def _payload_size_from_result(data: dict[str, object]) -> int | None:
    override_dir = data.get("override_dir")
    seed_name = data.get("seed_name")
    if isinstance(override_dir, str) and isinstance(seed_name, str):
        payload_path = Path(override_dir) / "data" / seed_name
        if payload_path.is_file():
            return payload_path.stat().st_size
    return None


def _load_result(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"semantic result is not an object: {path}")
    return value


def _load_semantic_case(path: Path) -> SemanticCase:
    data = _load_result(path)
    case_name = data.get("case_name")
    mutant_name = data.get("mutant_name")
    if not isinstance(case_name, str) or not isinstance(mutant_name, str):
        raise ValueError(f"semantic result is missing case_name/mutant_name: {path}")
    ordered_findings = _ordered_findings(data)
    primary = ordered_findings[0] if ordered_findings else (None, None)
    path_info = data.get("path")
    path_sub_index = None
    path_instruction_index = None
    if isinstance(path_info, dict):
        sub_index = path_info.get("sub_index")
        instruction_index = path_info.get("instruction_index")
        path_sub_index = sub_index if isinstance(sub_index, int) else None
        path_instruction_index = instruction_index if isinstance(instruction_index, int) else None
    source_value = data.get("source")
    source_kind = source_value if isinstance(source_value, str) else "targeted"
    return SemanticCase(
        result_path=path,
        case_name=case_name,
        mutant_name=mutant_name,
        source_kind=source_kind,
        primary_finding_kind=primary[0],
        primary_finding_detail=primary[1],
        finding_keys=tuple(_finding_key(kind, detail) for kind, detail in ordered_findings),
        payload_size=_payload_size_from_result(data),
        stage=data.get("stage") if isinstance(data.get("stage"), int) else None,
        seed_name=data.get("seed_name") if isinstance(data.get("seed_name"), str) else None,
        path_sub_index=path_sub_index,
        path_instruction_index=path_instruction_index,
        returncode=data.get("returncode") if isinstance(data.get("returncode"), int) else None,
        timed_out=bool(data.get("timed_out")),
        interesting=bool(data.get("interesting")),
    )


def _result_paths_from_summary_jsonl(path: Path) -> list[Path]:
    discovered: list[Path] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"summary.jsonl entry is not an object: {path}:{line_number}")
            case_name = value.get("case_name")
            if not isinstance(case_name, str):
                raise ValueError(f"summary.jsonl entry is missing case_name: {path}:{line_number}")
            result_path = (path.parent / case_name / "result.json").resolve()
            if not result_path.is_file():
                raise FileNotFoundError(f"summary.jsonl entry points to a missing result.json: {result_path}")
            discovered.append(result_path)
    return discovered


def _discover_results(result_args: list[Path], from_artifacts: bool) -> list[Path]:
    discovered: list[Path] = []
    for item in result_args:
        resolved = item.resolve()
        if resolved.is_file():
            if resolved.name == "result.json":
                discovered.append(resolved)
                continue
            if resolved.name == "summary.jsonl":
                discovered.extend(_result_paths_from_summary_jsonl(resolved))
                continue
            if resolved.name == "campaign.json":
                campaign = _load_result(resolved)
                summary_path = campaign.get("summary")
                if not isinstance(summary_path, str):
                    raise ValueError(f"campaign.json is missing summary path: {resolved}")
                discovered.extend(_result_paths_from_summary_jsonl(Path(summary_path).resolve()))
                continue
            raise ValueError(f"unsupported semantic cluster input file: {resolved}")
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("result.json")))
            continue
        raise FileNotFoundError(f"semantic cluster input does not exist: {resolved}")
    if from_artifacts:
        discovered.extend(sorted((ARTIFACTS_DIR / "semantic").glob("**/result.json")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _load_minimized_index(minimized_dir: Path) -> dict[str, list[MinimizedCase]]:
    index: dict[str, list[MinimizedCase]] = defaultdict(list)
    if not minimized_dir.is_dir():
        return {}
    for path in sorted(minimized_dir.glob("*/summary.json")):
        data = _load_result(path)
        source_result = data.get("source_result")
        if not isinstance(source_result, str):
            continue
        target = _finding_pair(data.get("target"))
        minimized_size = data.get("minimized_size")
        minimized = MinimizedCase(
            summary_path=path.resolve(),
            source_result=source_result,
            target_kind=target[0] if target is not None else None,
            target_detail=target[1] if target is not None else None,
            minimized_size=minimized_size if isinstance(minimized_size, int) else None,
        )
        index[source_result].append(minimized)
    for values in index.values():
        values.sort(key=lambda item: item.sort_key())
    return dict(index)


def _path_summary(case: SemanticCase) -> dict[str, object] | None:
    if case.path_sub_index is None and case.path_instruction_index is None:
        return None
    return {
        "sub_index": case.path_sub_index,
        "instruction_index": case.path_instruction_index,
    }


def _case_summary(case: SemanticCase) -> dict[str, object]:
    return {
        "case_name": case.case_name,
        "result": str(case.result_path),
        "mutant_name": case.mutant_name,
        "source_kind": case.source_kind,
        "primary_finding": {
            "kind": case.primary_finding_kind,
            "detail": case.primary_finding_detail,
            "key": case.primary_finding_key,
        },
        "payload_size": case.payload_size,
        "stage": case.stage,
        "seed_name": case.seed_name,
        "path": _path_summary(case),
        "returncode": case.returncode,
        "timed_out": case.timed_out,
    }


def _minimized_summary(case: MinimizedCase) -> dict[str, object]:
    return {
        "summary": str(case.summary_path),
        "source_result": case.source_result,
        "target": {
            "kind": case.target_kind,
            "detail": case.target_detail,
            "key": case.target_key,
        },
        "minimized_size": case.minimized_size,
    }


def _severity_for_finding(key: str) -> int:
    kind = key.split(":", 1)[0]
    return FINDING_SEVERITY.get(kind, 99)


def _choose_cluster_representative(
    members: list[SemanticCase],
    minimized_index: dict[str, list[MinimizedCase]],
) -> tuple[SemanticCase, MinimizedCase | None]:
    preferred_minimized: MinimizedCase | None = None
    preferred_case: SemanticCase | None = None
    for case in sorted(members, key=lambda item: item.representative_sort_key()):
        minimized = minimized_index.get(str(case.result_path), [])
        if minimized:
            if preferred_minimized is None or minimized[0].sort_key() < preferred_minimized.sort_key():
                preferred_minimized = minimized[0]
                preferred_case = case
    if preferred_case is not None:
        return preferred_case, preferred_minimized
    representative = min(members, key=lambda item: item.representative_sort_key())
    return representative, None


def _cluster_summary(
    *,
    cluster_key: str,
    family_key: str,
    members: list[SemanticCase],
    minimized_index: dict[str, list[MinimizedCase]],
    member_limit: int,
    minimized_limit: int,
) -> dict[str, object]:
    members_sorted = sorted(members, key=lambda item: item.representative_sort_key())
    representative, preferred_minimized = _choose_cluster_representative(members_sorted, minimized_index)
    minimized_matches: list[MinimizedCase] = []
    for case in members_sorted:
        minimized_matches.extend(minimized_index.get(str(case.result_path), []))
    unique_minimized: list[MinimizedCase] = []
    seen_minimized: set[Path] = set()
    for item in minimized_matches:
        if item.summary_path in seen_minimized:
            continue
        seen_minimized.add(item.summary_path)
        unique_minimized.append(item)
    payload_sizes = [case.payload_size for case in members_sorted if case.payload_size is not None]
    path_examples = [_path_summary(case) for case in members_sorted[:member_limit] if _path_summary(case) is not None]
    first = members_sorted[0]
    preferred_handoff = (
        {
            "kind": "minimized-summary",
            "path": str(preferred_minimized.summary_path),
            "minimized_size": preferred_minimized.minimized_size,
            "source_result": preferred_minimized.source_result,
        }
        if preferred_minimized is not None
        else {
            "kind": "result-json",
            "path": str(representative.result_path),
            "payload_size": representative.payload_size,
        }
    )
    return {
        "cluster_key": cluster_key,
        "family_key": family_key,
        "finding": {
            "kind": first.primary_finding_kind,
            "detail": first.primary_finding_detail,
            "key": first.primary_finding_key,
        },
        "source_kind": first.source_kind,
        "mutant_name": first.mutant_name,
        "cases": len(members_sorted),
        "cases_with_minimized": sum(1 for case in members_sorted if minimized_index.get(str(case.result_path))),
        "payload_size": {
            "min": min(payload_sizes) if payload_sizes else None,
            "max": max(payload_sizes) if payload_sizes else None,
            "unique_count": len(set(payload_sizes)),
            "unique_values": sorted(set(payload_sizes))[:member_limit] if payload_sizes else [],
        },
        "paths": {
            "count": sum(1 for case in members_sorted if _path_summary(case) is not None),
            "examples": path_examples,
        },
        "representative": _case_summary(representative),
        "preferred_handoff": preferred_handoff,
        "members": [_case_summary(case) for case in members_sorted[:member_limit]],
        "truncated_members": max(0, len(members_sorted) - member_limit),
        "minimized": [_minimized_summary(item) for item in unique_minimized[:minimized_limit]],
        "truncated_minimized": max(0, len(unique_minimized) - minimized_limit),
    }


def _clusters_payload(
    cases: list[SemanticCase],
    minimized_index: dict[str, list[MinimizedCase]],
    *,
    member_limit: int,
    minimized_limit: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_cluster: dict[str, list[SemanticCase]] = defaultdict(list)
    for case in cases:
        by_cluster[case.cluster_key].append(case)
    cluster_rows: list[dict[str, object]] = []
    for cluster_key, members in by_cluster.items():
        family_key = members[0].family_key
        cluster_rows.append(
            _cluster_summary(
                cluster_key=cluster_key,
                family_key=family_key,
                members=members,
                minimized_index=minimized_index,
                member_limit=member_limit,
                minimized_limit=minimized_limit,
            )
        )
    cluster_rows.sort(
        key=lambda row: (
            _severity_for_finding(str(row["finding"]["key"])),
            -int(row["cases"]),
            0 if row["preferred_handoff"]["kind"] == "minimized-summary" else 1,
            row["source_kind"],
            row["mutant_name"],
            row["cluster_key"],
        )
    )

    clusters_by_family: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in cluster_rows:
        clusters_by_family[str(row["family_key"])].append(row)
    family_rows: list[dict[str, object]] = []
    for family_key, clusters in clusters_by_family.items():
        first = clusters[0]
        preferred_cluster = max(
            clusters,
            key=lambda row: (
                1 if row["preferred_handoff"]["kind"] == "minimized-summary" else 0,
                int(row["cases"]),
                row["mutant_name"],
            ),
        )
        family_rows.append(
            {
                "family_key": family_key,
                "finding": first["finding"],
                "source_kind": first["source_kind"],
                "cases": sum(int(row["cases"]) for row in clusters),
                "clusters": len(clusters),
                "mutant_names": sorted(str(row["mutant_name"]) for row in clusters),
                "cluster_keys": [str(row["cluster_key"]) for row in clusters],
                "preferred_cluster_key": str(preferred_cluster["cluster_key"]),
            }
        )
    family_rows.sort(
        key=lambda row: (
            _severity_for_finding(str(row["finding"]["key"])),
            -int(row["cases"]),
            row["source_kind"],
            row["family_key"],
        )
    )
    return cluster_rows, family_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster semantic interesting cases into reviewable families before minimization/retail replay."
    )
    parser.add_argument(
        "--result",
        type=Path,
        action="append",
        default=[],
        help="semantic result.json, summary.jsonl, campaign.json, or a directory to scan recursively",
    )
    parser.add_argument(
        "--from-artifacts",
        action="store_true",
        help="append all artifacts/semantic/**/result.json cases",
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--minimized-dir", type=Path, default=ARTIFACTS_DIR / "semantic-minimized")
    parser.add_argument("--include-non-interesting", action="store_true")
    parser.add_argument("--member-limit", type=int, default=DEFAULT_MEMBER_LIMIT)
    parser.add_argument("--minimized-limit", type=int, default=DEFAULT_MINIMIZED_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.result and not args.from_artifacts:
        raise ValueError("semantic clustering needs at least one --result or --from-artifacts")
    if args.member_limit <= 0 or args.minimized_limit <= 0:
        raise ValueError("member/minimized limits must be positive")

    result_paths = _discover_results(args.result, args.from_artifacts)
    if not result_paths:
        raise ValueError("semantic clustering did not find any result.json inputs")
    cases = [_load_semantic_case(path) for path in result_paths]
    scanned_cases = len(cases)
    interesting_cases = [case for case in cases if case.interesting] if not args.include_non_interesting else cases
    minimized_index = _load_minimized_index(args.minimized_dir.resolve())

    clusters, families = _clusters_payload(
        interesting_cases,
        minimized_index,
        member_limit=args.member_limit,
        minimized_limit=args.minimized_limit,
    )

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    summary = {
        "schema": "danmakufuzz-semantic-clusters-v1",
        "artifact_dir": str(artifact_dir),
        "inputs": {
            "result_args": [str(path.resolve()) for path in args.result],
            "from_artifacts": args.from_artifacts,
            "discovered_results_count": len(result_paths),
            "discovered_results_examples": [str(path) for path in result_paths[:args.member_limit]],
        },
        "minimized_dir": str(args.minimized_dir.resolve()),
        "include_non_interesting": args.include_non_interesting,
        "cases_scanned": scanned_cases,
        "cases_considered": len(interesting_cases),
        "clusters": clusters,
        "families": families,
        "finding_counts": dict(sorted(Counter(case.primary_finding_key for case in interesting_cases).items())),
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
