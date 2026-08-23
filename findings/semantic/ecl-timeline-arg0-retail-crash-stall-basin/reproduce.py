from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from danmakufuzz.headless.baseline import DEFAULT_GAME_DIR
from danmakufuzz.ecl_ir.model import TimelineInstruction
from danmakufuzz.ecl_ir.parser import parse_ecl
from danmakufuzz.ecl_ir.serializer import serialize_ecl_canonical
from danmakufuzz.repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory


DEFAULT_CASE = "stage5-arg0-256"


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
        description="Reproduce the ECL timeline-arg0 retail crash/stall basin."
    )
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--source-game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "semantic-ecl-timeline-arg0-retail-crash-stall-basin",
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


def _build_source_result(case: dict[str, object], case_artifact_dir: Path) -> Path:
    case_name = str(case["name"])
    seed_name = str(case.get("seed_name") or f"ecldata{int(case['stage'])}.ecl")
    source_path = REFERENCE_DIR / "corpus" / "ecl" / "original" / seed_name
    source_payload = source_path.read_bytes()
    ecl = parse_ecl(source_payload).clone()
    timeline_index = int(case["timeline_index"])
    if not 0 <= timeline_index < len(ecl.timeline):
        raise RuntimeError(f"{case_name} timeline_index is outside {seed_name}: {timeline_index}")
    old = ecl.timeline[timeline_index]
    ecl.timeline[timeline_index] = TimelineInstruction(
        time=old.time,
        arg0=int(case["timeline_arg0"]),
        opcode=old.opcode,
        size=old.size,
        args=old.args,
    )
    payload = serialize_ecl_canonical(ecl)
    payload_sha256 = _sha256(payload)
    if payload_sha256 != case["payload_sha256"]:
        raise RuntimeError(
            f"{case_name} rebuilt payload sha drifted: expected {case['payload_sha256']}, got {payload_sha256}"
        )

    source_dir = case_artifact_dir / "source-result"
    override_dir = source_dir / "override"
    payload_path = override_dir / "data" / seed_name
    ensure_directory(payload_path.parent)
    payload_path.write_bytes(payload)
    result = {
        "case_name": case_name,
        "mutant_name": f"timeline-arg0-{int(case['timeline_arg0'])}",
        "seed_name": seed_name,
        "override_dir": str(override_dir.resolve()),
        "payload_sha256": payload_sha256,
        "mutation_metadata": {
            "family": "timeline-arg0",
            "field_name": "arg0",
            "value": int(case["timeline_arg0"]),
            "site_key": f"tl{timeline_index:04d}",
            "sites": [{"site_kind": "timeline", "instruction_index": timeline_index}],
        },
        "sites": [{"site_kind": "timeline", "instruction_index": timeline_index}],
    }
    result_path = source_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result_path


def _run_case(case: dict[str, object], args: argparse.Namespace, *, repeat: int, require: int) -> dict[str, object]:
    case_name = str(case["name"])
    classification = str(case["classification"])
    case_artifact_dir = args.artifact_dir.resolve() / case_name
    ensure_directory(case_artifact_dir)
    source_result = _build_source_result(case, case_artifact_dir)
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
        classification,
    ]
    if repeat > 1:
        command.extend(["--repeat", str(repeat), "--require", str(require)])
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    report_path = case_artifact_dir / "report.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"retail confirmation did not write {report_path}")
    return {
        "case": case_name,
        "classification": classification,
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
        "finding": "semantic/ecl-timeline-arg0-retail-crash-stall-basin",
        "artifact_dir": str(args.artifact_dir.resolve()),
        "reports": reports,
    }
    summary_path = args.artifact_dir.resolve() / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
