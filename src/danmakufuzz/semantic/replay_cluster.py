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
    first_diff_line,
    load_json_object,
    load_trace_rows,
    sink_signature_from_records,
    trace_sha256,
)


DEFAULT_MEMBER_LIMIT = 8


@dataclass(frozen=True)
class ReplayCase:
    result_path: Path
    campaign_path: Path | None
    case_name: str
    source_kind: str
    mutant_name: str
    family: str
    site_key: str
    stage: int | None
    action_count: int
    runtime_seed: int | None
    runtime_difficulty: int | None
    runtime_character: int | None
    runtime_shot_type: int | None
    replay_difficulty: int | None
    replay_random_seed: int | None
    payload_sha256: str | None
    seed_source: str | None
    seed_replay: str | None
    classification: str
    error_type: str | None
    error_message: str | None
    interesting: bool
    returncode: int | None
    timed_out: bool
    trace_lines: int
    trace_sha256: str | None
    baseline_trace_sha256: str | None
    first_diff_line: int | None
    sink_signature: str | None
    sink_snapshot: dict[str, Any] | None
    sink_tick: int | None
    primary_finding_kind: str | None
    primary_finding_detail: str | None
    finding_keys: tuple[str, ...]

    @property
    def exact_cluster_key(self) -> str:
        if self.trace_sha256 is not None:
            return self.trace_sha256
        return (
            f"classification={self.classification}"
            f"|stage={self.stage}"
            f"|error_type={self.error_type}"
            f"|error_message={self.error_message}"
            f"|returncode={self.returncode}"
        )

    @property
    def sink_cluster_key(self) -> str:
        if self.classification != "runtime":
            return (
                f"classification={self.classification}"
                f"|stage={self.stage}"
                f"|error_type={self.error_type}"
                f"|error_message={self.error_message}"
            )
        return (
            f"stage={self.stage}|returncode={self.returncode}|timed_out={self.timed_out}"
            f"|trace_lines={self.trace_lines}|sink={self.sink_signature}"
        )

    @property
    def terminal_reason(self) -> str | None:
        if not isinstance(self.sink_snapshot, dict):
            return None
        value = self.sink_snapshot.get("terminal_reason")
        return value if isinstance(value, str) else None

    @property
    def sink_instruction_index(self) -> int | None:
        if not isinstance(self.sink_snapshot, dict):
            return None
        stage_vm = self.sink_snapshot.get("stage_vm")
        if not isinstance(stage_vm, dict):
            return None
        value = stage_vm.get("instruction_index")
        return value if isinstance(value, int) else None

    @property
    def pattern_cluster_key(self) -> str:
        return (
            f"stage={self.stage}|classification={self.classification}"
            f"|finding={self.primary_finding_kind}|family={self.family}|mutant={self.mutant_name}"
            f"|site={self.site_key}|returncode={self.returncode}|timed_out={self.timed_out}"
            f"|terminal={self.terminal_reason}|instruction_index={self.sink_instruction_index}"
            f"|first_diff={self.first_diff_line}"
        )

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.first_diff_line if self.first_diff_line is not None else 2**31 - 1,
            self.action_count,
            self.case_name,
            str(self.result_path),
        )


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "replay-clusters" / stamp


def _result_paths_from_summary_jsonl(path: Path) -> list[Path]:
    discovered: list[Path] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"replay summary entry is not an object: {path}:{line_number}")

            status = value.get("status")
            if isinstance(status, str) and status != "ran":
                continue

            case_name = value.get("case_name")
            if isinstance(case_name, str):
                result_path = (path.parent / case_name / "result.json").resolve()
                if not result_path.is_file():
                    raise FileNotFoundError(f"replay summary entry points to missing result.json: {result_path}")
                discovered.append(result_path)
                continue

            campaign = value.get("campaign")
            if isinstance(campaign, dict):
                nested_summary = campaign.get("summary")
                if isinstance(nested_summary, str):
                    discovered.extend(_result_paths_from_summary_jsonl(Path(nested_summary).resolve()))
                    continue

            raise ValueError(f"unsupported replay summary entry: {path}:{line_number}")
    return discovered


