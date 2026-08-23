from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time

from ..corpus.pbg3 import Pbg3Archive
from ..headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    DEFAULT_TRACE_COMPACT_COUNTS,
    build_command,
    default_headless_binary,
    run_baseline,
)
from ..headless.overrides import materialize_override_bundle, stage_active_override_bundle
from ..interestingness.rules import Finding, load_trace_records, score_trace_path_with_baseline
from ..parser.anm import DEFAULT_ARCHIVE, parse_anm
from ..parser.anm_campaign import evaluate_anm_payload
from ..parser.anm_mutants import AnmMutant, generate_anm_mutants
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .resource_coordination_cluster import build_resource_coordination_clusters
from .resource_coordination_common import first_diff_line, sink_signature_from_records, trace_sha256
from .ecl_campaign import classify_process_result
from .payload_mutants import PayloadMutant, generate_payload_mutants


ENTRY_STAGE_RE = re.compile(r"^stg(?P<stage>\d+)(?P<kind>bg|enm(?:\d+)?)\.anm$", re.IGNORECASE)
DEFAULT_TRIAD_MUTANTS = (
    "first-sprite-offset-zero",
    "first-script-id-ffff",
    "first-script-offset-zero",
    "first-instr-opcode-255",
)
DEFAULT_ECL_FAMILY_FILTERS = (
    "generic-opcode",
    "generic-arg16",
    "generic-arg32-cross",
    "timeline-time",
    "instruction-time",
)


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-resource-coordination" / stamp


def _trace_line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _default_seed_ecl(stage: int) -> Path:
    return REFERENCE_DIR / "corpus" / "ecl" / "original" / f"ecldata{stage}.ecl"


def _entry_name(stage: int, kind: str) -> str:
    return f"stg{stage}{kind}.anm"


def _finding_records(findings: list[Finding]) -> list[dict[str, str]]:
    return [{"kind": finding.kind, "detail": finding.detail} for finding in findings]


def _select_entry_payloads(archive: Pbg3Archive, *, stage: int) -> dict[str, bytes]:
    selected: dict[str, bytes] = {}
    for kind in ("bg", "enm", "enm2"):
        entry_name = _entry_name(stage, kind)
        try:
            selected[entry_name] = archive.extract(entry_name)
        except KeyError:
            continue
    if not selected:
        raise RuntimeError(f"archive does not contain any stage {stage} ANM runtime entries")
    return selected


def _accepted_anm_mutants_by_name(payload: bytes) -> dict[str, AnmMutant]:
    baseline_summary = parse_anm(payload, max_script_instructions=4096)
    accepted: dict[str, AnmMutant] = {}
    for mutant in generate_anm_mutants(payload):
        evaluation = evaluate_anm_payload(mutant.payload, baseline_summary, max_script_instructions=4096)
        if evaluation["classification"] != "accepted":
            continue
        if not bool(evaluation.get("interesting")):
            continue
        accepted[mutant.name] = mutant
    return accepted


def _triad_cases(entry_payloads: dict[str, bytes]) -> list[dict[str, object]]:
    accepted_by_entry = {
        entry_name: _accepted_anm_mutants_by_name(payload)
        for entry_name, payload in entry_payloads.items()
    }
    cases: list[dict[str, object]] = []
    for mutant_name in DEFAULT_TRIAD_MUTANTS:
        payloads: dict[str, bytes] = {}
        entries: list[str] = []
        for entry_name, accepted in accepted_by_entry.items():
            mutant = accepted.get(mutant_name)
            if mutant is None:
                continue
            payloads[entry_name] = mutant.payload
            entries.append(entry_name)
        if len(payloads) < 2:
            continue
        cases.append(
            {
                "name": f"anm-triad-{mutant_name}",
                "source": "anm-triad",
                "override_payloads": payloads,
                "metadata": {
                    "family": "anm-triad",
                    "mutant_name": mutant_name,
                    "entries": entries,
                },
            }
        )
    return cases


def _select_ecl_mutants(
    seed_payload: bytes,
    *,
    random_seed: int,
    samples_per_site: int,
    limit: int,
    family_filters: tuple[str, ...],
) -> list[PayloadMutant]:
    mutants = generate_payload_mutants(
        seed_payload,
        include_structural=False,
        mutation_mode="exploration",
        random_seed=random_seed,
        samples_per_site=samples_per_site,
        family_filters=family_filters,
    )
    return mutants[:limit]


