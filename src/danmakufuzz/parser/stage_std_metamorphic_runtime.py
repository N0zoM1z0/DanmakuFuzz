from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
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
    DEFAULT_GAME_DIR,
    DEFAULT_TRACE_COMPACT_COUNTS,
    build_command,
    default_headless_binary,
)
from ..headless.overrides import materialize_override_bundle
from ..headless.prepare_worker_game_dir import prepare_worker_game_dir
from ..repo import ARTIFACTS_DIR, CONFIG_DIR, REFERENCE_DIR, ensure_directory
from .stage_std import RawStageHeader, parse_stage_std
from .stage_std_campaign import evaluate_stage_std_payload


DEFAULT_ARCHIVE = REFERENCE_DIR / "retail" / "game" / "th06" / "紅魔郷ST.DAT"
DEFAULT_ACTION_FILE = CONFIG_DIR / "headless_baseline_actions_1800.txt"
if not DEFAULT_ACTION_FILE.is_file():
    from ..headless.baseline import DEFAULT_ACTION_FILE as FALLBACK_ACTION_FILE

    DEFAULT_ACTION_FILE = FALLBACK_ACTION_FILE


@dataclass(frozen=True)
class StageStdMetamorphicCase:
    name: str
    payload: bytes
    relation: str
    description: str
    sha256: str


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-stage-std-metamorphic-runtime" / stamp


def _entry_name(stage: int) -> str:
    return f"stage{stage}.std"


def _case(
    name: str,
    payload: bytes,
    *,
    relation: str,
    description: str,
) -> StageStdMetamorphicCase:
    return StageStdMetamorphicCase(
        name=name,
        payload=payload,
        relation=relation,
        description=description,
        sha256=sha256_bytes(payload),
    )


def _replace_i32(payload: bytes, offset: int, value: int) -> bytes:
    mutable = bytearray(payload)
    struct.pack_into("<i", mutable, offset, int(value))
    return bytes(mutable)


def _ascii_field(value: str, *, size: int) -> bytes:
    return value.encode("ascii", errors="replace")[: size - 1].ljust(size, b"\x00")


def _replace_fixed_field(payload: bytes, offset: int, size: int, value: str) -> bytes:
    mutable = bytearray(payload)
    mutable[offset : offset + size] = _ascii_field(value, size=size)
    return bytes(mutable)


def _fill_after_nul(payload: bytes, offset: int, size: int, value: int) -> bytes:
    mutable = bytearray(payload)
    field = bytes(mutable[offset : offset + size])
    try:
        nul_index = field.index(0)
    except ValueError:
        return payload
    for index in range(offset + nul_index + 1, offset + size):
        mutable[index] = int(value) & 0xFF
    return bytes(mutable)


def _replace_song_field(payload: bytes, base_offset: int, index: int, value: str) -> bytes:
    return _replace_fixed_field(payload, base_offset + (index * 128), 128, value)


def generate_stage_std_metamorphic_cases(seed_payload: bytes) -> list[StageStdMetamorphicCase]:
    if len(seed_payload) < struct.calcsize("<hhhh"):
        raise ValueError("stage std seed payload is smaller than the header prefix")

    cases = [
        _case(
            "header-unk-c-pattern",
            _replace_i32(seed_payload, RawStageHeader.unk_c.offset, 0x5A5A5A5A),
            relation="stage-std-unknown-header-field-equivalence",
            description="Change RawStageHeader.unk_c only; gameplay should remain equivalent if the field is ignored.",
        ),
        _case(
            "stage-name-text-pattern",
            _replace_fixed_field(seed_payload, RawStageHeader.stageName.offset, 128, "DANMAKUFUZZ-STAGE"),
            relation="stage-std-display-metadata-headless-equivalence",
            description="Change the stage display name; headless gameplay trace should remain equivalent.",
        ),
        _case(
            "stage-name-tail-padding-aa",
            _fill_after_nul(seed_payload, RawStageHeader.stageName.offset, 128, 0xAA),
            relation="stage-std-cstring-tail-equivalence",
            description="Fill bytes after the stage-name NUL terminator; decoded C string should remain unchanged.",
        ),
        _case(
            "song-name-tail-padding-aa",
            _fill_after_nul(seed_payload, RawStageHeader.songNames.offset, 128, 0xAA),
            relation="stage-std-cstring-tail-equivalence",
            description="Fill bytes after the first song-name NUL terminator; decoded C string should remain unchanged.",
        ),
        _case(
            "song-path-tail-padding-aa",
            _fill_after_nul(seed_payload, RawStageHeader.songPaths.offset, 128, 0xAA),
            relation="stage-std-cstring-tail-equivalence",
            description="Fill bytes after the first song-path NUL terminator; decoded C string should remain unchanged.",
        ),
    ]

    song_name_payload = seed_payload
    for index in range(4):
        song_name_payload = _replace_song_field(
            song_name_payload,
            RawStageHeader.songNames.offset,
            index,
            f"DANMAKU SONG {index}",
        )
    cases.append(
        _case(
            "song-names-text-pattern",
            song_name_payload,
            relation="stage-std-display-metadata-headless-equivalence",
            description="Change all song display names; headless gameplay trace should remain equivalent.",
        )
    )

    song_path_payload = seed_payload
    for index in range(4):
        song_path_payload = _replace_song_field(
            song_path_payload,
            RawStageHeader.songPaths.offset,
            index,
            f"data/danmaku{index}.mid",
        )
    cases.append(
        _case(
            "song-paths-text-pattern",
            song_path_payload,
            relation="stage-std-audio-path-headless-equivalence",
            description="Change all song paths; this is a headless-only equivalence check because retail audio may differ.",
        )
    )

    deduped: list[StageStdMetamorphicCase] = []
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run STD stage-file metamorphic runtime equivalence checks through th06-headless."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", type=str)
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
        raise FileNotFoundError(f"missing STD archive: {archive_path}")
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
        worker_name=f"stage-std-metamorphic-stage{args.stage}",
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
    entry_name = args.entry or _entry_name(args.stage)
    seed_payload = archive.extract(entry_name)
    baseline_summary = {"input": f"{archive_path}:{entry_name}", **parse_stage_std(seed_payload)}
    (artifact_dir / "baseline-stage-std.json").write_text(
        json.dumps(baseline_summary, indent=2) + "\n",
        encoding="utf-8",
    )
    cases = generate_stage_std_metamorphic_cases(seed_payload)
    if args.name_filter:
        cases = [
            case
            for case in cases
            if any(name_filter in case.name for name_filter in args.name_filter)
        ]

    summary_path = artifact_dir / "summary.jsonl"
    relation_counts: Counter[str] = Counter()
    violation_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, case in enumerate(cases, start=1):
            case_name = f"{entry_name}-{case_index:04d}-{case.name}"
            case_dir = artifact_dir / case_name
            ensure_directory(case_dir)
            override_dir = materialize_override_bundle(case_dir, {entry_name: case.payload})
            parser_evaluation = evaluate_stage_std_payload(
                case.payload,
                baseline_summary,
                max_script_instructions=100000,
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
                "schema": "danmakufuzz-stage-std-metamorphic-runtime-case-v1",
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
        "schema": "danmakufuzz-stage-std-metamorphic-runtime-campaign-v1",
        "artifact_dir": str(artifact_dir),
        "archive": str(archive_path),
        "stage": args.stage,
        "entry": entry_name,
        "baseline": baseline,
        "cases_generated": len(cases),
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
