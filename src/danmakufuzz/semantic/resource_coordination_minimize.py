from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Callable

from ..headless.baseline import DEFAULT_GAME_DIR
from ..interestingness.rules import Finding, score_trace_path_with_baseline
from ..repo import ARTIFACTS_DIR, ensure_directory
from .ecl_campaign import classify_process_result
from .resource_coordination_common import (
    baseline_trace_for_result,
    discover_resource_results,
    first_diff_line,
    game_dir_for_result,
    load_json_object,
    load_trace_rows,
    override_payload_paths,
    sink_signature_from_records,
    trace_sha256,
)


def _replace_trace_path(command: list[str], trace_path: Path) -> list[str]:
    updated = list(command)
    if "--trace" not in updated:
        raise ValueError("command template does not contain --trace")
    trace_index = updated.index("--trace")
    updated[trace_index + 1] = str(trace_path.resolve())
    return updated


def _ordered_findings(data: dict[str, object]) -> list[tuple[str | None, str | None]]:
    findings = data.get("findings")
    if not isinstance(findings, list):
        return []
    ordered: list[tuple[str | None, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for item in findings:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        detail = item.get("detail")
        if not isinstance(kind, str):
            continue
        pair = (kind, detail if isinstance(detail, str) else None)
        if pair in seen:
            continue
        seen.add(pair)
        ordered.append(pair)
    return ordered


def _ddmin_keys(
    keys: list[str],
    predicate: Callable[[list[str]], bool],
    *,
    max_evaluations: int,
    evaluation_counter: list[int],
) -> list[str]:
    current = list(keys)
    granularity = 2
    while len(current) > 0 and evaluation_counter[0] < max_evaluations:
        if len(current) == 1:
            break
        chunk_size = math.ceil(len(current) / granularity)
        reduced = False
        for start in range(0, len(current), chunk_size):
            candidate = current[:start] + current[start + chunk_size :]
            evaluation_counter[0] += 1
            if predicate(candidate):
                current = candidate
                granularity = max(2, granularity - 1)
                reduced = True
                break
            if evaluation_counter[0] >= max_evaluations:
                break
        if not reduced:
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    return current


def _evaluate_bundle(
    *,
    command_template: list[str],
    game_dir: Path,
    payloads: dict[str, bytes],
    work_dir: Path,
    timeout_seconds: float,
    baseline_trace: Path | None,
) -> dict[str, object]:
    ensure_directory(work_dir)
    override_dir = work_dir / "override"
    ensure_directory(override_dir / "data")
    for relative_name, payload in sorted(payloads.items()):
        path = override_dir / "data" / relative_name
        ensure_directory(path.parent)
        path.write_bytes(payload)

    trace_path = work_dir / "trace.jsonl"
    log_path = work_dir / "run.log"
    command = _replace_trace_path(command_template, trace_path)
    run_env = dict(os.environ)
    run_env["DANMAKUFUZZ_OVERRIDE_DIR"] = str(override_dir.resolve())

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
        baseline_records = load_trace_rows(baseline_trace) if baseline_trace is not None else []
        findings.extend(score_trace_path_with_baseline(trace_path, baseline_records=baseline_records))
    elif not findings:
        findings.append(Finding("empty-trace", "headless run finished without a non-empty trace"))
    trace_rows = load_trace_rows(trace_path)
    sink_signature, sink_snapshot, sink_tick = sink_signature_from_records(trace_rows)
    baseline_rows = load_trace_rows(baseline_trace) if baseline_trace is not None else []
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed_seconds,
        "trace": str(trace_path.resolve()),
        "trace_lines": len(trace_rows),
        "trace_sha256": trace_sha256(trace_path),
        "log": str(log_path.resolve()),
        "override_dir": str(override_dir.resolve()),
        "findings": [{"kind": finding.kind, "detail": finding.detail} for finding in findings],
        "sink_signature": sink_signature,
        "sink_snapshot": sink_snapshot,
        "sink_tick": sink_tick,
        "first_diff_line": first_diff_line(baseline_rows, trace_rows) if baseline_rows and trace_rows else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimize a coordinated resource case by dropping override entries while preserving the same coarse sink."
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--max-evaluations", type=int, default=32)
    parser.add_argument("--match-kind", type=str)
    parser.add_argument("--match-detail", type=str)
    parser.add_argument("--preserve-exact-trace", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_path = args.result.resolve()
    if not result_path.is_file():
        raise FileNotFoundError(f"missing result.json: {result_path}")
    case_result = load_json_object(result_path)
    command_template = case_result.get("command")
    if not isinstance(command_template, list) or not all(isinstance(item, str) for item in command_template):
        raise ValueError("result.json does not contain a valid command list")

    artifact_dir = args.artifact_dir or (ARTIFACTS_DIR / "resource-coordination-minimized" / result_path.parent.name)
    artifact_dir = artifact_dir.resolve()
    ensure_directory(artifact_dir)

    original_payload_paths = override_payload_paths(case_result, result_path)
    original_payloads = {key: path.read_bytes() for key, path in original_payload_paths.items()}
    original_keys = sorted(original_payloads)
    baseline_trace = baseline_trace_for_result(result_path)
    game_dir = args.game_dir.resolve()
    if args.game_dir == DEFAULT_GAME_DIR:
        game_dir = game_dir_for_result(result_path, case_result)
    if not game_dir.is_dir():
        raise FileNotFoundError(f"missing game directory: {game_dir}")

    original_trace = Path(str(case_result.get("trace"))).resolve() if isinstance(case_result.get("trace"), str) else None
    original_trace_sha = trace_sha256(original_trace) if original_trace is not None else None
    original_sink_signature, original_sink_snapshot, original_sink_tick = (
        sink_signature_from_records(load_trace_rows(original_trace)) if original_trace is not None else (None, None, None)
    )
    target_kind = args.match_kind
    target_detail = args.match_detail

    history: list[dict[str, object]] = []
    evaluation_counter = [0]

    def predicate(candidate_keys: list[str]) -> bool:
        payloads = {key: original_payloads[key] for key in candidate_keys}
        work_dir = artifact_dir / f"eval-{len(history):04d}"
        result = _evaluate_bundle(
            command_template=list(command_template),
            game_dir=game_dir,
            payloads=payloads,
            work_dir=work_dir,
            timeout_seconds=args.timeout_seconds,
            baseline_trace=baseline_trace,
        )
        matched = False
        if args.preserve_exact_trace:
            matched = result["trace_sha256"] == original_trace_sha
        elif target_kind is not None:
            matched = any(
                row.get("kind") == target_kind
                and (target_detail is None or row.get("detail") == target_detail)
                for row in result["findings"]
                if isinstance(row, dict)
            )
        else:
            matched = (
                result["returncode"] == case_result.get("returncode")
                and bool(result["timed_out"]) == bool(case_result.get("timed_out"))
                and int(result["trace_lines"]) == int(case_result.get("trace_lines", 0))
                and result["sink_signature"] == original_sink_signature
            )
        history.append(
            {
                "eval_index": len(history),
                "override_keys": list(candidate_keys),
                "override_count": len(candidate_keys),
                "matched": matched,
                "returncode": result["returncode"],
                "timed_out": result["timed_out"],
                "trace_lines": result["trace_lines"],
                "trace_sha256": result["trace_sha256"],
                "sink_signature": result["sink_signature"],
                "first_diff_line": result["first_diff_line"],
                "findings": result["findings"],
                "work_dir": str(work_dir.resolve()),
            }
        )
        return matched

    if not predicate(original_keys):
        raise RuntimeError("original override bundle no longer reproduces the requested sink/target")

    minimized_keys = _ddmin_keys(
        original_keys,
        predicate,
        max_evaluations=args.max_evaluations,
        evaluation_counter=evaluation_counter,
    )
    final_dir = artifact_dir / "final"
    final_payloads = {key: original_payloads[key] for key in minimized_keys}
    final_result = _evaluate_bundle(
        command_template=list(command_template),
        game_dir=game_dir,
        payloads=final_payloads,
        work_dir=final_dir,
        timeout_seconds=args.timeout_seconds,
        baseline_trace=baseline_trace,
    )
    summary = {
        "schema": "danmakufuzz-resource-coordination-minimized-v1",
        "source_result": str(result_path),
        "target_mode": "exact-trace" if args.preserve_exact_trace else ("finding" if target_kind is not None else "coarse-sink"),
        "target": {"kind": target_kind, "detail": target_detail} if target_kind is not None else None,
        "original_override_keys": original_keys,
        "original_override_count": len(original_keys),
        "minimized_override_keys": minimized_keys,
        "minimized_override_count": len(minimized_keys),
        "removed_override_keys": [key for key in original_keys if key not in set(minimized_keys)],
        "original_trace_sha256": original_trace_sha,
        "original_sink_signature": original_sink_signature,
        "original_sink_tick": original_sink_tick,
        "original_sink_snapshot": original_sink_snapshot,
        "evaluation_count": len(history),
        "reduction_attempts": evaluation_counter[0],
        "max_reduction_attempts": args.max_evaluations,
        "game_dir": str(game_dir),
        "baseline_trace": str(baseline_trace.resolve()) if baseline_trace is not None else None,
        "final_result": final_result,
        "final_override_dir": str((final_dir / "override").resolve()),
    }
    (artifact_dir / "history.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in history),
        encoding="utf-8",
    )
    (artifact_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
