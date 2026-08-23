from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

from ..corpus.pbg3 import Pbg3Archive, sha256_bytes
from ..headless.actions import parse_actions_file
from ..headless.baseline import (
    DEFAULT_ACTION_FILE,
    DEFAULT_GAME_DIR,
    DEFAULT_TRACE_COMPACT_COUNTS,
    build_command,
    default_headless_binary,
)
from ..headless.overrides import materialize_override_bundle
from ..headless.prepare_worker_game_dir import prepare_worker_game_dir
from ..repo import ARTIFACTS_DIR, ensure_directory
from .anm import DEFAULT_ARCHIVE, AnmRawEntry, parse_anm
from .anm_campaign import evaluate_anm_payload


ENTRY_STAGE_KINDS = ("bg", "enm", "enm2")


@dataclass(frozen=True)
class AnmMetamorphicCase:
    name: str
    payload: bytes
    relation: str
    description: str
    sha256: str


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-anm-metamorphic-runtime" / stamp


def _entry_name(stage: int, kind: str) -> str:
    return f"stg{stage}{kind}.anm"


def _replace_u32(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<I", mutable, offset, value & 0xFFFFFFFF)
    return bytes(mutable)


def _script_table_bounds(payload: bytes) -> tuple[int, int, int] | None:
    if len(payload) < ctypes.sizeof(AnmRawEntry):
        return None
    entry = AnmRawEntry.from_buffer_copy(payload)
    num_sprites = int(entry.numSprites)
    num_scripts = int(entry.numScripts)
    if num_sprites < 0 or num_scripts < 2:
        return None
    script_table_offset = ctypes.sizeof(AnmRawEntry) + num_sprites * 4
    script_table_size = num_scripts * 8
    if script_table_offset + script_table_size > len(payload):
        return None
    return script_table_offset, num_scripts, script_table_size


def _script_rows(payload: bytes) -> list[tuple[int, int]]:
    bounds = _script_table_bounds(payload)
    if bounds is None:
        return []
    offset, count, _ = bounds
    return [
        struct.unpack_from("<II", payload, offset + index * 8)
        for index in range(count)
    ]


def _with_script_rows(payload: bytes, rows: list[tuple[int, int]]) -> bytes:
    bounds = _script_table_bounds(payload)
    if bounds is None:
        raise ValueError("ANM payload does not have a reorderable script table")
    offset, count, _ = bounds
    if len(rows) != count:
        raise ValueError("script row count drifted")
    mutable = bytearray(payload)
    for index, (script_id, script_offset) in enumerate(rows):
        struct.pack_into("<II", mutable, offset + index * 8, script_id, script_offset)
    return bytes(mutable)


def _case(name: str, payload: bytes, *, relation: str, description: str) -> AnmMetamorphicCase:
    return AnmMetamorphicCase(
        name=name,
        payload=payload,
        relation=relation,
        description=description,
        sha256=sha256_bytes(payload),
    )


def generate_anm_metamorphic_cases(seed_payload: bytes) -> list[AnmMetamorphicCase]:
    if len(seed_payload) < ctypes.sizeof(AnmRawEntry):
        raise ValueError("ANM seed payload is smaller than AnmRawEntry")
    cases = [
        _case(
            "header-unk1-pattern",
            _replace_u32(seed_payload, AnmRawEntry.unk1.offset, 0x5A5A5A5A),
            relation="anm-ignored-header-field-equivalence",
            description="Change header unk1 only; parsed resources and runtime behavior should stay equivalent.",
        ),
        _case(
            "header-unk2-pattern",
            _replace_u32(seed_payload, AnmRawEntry.unk2.offset, 0xA5A5A5A5),
            relation="anm-ignored-header-field-equivalence",
            description="Change header unk2 only; parsed resources and runtime behavior should stay equivalent.",
        ),
    ]
    rows = _script_rows(seed_payload)
    if len(rows) >= 2:
        swapped = list(rows)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        cases.append(
            _case(
                "script-table-swap-first-two",
                _with_script_rows(seed_payload, swapped),
                relation="anm-script-table-order-equivalence",
                description="Swap the first two script table rows without moving script bytecode.",
            )
        )
        cases.append(
            _case(
                "script-table-reverse",
                _with_script_rows(seed_payload, list(reversed(rows))),
                relation="anm-script-table-order-equivalence",
                description="Reverse script table row order without moving script bytecode.",
            )
        )
        by_id = sorted(rows, key=lambda row: (row[0], row[1]))
        if by_id != rows:
            cases.append(
                _case(
                    "script-table-sort-by-id",
                    _with_script_rows(seed_payload, by_id),
                    relation="anm-script-table-order-equivalence",
                    description="Sort script table rows by script id without moving script bytecode.",
                )
            )
        by_offset = sorted(rows, key=lambda row: (row[1], row[0]))
        if by_offset != rows:
            cases.append(
                _case(
                    "script-table-sort-by-offset",
                    _with_script_rows(seed_payload, by_offset),
                    relation="anm-script-table-order-equivalence",
                    description="Sort script table rows by script offset without moving script bytecode.",
                )
            )
    deduped: list[AnmMetamorphicCase] = []
    seen: set[tuple[str, str]] = set()
    for case in cases:
        key = (case.name, case.sha256)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(case)
    return deduped


def _trace_sha256(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _trace_line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _run_headless(
    *,
    binary: Path,
    game_dir: Path,
    stage: int,
    seed: int,
    actions: Path,
    trace: Path,
    log: Path,
    difficulty: int,
    character: int,
    shot_type: int,
    max_ticks: int,
    auto_shoot: bool,
    continue_after_hit: bool,
    trace_compact_counts: bool,
    override_dir: Path | None,
    timeout_seconds: float,
) -> dict[str, object]:
    command = build_command(
        binary=binary,
        game_dir=game_dir,
        stage=stage,
        seed=seed,
        actions=actions,
        trace=trace,
        difficulty=difficulty,
        character=character,
        shot_type=shot_type,
        max_ticks=max_ticks,
        auto_shoot=auto_shoot,
        continue_after_hit=continue_after_hit,
        trace_compact_counts=trace_compact_counts,
    )
    env = os.environ.copy()
    if override_dir is not None:
        env["DANMAKUFUZZ_OVERRIDE_DIR"] = str(override_dir.resolve())
    ensure_directory(trace.parent)
    started = time.time()
    timed_out = False
    try:
        with log.open("w", encoding="utf-8") as log_handle:
            completed = subprocess.run(
                command,
                cwd=game_dir,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = None
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": time.time() - started,
        "trace": str(trace.resolve()),
        "trace_sha256": _trace_sha256(trace),
        "trace_lines": _trace_line_count(trace),
        "log": str(log.resolve()),
    }


def _selected_entries(archive: Pbg3Archive, *, stage: int, entries: list[str]) -> list[tuple[str, bytes]]:
    names = entries or [_entry_name(stage, kind) for kind in ENTRY_STAGE_KINDS]
    selected: list[tuple[str, bytes]] = []
    for entry_name in names:
        try:
            selected.append((entry_name, archive.extract(entry_name)))
        except KeyError:
            continue
    if not selected:
        raise RuntimeError(f"no ANM entries selected for stage {stage}: {names}")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ANM metamorphic runtime equivalence checks through th06-headless."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", action="append", default=[])
    parser.add_argument("--stage", type=int, default=6)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_FILE)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--character", type=int, default=0)
    parser.add_argument("--shot-type", type=int, default=0)
    parser.add_argument("--max-ticks", type=int, default=1200)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.set_defaults(auto_shoot=True)
    parser.add_argument("--continue-after-hit", action="store_true")
    parser.add_argument("--trace-compact-counts", dest="trace_compact_counts", action="store_true")
    parser.add_argument("--full-entity-trace", dest="trace_compact_counts", action="store_false")
    parser.set_defaults(trace_compact_counts=DEFAULT_TRACE_COMPACT_COUNTS)
    parser.add_argument("--name-filter", action="append", default=[])
    parser.add_argument("--emit-cases", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    source_game_dir = args.game_dir.resolve()
    binary = args.headless_bin.resolve()
    actions = args.actions.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing ANM archive: {archive_path}")
    if not source_game_dir.is_dir():
        raise FileNotFoundError(f"missing game dir: {source_game_dir}")
    if not binary.is_file():
        raise FileNotFoundError(f"missing headless binary: {binary}")
    parse_actions_file(actions)
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    worker_game_dir = artifact_dir / "worker-game"
    if worker_game_dir.exists():
        shutil.rmtree(worker_game_dir)
    prepare_worker_game_dir(
        source_game_dir=source_game_dir,
        destination=worker_game_dir,
        worker_name=f"anm-metamorphic-stage{args.stage}",
        reuse=False,
    )
    baseline_dir = artifact_dir / "_baseline"
    baseline = _run_headless(
        binary=binary,
        game_dir=worker_game_dir,
        stage=args.stage,
        seed=args.seed,
        actions=actions,
        trace=baseline_dir / "trace.jsonl",
        log=baseline_dir / "run.log",
        difficulty=args.difficulty,
        character=args.character,
        shot_type=args.shot_type,
        max_ticks=args.max_ticks,
        auto_shoot=args.auto_shoot,
        continue_after_hit=args.continue_after_hit,
        trace_compact_counts=args.trace_compact_counts,
        override_dir=None,
        timeout_seconds=args.timeout_seconds,
    )
    if baseline["returncode"] != 0 or baseline["timed_out"]:
        raise RuntimeError(f"baseline did not complete cleanly: {baseline}")

    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    selected_entries = _selected_entries(archive, stage=args.stage, entries=args.entry)
    summary_path = artifact_dir / "summary.jsonl"
    relation_counts: Counter[str] = Counter()
    violation_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    cases_generated = 0
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for entry_name, seed_payload in selected_entries:
            entry_baseline_summary = parse_anm(seed_payload)
            cases = generate_anm_metamorphic_cases(seed_payload)
            if args.name_filter:
                cases = [
                    case
                    for case in cases
                    if any(name_filter in case.name for name_filter in args.name_filter)
                ]
            for case_index, case in enumerate(cases, start=1):
                cases_generated += 1
                case_name = f"{entry_name}-{case_index:04d}-{case.name}"
                case_dir = artifact_dir / case_name
                ensure_directory(case_dir)
                override_dir = materialize_override_bundle(case_dir, {entry_name: case.payload})
                parser_evaluation = evaluate_anm_payload(
                    case.payload,
                    entry_baseline_summary,
                    max_script_instructions=4096,
                )
                run = _run_headless(
                    binary=binary,
                    game_dir=worker_game_dir,
                    stage=args.stage,
                    seed=args.seed,
                    actions=actions,
                    trace=case_dir / "trace.jsonl",
                    log=case_dir / "run.log",
                    difficulty=args.difficulty,
                    character=args.character,
                    shot_type=args.shot_type,
                    max_ticks=args.max_ticks,
                    auto_shoot=args.auto_shoot,
                    continue_after_hit=args.continue_after_hit,
                    trace_compact_counts=args.trace_compact_counts,
                    override_dir=override_dir,
                    timeout_seconds=args.timeout_seconds,
                )
                relation_holds = (
                    run["returncode"] == baseline["returncode"]
                    and run["timed_out"] == baseline["timed_out"]
                    and run["trace_sha256"] == baseline["trace_sha256"]
                    and run["trace_lines"] == baseline["trace_lines"]
                )
                violation_kind = None if relation_holds else "runtime-trace-drift"
                relation_counts["holds" if relation_holds else "violated"] += 1
                if violation_kind is not None:
                    violation_counts[violation_kind] += 1
                classification_counts["equivalent" if relation_holds else "runtime-drift"] += 1
                result = {
                    "schema": "danmakufuzz-anm-metamorphic-runtime-case-v1",
                    "case_name": case_name,
                    "entry_name": entry_name,
                    "stage": args.stage,
                    "mutant_name": case.name,
                    "relation": case.relation,
                    "description": case.description,
                    "payload_sha256": case.sha256,
                    "payload_size": len(case.payload),
                    "override_dir": str(override_dir.resolve()),
                    "parser_evaluation": {
                        "classification": parser_evaluation.get("classification"),
                        "equivalent_to_baseline": parser_evaluation.get("equivalent_to_baseline"),
                        "changed_fields": parser_evaluation.get("changed_fields"),
                    },
                    "baseline": baseline,
                    "run": run,
                    "relation_holds": relation_holds,
                    "metamorphic_violation": not relation_holds,
                    "violation_kind": violation_kind,
                }
                (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                summary_handle.write(json.dumps(result) + "\n")
                if args.emit_cases:
                    print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-anm-metamorphic-runtime-campaign-v1",
        "artifact_dir": str(artifact_dir),
        "archive": str(archive_path),
        "stage": args.stage,
        "entries": [entry_name for entry_name, _ in selected_entries],
        "baseline": baseline,
        "cases_generated": cases_generated,
        "relation_counts": dict(sorted(relation_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "violation_counts": dict(sorted(violation_counts.items())),
        "summary": str(summary_path.resolve()),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if violation_counts else 0


if __name__ == "__main__":
    raise SystemExit(main())