def discover_replay_results(result_args: list[Path], from_artifacts: bool) -> list[Path]:
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
                campaign = load_json_object(resolved)
                summary_path = campaign.get("summary")
                if not isinstance(summary_path, str):
                    raise ValueError(f"replay campaign.json is missing summary path: {resolved}")
                discovered.extend(_result_paths_from_summary_jsonl(Path(summary_path).resolve()))
                continue
            raise ValueError(f"unsupported replay cluster input file: {resolved}")
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("result.json")))
            continue
        raise FileNotFoundError(f"replay cluster input does not exist: {resolved}")
    if from_artifacts:
        discovered.extend(sorted((ARTIFACTS_DIR / "semantic-replay").glob("**/result.json")))
        discovered.extend(sorted((ARTIFACTS_DIR / "semantic-replay-corpus").glob("**/result.json")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


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


def _campaign_metadata(
    campaign_path: Path | None,
    cache: dict[Path, dict[str, object]],
) -> dict[str, object] | None:
    if campaign_path is None:
        return None
    resolved = campaign_path.resolve()
    cached = cache.get(resolved)
    if cached is not None:
        return cached
    if not resolved.is_file():
        cache[resolved] = {}
        return cache[resolved]
    loaded = load_json_object(resolved)
    cache[resolved] = loaded
    return loaded


def _sorted_present(values: set[object]) -> list[object]:
    present = [value for value in values if value is not None]
    return sorted(present, key=lambda value: (str(type(value)), str(value)))


def _case_summary(case: ReplayCase) -> dict[str, object]:
    return {
        "case_name": case.case_name,
        "result": str(case.result_path),
        "campaign": str(case.campaign_path) if case.campaign_path is not None else None,
        "source_kind": case.source_kind,
        "mutant_name": case.mutant_name,
        "family": case.family,
        "site_key": case.site_key,
        "stage": case.stage,
        "action_count": case.action_count,
        "runtime_seed": case.runtime_seed,
        "runtime_difficulty": case.runtime_difficulty,
        "runtime_character": case.runtime_character,
        "runtime_shot_type": case.runtime_shot_type,
        "replay_difficulty": case.replay_difficulty,
        "replay_random_seed": case.replay_random_seed,
        "payload_sha256": case.payload_sha256,
        "seed_source": case.seed_source,
        "seed_replay": case.seed_replay,
        "classification": case.classification,
        "error_type": case.error_type,
        "error_message": case.error_message,
        "returncode": case.returncode,
        "timed_out": case.timed_out,
        "trace_lines": case.trace_lines,
        "trace_sha256": case.trace_sha256,
        "baseline_trace_sha256": case.baseline_trace_sha256,
        "first_diff_line": case.first_diff_line,
        "sink_signature": case.sink_signature,
        "sink_tick": case.sink_tick,
        "primary_finding": {
            "kind": case.primary_finding_kind,
            "detail": case.primary_finding_detail,
        },
    }


def _load_case(path: Path, campaign_cache: dict[Path, dict[str, object]]) -> ReplayCase:
    data = load_json_object(path)
    case_name = data.get("case_name")
    source_kind = data.get("source")
    mutant_name = data.get("mutant_name")
    if not isinstance(case_name, str) or not isinstance(source_kind, str) or not isinstance(mutant_name, str):
        raise ValueError(f"replay result is missing case_name/source/mutant_name: {path}")

    metadata = data.get("mutation_metadata") if isinstance(data.get("mutation_metadata"), dict) else {}
    family = metadata.get("family") if isinstance(metadata.get("family"), str) else mutant_name.split("-", 1)[0]
    site_key = metadata.get("site_key") if isinstance(metadata.get("site_key"), str) else family
    classification = data.get("classification") if isinstance(data.get("classification"), str) else "runtime"

    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    run_a = data.get("run_a") if isinstance(data.get("run_a"), dict) else {}
    trace_path = Path(str(run_a.get("trace"))).resolve() if isinstance(run_a.get("trace"), str) else None
    trace_rows = load_trace_rows(trace_path) if trace_path is not None else []
    baseline_rows: list[dict[str, Any]] = []
    baseline_trace_path = baseline_trace_for_result(path)
    if baseline_trace_path is not None:
        baseline_rows = load_trace_rows(baseline_trace_path)
    trace_hash = trace_sha256(trace_path) if trace_path is not None else None
    baseline_trace_hash = trace_sha256(baseline_trace_path) if baseline_trace_path is not None else None
    sink_signature, sink_snapshot, sink_tick = sink_signature_from_records(trace_rows)

    campaign_path = campaign_path_for_result(path)
    campaign = _campaign_metadata(campaign_path, campaign_cache) or {}
    seed_runtime = campaign.get("seed_runtime") if isinstance(campaign.get("seed_runtime"), dict) else {}

    ordered_findings = _ordered_findings(data)
    primary = ordered_findings[0] if ordered_findings else (None, None)

    return ReplayCase(
        result_path=path.resolve(),
        campaign_path=campaign_path.resolve() if campaign_path is not None else None,
        case_name=case_name,
        source_kind=source_kind,
        mutant_name=mutant_name,
        family=family,
        site_key=site_key,
        stage=data.get("stage") if isinstance(data.get("stage"), int) else None,
        action_count=data.get("actions_count") if isinstance(data.get("actions_count"), int) else 0,
        runtime_seed=runtime.get("seed") if isinstance(runtime.get("seed"), int) else None,
        runtime_difficulty=runtime.get("difficulty") if isinstance(runtime.get("difficulty"), int) else None,
        runtime_character=runtime.get("character") if isinstance(runtime.get("character"), int) else None,
        runtime_shot_type=runtime.get("shot_type") if isinstance(runtime.get("shot_type"), int) else None,
        replay_difficulty=runtime.get("replay_difficulty") if isinstance(runtime.get("replay_difficulty"), int) else None,
        replay_random_seed=runtime.get("replay_random_seed")
        if isinstance(runtime.get("replay_random_seed"), int)
        else None,
        payload_sha256=data.get("payload_sha256") if isinstance(data.get("payload_sha256"), str) else None,
        seed_source=seed_runtime.get("source") if isinstance(seed_runtime.get("source"), str) else None,
        seed_replay=campaign.get("seed_replay") if isinstance(campaign.get("seed_replay"), str) else None,
        classification=classification,
        error_type=data.get("error_type") if isinstance(data.get("error_type"), str) else None,
        error_message=data.get("error_message") if isinstance(data.get("error_message"), str) else None,
        interesting=bool(data.get("interesting")),
        returncode=run_a.get("returncode") if isinstance(run_a.get("returncode"), int) else None,
        timed_out=bool(run_a.get("timed_out")),
        trace_lines=len(trace_rows),
        trace_sha256=trace_hash,
        baseline_trace_sha256=baseline_trace_hash,
        first_diff_line=first_diff_line(baseline_rows, trace_rows) if baseline_rows and trace_rows else None,
        sink_signature=sink_signature,
        sink_snapshot=coarse_sink_snapshot(trace_rows[-1]) if trace_rows else sink_snapshot,
        sink_tick=sink_tick,
        primary_finding_kind=primary[0],
        primary_finding_detail=primary[1],
        finding_keys=tuple(f"{kind}:{detail}" if detail else str(kind) for kind, detail in ordered_findings),
    )


def _representative_handoff(members: list[ReplayCase]) -> dict[str, object]:
    representative = min(members, key=lambda item: item.sort_key())
    return {
        "kind": "result-json",
        "path": str(representative.result_path),
        "mutant_name": representative.mutant_name,
        "family": representative.family,
        "site_key": representative.site_key,
        "seed_source": representative.seed_source,
    }


def _exact_cluster_summary(key: str, members: list[ReplayCase], *, member_limit: int) -> dict[str, object]:
    members_sorted = sorted(members, key=lambda item: item.sort_key())
    representative = members_sorted[0]
    return {
        "cluster_key": key,
        "cluster_kind": "exact-trace",
        "cases": len(members_sorted),
        "stage": representative.stage,
        "trace_sha256": representative.trace_sha256,
        "baseline_trace_sha256s": _sorted_present({case.baseline_trace_sha256 for case in members_sorted}),
        "trace_lines": representative.trace_lines,
        "returncode": representative.returncode,
        "timed_out": representative.timed_out,
        "classification": representative.classification,
        "sink_signature": representative.sink_signature,
        "sink_tick": representative.sink_tick,
        "sink_snapshot": representative.sink_snapshot,
        "source_kinds": _sorted_present({case.source_kind for case in members_sorted}),
        "families": _sorted_present({case.family for case in members_sorted}),
        "site_keys": _sorted_present({case.site_key for case in members_sorted}),
        "mutant_names": _sorted_present({case.mutant_name for case in members_sorted}),
        "seed_sources": _sorted_present({case.seed_source for case in members_sorted}),
        "runtime_seeds": _sorted_present({case.runtime_seed for case in members_sorted}),
        "replay_random_seeds": _sorted_present({case.replay_random_seed for case in members_sorted}),
        "first_diff_lines": _sorted_present({case.first_diff_line for case in members_sorted}),
        "finding_kinds": _sorted_present({case.primary_finding_kind for case in members_sorted}),
        "representative": _case_summary(representative),
        "preferred_handoff": _representative_handoff(members_sorted),
        "members": [_case_summary(case) for case in members_sorted[:member_limit]],
        "truncated_members": max(0, len(members_sorted) - member_limit),
    }


def _sink_cluster_summary(key: str, members: list[ReplayCase], *, member_limit: int) -> dict[str, object]:
    members_sorted = sorted(members, key=lambda item: item.sort_key())
    representative = members_sorted[0]
    return {
        "cluster_key": key,
        "cluster_kind": "coarse-sink",
        "cases": len(members_sorted),
        "stage": representative.stage,
        "classification": representative.classification,
        "returncode": representative.returncode,
        "timed_out": representative.timed_out,
        "trace_lines": representative.trace_lines,
        "sink_signature": representative.sink_signature,
        "sink_tick": representative.sink_tick,
        "sink_snapshot": representative.sink_snapshot,
        "trace_sha256s": _sorted_present({case.trace_sha256 for case in members_sorted}),
        "source_kinds": _sorted_present({case.source_kind for case in members_sorted}),
        "families": _sorted_present({case.family for case in members_sorted}),
        "site_keys": _sorted_present({case.site_key for case in members_sorted}),
        "mutant_names": _sorted_present({case.mutant_name for case in members_sorted}),
        "seed_sources": _sorted_present({case.seed_source for case in members_sorted}),
        "runtime_seeds": _sorted_present({case.runtime_seed for case in members_sorted}),
        "first_diff_lines": _sorted_present({case.first_diff_line for case in members_sorted}),
        "finding_kinds": _sorted_present({case.primary_finding_kind for case in members_sorted}),
        "representative": _case_summary(representative),
        "preferred_handoff": _representative_handoff(members_sorted),
        "members": [_case_summary(case) for case in members_sorted[:member_limit]],
        "truncated_members": max(0, len(members_sorted) - member_limit),
    }


def _pattern_cluster_summary(key: str, members: list[ReplayCase], *, member_limit: int) -> dict[str, object]:
    members_sorted = sorted(members, key=lambda item: item.sort_key())
    representative = members_sorted[0]
    return {
        "cluster_key": key,
        "cluster_kind": "mutation-pattern",
        "cases": len(members_sorted),
        "stage": representative.stage,
        "classification": representative.classification,
        "primary_finding_kind": representative.primary_finding_kind,
        "family": representative.family,
        "mutant_name": representative.mutant_name,
        "site_key": representative.site_key,
        "returncode": representative.returncode,
        "timed_out": representative.timed_out,
        "terminal_reason": representative.terminal_reason,
        "instruction_index": representative.sink_instruction_index,
        "first_diff_lines": _sorted_present({case.first_diff_line for case in members_sorted}),
        "trace_sha256s": _sorted_present({case.trace_sha256 for case in members_sorted}),
        "seed_sources": _sorted_present({case.seed_source for case in members_sorted}),
        "runtime_seeds": _sorted_present({case.runtime_seed for case in members_sorted}),
        "sink_signatures": _sorted_present({case.sink_signature for case in members_sorted}),
        "representative": _case_summary(representative),
        "preferred_handoff": _representative_handoff(members_sorted),
        "members": [_case_summary(case) for case in members_sorted[:member_limit]],
        "truncated_members": max(0, len(members_sorted) - member_limit),
    }


def build_replay_clusters(
    result_paths: list[Path],
    *,
    include_non_interesting: bool,
    member_limit: int,
) -> dict[str, object]:
    campaign_cache: dict[Path, dict[str, object]] = {}
    cases = [_load_case(path, campaign_cache) for path in result_paths]
    if not include_non_interesting:
        cases = [case for case in cases if case.interesting]

    exact_groups: dict[str, list[ReplayCase]] = defaultdict(list)
    sink_groups: dict[str, list[ReplayCase]] = defaultdict(list)
    pattern_groups: dict[str, list[ReplayCase]] = defaultdict(list)
    for case in cases:
        exact_groups[case.exact_cluster_key].append(case)
        sink_groups[case.sink_cluster_key].append(case)
        pattern_groups[case.pattern_cluster_key].append(case)

    exact_clusters = [
        _exact_cluster_summary(key, members, member_limit=member_limit)
        for key, members in exact_groups.items()
    ]
    sink_clusters = [
        _sink_cluster_summary(key, members, member_limit=member_limit)
        for key, members in sink_groups.items()
    ]
    pattern_clusters = [
        _pattern_cluster_summary(key, members, member_limit=member_limit)
        for key, members in pattern_groups.items()
    ]
    exact_clusters.sort(key=lambda row: (-int(row["cases"]), str(row["cluster_key"])))
    sink_clusters.sort(key=lambda row: (-int(row["cases"]), str(row["cluster_key"])))
    pattern_clusters.sort(key=lambda row: (-int(row["cases"]), str(row["cluster_key"])))

    campaign_paths = sorted(
        {
            str(candidate.resolve())
            for case in cases
            for candidate in [case.campaign_path]
            if candidate is not None
        }
    )
    return {
        "schema": "danmakufuzz-semantic-replay-clusters-v1",
        "cases": len(cases),
        "campaigns": campaign_paths,
        "exact_clusters": exact_clusters,
        "sink_clusters": sink_clusters,
        "pattern_clusters": pattern_clusters,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster replay semantic cases by exact trace and by coarse sink signature."
    )
    parser.add_argument(
        "--result",
        type=Path,
        action="append",
        default=[],
        help="replay result.json, summary.jsonl, campaign.json, or a directory to scan recursively",
    )
    parser.add_argument("--from-artifacts", action="store_true")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--include-non-interesting", action="store_true")
    parser.add_argument("--member-limit", type=int, default=DEFAULT_MEMBER_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.result and not args.from_artifacts:
        raise ValueError("replay clustering needs at least one --result or --from-artifacts")
    if args.member_limit <= 0:
        raise ValueError("member limit must be positive")

    result_paths = discover_replay_results(args.result, args.from_artifacts)
    if not result_paths:
        raise ValueError("replay clustering did not find any result.json inputs")

    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    payload = build_replay_clusters(
        result_paths,
        include_non_interesting=args.include_non_interesting,
        member_limit=args.member_limit,
    )
    output_path = artifact_dir / "summary.json"
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
