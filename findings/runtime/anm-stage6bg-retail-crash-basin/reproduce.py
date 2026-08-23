from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import struct


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from danmakufuzz.corpus.pbg3 import Pbg3Archive
from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR
from danmakufuzz.parser.anm import AnmRawEntry, parse_anm
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


DEFAULT_CASE = "first-sprite-offset-zero"
PRIMARY_STAGE_ARCHIVE = "紅魔郷ST.DAT"


def _here() -> Path:
    return Path(__file__).resolve().parent


def _load_cases() -> list[dict[str, object]]:
    data = json.loads((_here() / "cases.json").read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("cases.json has no cases")
    return [case for case in cases if isinstance(case, dict)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the Stage 6 background ANM retail crash basin."
    )
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--source-game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "runtime-anm-stage6bg-retail-crash-basin",
    )
    parser.add_argument("--repeat", type=int)
    parser.add_argument("--require", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=28.0)
    parser.add_argument("--startup-seconds", type=float, default=1.2)
    parser.add_argument("--stage-entry-wait-seconds", type=float, default=4.0)
    parser.add_argument("--stage-entry-min-frame", type=int, default=60)
    parser.add_argument("--progress-probe-seconds", type=float, default=12.0)
    parser.add_argument("--progress-probe-frames", type=int, default=450)
    parser.add_argument(
        "--startup-normalization",
        choices=("auto", "gdb", "off"),
        default="gdb",
    )
    return parser.parse_args()


def _selected_cases(cases: list[dict[str, object]], args: argparse.Namespace) -> list[dict[str, object]]:
    by_name = {str(case["name"]): case for case in cases}
    if args.all:
        return cases
    names = args.case or [DEFAULT_CASE]
    missing = sorted(set(names) - set(by_name))
    if missing:
        raise RuntimeError(f"unknown case name(s): {missing}")
    return [by_name[name] for name in names]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stage_archive(source_game_dir: Path) -> Path:
    archive = source_game_dir / PRIMARY_STAGE_ARCHIVE
    if not archive.is_file():
        raise FileNotFoundError(f"missing retail stage archive: {archive}")
    return archive


def _anm_mutation_offset(payload: bytes, mutation: dict[str, object]) -> int:
    entry = AnmRawEntry.from_buffer_copy(payload)
    header_size = ctypes.sizeof(AnmRawEntry)
    table = str(mutation["table"])
    index = int(mutation["index"])
    field = str(mutation["field"])
    if table == "sprite_offsets" and field == "offset":
        if not 0 <= index < int(entry.numSprites):
            raise RuntimeError(f"sprite index outside payload: {index}")
        return header_size + index * 4
    if table == "script_entries":
        if not 0 <= index < int(entry.numScripts):
            raise RuntimeError(f"script index outside payload: {index}")
        script_table_offset = header_size + int(entry.numSprites) * 4
        if field == "id":
            return script_table_offset + index * 8
        if field == "first_instruction":
            return script_table_offset + index * 8 + 4
    raise RuntimeError(f"unsupported ANM mutation recipe: {mutation!r}")


def _build_source_result(case: dict[str, object], args: argparse.Namespace, case_artifact_dir: Path) -> Path:
    case_name = str(case["name"])
    entry_name = str(case["entry_name"])
    archive = Pbg3Archive.from_bytes(_stage_archive(args.source_game_dir.resolve()).read_bytes())
    payload = bytearray(archive.extract(entry_name))
    mutation = case.get("mutation")
    if not isinstance(mutation, dict):
        raise RuntimeError(f"{case_name} is missing a mutation recipe")
    byte_offset = _anm_mutation_offset(payload, mutation)
    struct.pack_into("<I", payload, byte_offset, int(mutation["value"]))
    payload_bytes = bytes(payload)
    payload_sha256 = _sha256(payload_bytes)
    if payload_sha256 != case["payload_sha256"]:
        raise RuntimeError(
            f"{case_name} rebuilt payload sha drifted: expected {case['payload_sha256']}, got {payload_sha256}"
        )

    source_dir = case_artifact_dir / "source-result"
    override_dir = source_dir / "override"
    payload_path = override_dir / "data" / entry_name
    ensure_directory(payload_path.parent)
    payload_path.write_bytes(payload_bytes)
    result = {
        "case_name": case_name,
        "mutant_name": str(case.get("mutant_name") or case_name),
        "entry_name": entry_name,
        "override_dir": str(override_dir.resolve()),
        "payload_sha256": payload_sha256,
        "mutation": mutation,
        "parser_evaluation": parse_anm(payload_bytes),
        "target_hits": [str(case.get("primary_finding", "")).split(":", 1)[0]],
    }
    result_path = source_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result_path


def _run_case(case: dict[str, object], args: argparse.Namespace, *, repeat: int, require: int) -> dict[str, object]:
    case_name = str(case["name"])
    case_artifact_dir = args.artifact_dir.resolve() / case_name
    ensure_directory(case_artifact_dir)
    source_result = _build_source_result(case, args, case_artifact_dir)
    command = [
        sys.executable,
        "-m",
        "danmakufuzz.retail.confirm_case",
        "--result",
        str(source_result),
        "--artifact-dir",
        str(case_artifact_dir),
        "--source-game-dir",
        str(args.source_game_dir.resolve()),
        "--practice-stage",
        str(int(case["stage"])),
        "--difficulty",
        "3",
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--startup-seconds",
        str(args.startup_seconds),
        "--stage-entry-wait-seconds",
        str(args.stage_entry_wait_seconds),
        "--stage-entry-min-frame",
        str(args.stage_entry_min_frame),
        "--progress-probe-seconds",
        str(args.progress_probe_seconds),
        "--progress-probe-frames",
        str(args.progress_probe_frames),
        "--startup-normalization",
        str(args.startup_normalization),
        "--compare-clean-baseline",
        "--expect-classification",
        str(case["classification"]),
    ]
    if repeat > 1:
        command.extend(["--repeat", str(repeat), "--require", str(require)])
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    report_path = case_artifact_dir / "report.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"retail confirmation did not write {report_path}")
    return {
        "case": case_name,
        "classification": str(case["classification"]),
        "report": str(report_path.resolve()),
        "repeat": repeat,
        "require": require if repeat > 1 else None,
    }


def main() -> int:
    args = parse_args()
    cases = _selected_cases(_load_cases(), args)
    repeat = args.repeat
    if repeat is None:
        repeat = 1 if args.all or args.case else 2
    if repeat < 1:
        raise RuntimeError("--repeat must be at least 1")
    require = args.require if args.require is not None else repeat
    if require < 1 or require > repeat:
        raise RuntimeError("--require must be between 1 and --repeat")

    ensure_directory(args.artifact_dir.resolve())
    reports = [_run_case(case, args, repeat=repeat, require=require) for case in cases]
    summary = {
        "schema": "danmakufuzz-finding-reproduction-v1",
        "finding": "runtime/anm-stage6bg-retail-crash-basin",
        "artifact_dir": str(args.artifact_dir.resolve()),
        "reports": reports,
    }
    summary_path = args.artifact_dir.resolve() / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
