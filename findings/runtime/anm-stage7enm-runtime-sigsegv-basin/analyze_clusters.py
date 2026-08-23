from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from danmakufuzz.interestingness.rules import load_trace_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster the Stage 7 enemy ANM SIGSEGV basin by trace identity and first divergence."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("artifacts/findings/runtime-anm-stage7enm-runtime-sigsegv-basin"),
    )
    return parser.parse_args()


def _trace_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first_diff_line(
    baseline_records: list[dict[str, object]],
    case_records: list[dict[str, object]],
) -> int:
    for line_number, (baseline_record, case_record) in enumerate(
        zip(baseline_records, case_records),
        start=1,
    ):
        if baseline_record != case_record:
            return line_number
    return min(len(baseline_records), len(case_records)) + 1


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    summary_path = artifact_dir / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"missing finding summary: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    baseline_trace = Path(summary["baseline"]["trace"])
    baseline_records = load_trace_records(baseline_trace)

    cluster_map: dict[str, dict[str, object]] = {}
    cases: list[dict[str, object]] = []
    for case in summary["cases"]:
        trace_path = Path(case["trace"])
        trace_records = load_trace_records(trace_path)
        trace_hash = _trace_sha256(trace_path)
        first_diff_line = _first_diff_line(baseline_records, trace_records)
        analysis = {
            "mutant_name": case["mutant_name"],
            "trace_sha256": trace_hash,
            "trace_lines": len(trace_records),
            "first_diff_line": first_diff_line,
            "finding_kinds": case["finding_kinds"],
        }
        cases.append(analysis)
        cluster = cluster_map.setdefault(
            trace_hash,
            {
                "trace_sha256": trace_hash,
                "trace_lines": len(trace_records),
                "first_diff_line": first_diff_line,
                "mutants": [],
            },
        )
        cluster["mutants"].append(case["mutant_name"])

    clusters = sorted(cluster_map.values(), key=lambda cluster: (cluster["first_diff_line"], cluster["trace_sha256"]))
    report = {
        "finding": summary["finding"],
        "artifact_dir": str(artifact_dir),
        "baseline_trace": str(baseline_trace),
        "baseline_trace_lines": len(baseline_records),
        "case_count": len(cases),
        "cluster_count": len(clusters),
        "cases": cases,
        "clusters": clusters,
        "root_cause_hypothesis": [
            {
                "cluster_kind": "clean-script-crash",
                "mutants": [
                    "first-script-id-ffff",
                    "first-script-offset-zero",
                    "first-instr-opcode-255",
                ],
                "evidence": "identical trace hash; no divergence before the final emitted line; same SIGSEGV sink",
            },
            {
                "cluster_kind": "sprite-prelude-crash",
                "mutants": [
                    "first-sprite-offset-zero",
                ],
                "evidence": "different trace hash and immediate ANM-load drift, but converges to the same 440-line SIGSEGV sink",
            },
        ],
    }
    output_path = artifact_dir / "cluster-summary.json"
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