def _anm_ecl_cases(
    *,
    stage: int,
    entry_payloads: dict[str, bytes],
    ecl_seed_payload: bytes,
    random_seed: int,
    samples_per_site: int,
    ecl_limit: int,
    family_filters: tuple[str, ...],
) -> list[dict[str, object]]:
    accepted_by_entry = {
        entry_name: _accepted_anm_mutants_by_name(payload)
        for entry_name, payload in entry_payloads.items()
    }
    anchors: list[tuple[str, str, bytes]] = []
    for mutant_name in DEFAULT_TRIAD_MUTANTS:
        for preferred_kind in ("enm", "enm2", "bg"):
            entry_name = _entry_name(stage, preferred_kind)
            accepted = accepted_by_entry.get(entry_name)
            if accepted is None:
                continue
            mutant = accepted.get(mutant_name)
            if mutant is None:
                continue
            anchors.append((entry_name, mutant_name, mutant.payload))
            break
    if not anchors:
        return []
    ecl_mutants = _select_ecl_mutants(
        ecl_seed_payload,
        random_seed=random_seed,
        samples_per_site=samples_per_site,
        limit=ecl_limit,
        family_filters=family_filters,
    )
    cases: list[dict[str, object]] = []
    seed_name = f"ecldata{stage}.ecl"
    for index, ecl_mutant in enumerate(ecl_mutants):
        entry_name, mutant_name, payload = anchors[index % len(anchors)]
        cases.append(
            {
                "name": f"anm-ecl-{Path(entry_name).stem}-{mutant_name}__{ecl_mutant.name}",
                "source": "anm-ecl",
                "override_payloads": {
                    entry_name: payload,
                    seed_name: ecl_mutant.payload,
                },
                "metadata": {
                    "family": "anm-ecl",
                    "anm_entry": entry_name,
                    "anm_mutant_name": mutant_name,
                    "ecl_mutant_name": ecl_mutant.name,
                    "ecl_source": ecl_mutant.source,
                    "ecl_metadata": ecl_mutant.metadata,
                },
            }
        )
    return cases


def _run_case(
    *,
    artifact_dir: Path,
    case_index: int,
    case: dict[str, object],
    binary: Path,
    game_dir: Path,
    stage: int,
    seed: int,
    action_file: Path,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    timeout_seconds: float,
    trace_compact_counts: bool,
    baseline_records: list[dict[str, object]],
) -> dict[str, object]:
    case_name = f"{case_index:04d}-{case['name']}"
    case_dir = artifact_dir / case_name
    ensure_directory(case_dir)
    override_payloads = dict(case["override_payloads"])
    override_dir = materialize_override_bundle(case_dir, override_payloads)
    active_override_dir = stage_active_override_bundle(
        game_dir,
        override_payloads,
        namespace=f"resource-coordination-stage{stage}",
    )
    trace_path = case_dir / "trace.jsonl"
    log_path = case_dir / "run.log"
    command = build_command(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        actions=action_file,
        trace=trace_path,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        trace_compact_counts=trace_compact_counts,
    )
    run_env = dict(os.environ)
    run_env["DANMAKUFUZZ_OVERRIDE_DIR"] = str(active_override_dir.resolve())
    started_at = time.time()
    returncode: int | None = None
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log_handle:
        try:
            completed = subprocess.run(
                command,
                cwd=game_dir,
                env=run_env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    elapsed_seconds = time.time() - started_at

    findings = classify_process_result(returncode, timed_out=timed_out)
    if trace_path.is_file() and trace_path.stat().st_size > 0:
        findings.extend(score_trace_path_with_baseline(trace_path, baseline_records=baseline_records))
    elif not findings:
        findings.append(Finding("empty-trace", "headless run finished without a non-empty trace"))
    trace_records = load_trace_records(trace_path) if trace_path.is_file() and trace_path.stat().st_size > 0 else []
    sink_signature, sink_snapshot, sink_tick = sink_signature_from_records(trace_records)
    result = {
        "case_name": case_name,
        "source": case["source"],
        "metadata": case["metadata"],
        "override_keys": sorted(override_payloads),
        "command": command,
        "cwd": str(game_dir.resolve()),
        "stage": stage,
        "seed": seed,
        "elapsed_seconds": elapsed_seconds,
        "returncode": returncode,
        "timed_out": timed_out,
        "trace": str(trace_path.resolve()),
        "trace_lines": _trace_line_count(trace_path),
        "trace_sha256": trace_sha256(trace_path),
        "first_diff_line": first_diff_line(baseline_records, trace_records) if trace_records else None,
        "sink_signature": sink_signature,
        "sink_snapshot": sink_snapshot,
        "sink_tick": sink_tick,
        "log": str(log_path.resolve()),
        "override_dir": str(override_dir.resolve()),
        "active_override_dir": str(active_override_dir.resolve()),
        "override_payload_sizes": {key: len(payload) for key, payload in sorted(override_payloads.items())},
        "findings": _finding_records(findings),
        "finding_kinds": [finding.kind for finding in findings],
        "interesting": bool(findings),
    }
    result_path = case_dir / "result.json"
    result["result_path"] = str(result_path.resolve())
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run coordinated runtime mutation campaigns over stage ANM bundles and ANM+ECL pairs."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--seed-ecl", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--stage", type=int, default=7)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--max-ticks", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--mode", choices=("anm-triad", "anm-ecl", "all"), default="all")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--trace-compact-counts", dest="trace_compact_counts", action="store_true")
    parser.add_argument("--full-entity-trace", dest="trace_compact_counts", action="store_false")
    parser.set_defaults(trace_compact_counts=DEFAULT_TRACE_COMPACT_COUNTS)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--samples-per-site", type=int, default=1)
    parser.add_argument("--ecl-limit", type=int, default=4)
    parser.add_argument("--ecl-family-filter", action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    archive_path = args.archive.resolve()
    game_dir = args.game_dir.resolve()
    binary = args.headless_bin.resolve()
    actions = args.actions.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing archive: {archive_path}")
    if not game_dir.is_dir():
        raise FileNotFoundError(f"missing game directory: {game_dir}")
    if not binary.is_file():
        raise FileNotFoundError(f"missing headless binary: {binary}")

    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    entry_payloads = _select_entry_payloads(archive, stage=args.stage)
    ecl_path = (args.seed_ecl.resolve() if args.seed_ecl is not None else _default_seed_ecl(args.stage).resolve())
    if not ecl_path.is_file():
        raise FileNotFoundError(f"missing stage ECL seed: {ecl_path}")
    ecl_seed_payload = ecl_path.read_bytes()

    baseline_dir = artifact_dir / "_baseline"
    baseline_metadata = run_baseline(
        binary=binary,
        game_dir=game_dir,
        resource_override_dir=None,
        stage=args.stage,
        seed=args.seed,
        action_file=actions,
        artifact_dir=baseline_dir,
        difficulty=args.difficulty,
        character=args.character,
        shot_type=args.shot_type,
        max_ticks=args.max_ticks,
        auto_shoot=args.auto_shoot,
        continue_after_hit=args.continue_after_hit,
        trace_compact_counts=args.trace_compact_counts,
        log_path=baseline_dir / "run.log",
        dry_run=False,
    )
    baseline_trace = Path(str(baseline_metadata["trace"]))
    baseline_records = load_trace_records(baseline_trace)

    cases: list[dict[str, object]] = []
    if args.mode in ("anm-triad", "all"):
        cases.extend(_triad_cases(entry_payloads))
    if args.mode in ("anm-ecl", "all"):
        cases.extend(
            _anm_ecl_cases(
                stage=args.stage,
                entry_payloads=entry_payloads,
                ecl_seed_payload=ecl_seed_payload,
                random_seed=args.random_seed,
                samples_per_site=args.samples_per_site,
                ecl_limit=args.ecl_limit,
                family_filters=tuple(args.ecl_family_filter or DEFAULT_ECL_FAMILY_FILTERS),
            )
        )
    if args.limit is not None:
        cases = cases[: args.limit]

    summary_path = artifact_dir / "summary.jsonl"
    interesting_cases = 0
    finding_kind_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        result_paths: list[Path] = []
        for case_index, case in enumerate(cases, start=1):
            result = _run_case(
                artifact_dir=artifact_dir,
                case_index=case_index,
                case=case,
                binary=binary,
                game_dir=game_dir,
                stage=args.stage,
                seed=args.seed,
                action_file=actions,
                difficulty=args.difficulty,
                character=args.character,
                shot_type=args.shot_type,
                max_ticks=args.max_ticks,
                auto_shoot=args.auto_shoot,
                continue_after_hit=args.continue_after_hit,
                timeout_seconds=args.timeout_seconds,
                trace_compact_counts=args.trace_compact_counts,
                baseline_records=baseline_records,
            )
            interesting_cases += int(bool(result["interesting"]))
            source_counts[str(result["source"])] += 1
            for finding_kind in result["finding_kinds"]:
                finding_kind_counts[str(finding_kind)] += 1
            summary_handle.write(json.dumps(result) + "\n")
            result_paths.append(Path(str(result["result_path"])).resolve())
            print(json.dumps(result, ensure_ascii=False))

    clusters_path = artifact_dir / "clusters.json"
    clusters_payload = build_resource_coordination_clusters(
        result_paths,
        minimized_dir=ARTIFACTS_DIR / "resource-coordination-minimized",
        include_non_interesting=False,
        member_limit=8,
        minimized_limit=8,
    )
    clusters_path.write_text(json.dumps(clusters_payload, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema": "danmakufuzz-semantic-resource-coordination-v1",
        "archive": str(archive_path),
        "seed_ecl": str(ecl_path),
        "stage": args.stage,
        "seed": args.seed,
        "difficulty": args.difficulty,
        "character": args.character,
        "shot_type": args.shot_type,
        "mode": args.mode,
        "case_count": len(cases),
        "interesting_cases": interesting_cases,
        "source_counts": dict(sorted(source_counts.items())),
        "finding_kind_counts": dict(sorted(finding_kind_counts.items())),
        "summary": str(summary_path.resolve()),
        "clusters": str(clusters_path.resolve()),
        "baseline": baseline_metadata,
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
