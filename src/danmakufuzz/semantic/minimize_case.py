from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from typing import Callable

from ..headless.baseline import DEFAULT_GAME_DIR
from ..interestingness.rules import Finding, score_trace, score_trace_differential
from ..repo import ARTIFACTS_DIR, ensure_directory
from .ecl_campaign import classify_process_result


@dataclass(frozen=True)
class TargetFinding:
    kind: str
    detail: str | None = None

    def matches(self, findings: list[Finding]) -> bool:
        for finding in findings:
            if finding.kind != self.kind:
                continue
            if self.detail is None or finding.detail == self.detail:
                return True
        return False


@dataclass(frozen=True)
class CandidateResult:
    returncode: int | None
    timed_out: bool
    elapsed_seconds: float
    findings: tuple[Finding, ...]
    trace_path: Path
    log_path: Path
    override_dir: Path

    @property
    def interesting(self) -> bool:
        return bool(self.findings)


def _replace_trace_path(command: list[str], trace_path: Path) -> list[str]:
    updated = list(command)
    if "--trace" not in updated:
        raise ValueError("command template does not contain --trace")
    trace_index = updated.index("--trace")
    updated[trace_index + 1] = str(trace_path.resolve())
    return updated


def _payload_path_from_case_result(case_result: dict[str, object], result_path: Path) -> Path:
    override_dir = case_result.get("override_dir")
    seed_name = case_result.get("seed_name")
    if not isinstance(override_dir, str) or not isinstance(seed_name, str):
        raise ValueError(f"result.json is missing override_dir/seed_name: {result_path}")
    payload_path = Path(override_dir) / "data" / seed_name
    if not payload_path.is_file():
        raise FileNotFoundError(f"missing payload file for case: {payload_path}")
    return payload_path


def _load_case_result(result_path: Path) -> dict[str, object]:
    data = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"result.json is not an object: {result_path}")
    return data


def _campaign_baseline_trace(result_path: Path) -> Path | None:
    candidate = result_path.parent.parent / "_baseline" / "trace.jsonl"
    return candidate if candidate.is_file() else None


def _target_from_case_result(case_result: dict[str, object], *, kind: str | None, detail: str | None) -> TargetFinding:
    if kind is not None:
        return TargetFinding(kind=kind, detail=detail)
    findings = case_result.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ValueError("result.json does not contain any findings; specify --match-kind explicitly")
    first = findings[0]
    if not isinstance(first, dict) or not isinstance(first.get("kind"), str):
        raise ValueError("result.json has an invalid findings entry")
    first_detail = first.get("detail")
    return TargetFinding(kind=first["kind"], detail=first_detail if isinstance(first_detail, str) else None)


def evaluate_payload(
    *,
    command_template: list[str],
    game_dir: Path,
    payload: bytes,
    seed_name: str,
    work_dir: Path,
    timeout_seconds: float,
    baseline_trace: Path | None = None,
) -> CandidateResult:
    ensure_directory(work_dir)
    override_dir = work_dir / "override"
    ensure_directory(override_dir / "data")
    payload_path = override_dir / "data" / seed_name
    payload_path.write_bytes(payload)

    trace_path = work_dir / "trace.jsonl"
    log_path = work_dir / "run.log"
    command = _replace_trace_path(command_template, trace_path)
    run_env = os.environ.copy()
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
    if trace_path.exists() and trace_path.stat().st_size > 0:
        findings.extend(score_trace(trace_path))
        if baseline_trace is not None and baseline_trace.is_file():
            findings.extend(score_trace_differential(trace_path, baseline_trace))
    elif not findings:
        findings.append(Finding("empty-trace", "headless run finished without a non-empty trace"))

    return CandidateResult(
        returncode=returncode,
        timed_out=timed_out,
        elapsed_seconds=elapsed_seconds,
        findings=tuple(findings),
        trace_path=trace_path,
        log_path=log_path,
        override_dir=override_dir,
    )


def _ddmin_delete(
    payload: bytes,
    predicate: Callable[[bytes], bool],
    *,
    max_evaluations: int,
    evaluation_counter: list[int],
) -> bytes:
    current = payload
    granularity = 2
    while len(current) > 0 and evaluation_counter[0] < max_evaluations:
        chunk_size = math.ceil(len(current) / granularity)
        reduced = False
        for start in range(0, len(current), chunk_size):
            candidate = current[:start] + current[start + chunk_size:]
            evaluation_counter[0] += 1
            if predicate(candidate):
                current = candidate
                granularity = max(2, granularity - 1)
                reduced = True
                break
            if evaluation_counter[0] >= max_evaluations:
                break
        if not reduced:
            if granularity >= max(1, len(current)):
                break
            granularity = min(len(current), granularity * 2)
    return current


def _ddmin_zero(
    payload: bytes,
    predicate: Callable[[bytes], bool],
    *,
    max_evaluations: int,
    evaluation_counter: list[int],
) -> bytes:
    current = payload
    granularity = 2
    while len(current) > 0 and evaluation_counter[0] < max_evaluations:
        chunk_size = math.ceil(len(current) / granularity)
        reduced = False
        for start in range(0, len(current), chunk_size):
            end = min(len(current), start + chunk_size)
            mutable = bytearray(current)
            mutable[start:end] = b"\x00" * (end - start)
            candidate = bytes(mutable)
            if candidate == current:
                continue
            evaluation_counter[0] += 1
            if predicate(candidate):
                current = candidate
                granularity = max(2, granularity - 1)
                reduced = True
                break
            if evaluation_counter[0] >= max_evaluations:
                break
        if not reduced:
            if granularity >= max(1, len(current)):
                break
            granularity = min(len(current), granularity * 2)
    return current


def _fine_zero(
    payload: bytes,
    predicate: Callable[[bytes], bool],
    *,
    max_evaluations: int,
    evaluation_counter: list[int],
    byte_limit: int = 4096,
) -> bytes:
    current = payload
    if len(current) > byte_limit:
        return current
    index = 0
    while index < len(current) and evaluation_counter[0] < max_evaluations:
        if current[index] == 0:
            index += 1
            continue
        mutable = bytearray(current)
        mutable[index] = 0
        candidate = bytes(mutable)
        evaluation_counter[0] += 1
        if predicate(candidate):
            current = candidate
            continue
        index += 1
    return current


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimize a previously captured interesting semantic case.")
    parser.add_argument("--result", type=Path, required=True, help="Path to a semantic campaign result.json")
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--match-kind", type=str)
    parser.add_argument("--match-detail", type=str)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--max-evaluations", type=int, default=64)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_path = args.result.resolve()
    if not result_path.is_file():
        raise FileNotFoundError(f"missing result.json: {result_path}")
    resolved_game_dir = args.game_dir.resolve()
    if not resolved_game_dir.is_dir():
        raise FileNotFoundError(f"missing game directory: {resolved_game_dir}")

    case_result = _load_case_result(result_path)
    if args.game_dir == DEFAULT_GAME_DIR and isinstance(case_result.get("cwd"), str):
        resolved_game_dir = Path(case_result["cwd"]).resolve()
    game_dir = resolved_game_dir
    command_template = case_result.get("command")
    if not isinstance(command_template, list) or not all(isinstance(item, str) for item in command_template):
        raise ValueError("result.json does not contain a valid command list")
    seed_name = case_result.get("seed_name")
    if not isinstance(seed_name, str):
        raise ValueError("result.json does not contain seed_name")
    payload_path = _payload_path_from_case_result(case_result, result_path)
    original_payload = payload_path.read_bytes()
    target = _target_from_case_result(case_result, kind=args.match_kind, detail=args.match_detail)
    baseline_trace = _campaign_baseline_trace(result_path)
    artifact_dir = args.artifact_dir or (
        ARTIFACTS_DIR / "semantic-minimized" / result_path.parent.name
    )
    ensure_directory(artifact_dir)

    eval_counter = [0]
    history: list[dict[str, object]] = []

    def predicate(candidate: bytes) -> bool:
        run_index = eval_counter[0]
        work_dir = artifact_dir / f"eval-{run_index:04d}"
        result = evaluate_payload(
            command_template=command_template,
            game_dir=game_dir,
            payload=candidate,
            seed_name=seed_name,
            work_dir=work_dir,
            timeout_seconds=args.timeout_seconds,
            baseline_trace=baseline_trace,
        )
        matched = target.matches(list(result.findings))
        history.append(
            {
                "eval_index": run_index,
                "payload_size": len(candidate),
                "matched": matched,
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "findings": [{"kind": finding.kind, "detail": finding.detail} for finding in result.findings],
                "work_dir": str(work_dir.resolve()),
            }
        )
        return matched

    if not predicate(original_payload):
        raise RuntimeError("original payload does not reproduce the requested target finding")

    minimized = original_payload
    minimized = _ddmin_delete(minimized, predicate, max_evaluations=args.max_evaluations, evaluation_counter=eval_counter)
    minimized = _ddmin_zero(minimized, predicate, max_evaluations=args.max_evaluations, evaluation_counter=eval_counter)
    minimized = _fine_zero(minimized, predicate, max_evaluations=args.max_evaluations, evaluation_counter=eval_counter)

    final_dir = artifact_dir / "final"
    final_result = evaluate_payload(
        command_template=command_template,
        game_dir=game_dir,
        payload=minimized,
        seed_name=seed_name,
        work_dir=final_dir,
        timeout_seconds=args.timeout_seconds,
        baseline_trace=baseline_trace,
    )
    final_payload_path = final_dir / "override" / "data" / seed_name
    summary = {
        "source_result": str(result_path),
        "payload_path": str(payload_path),
        "target": {"kind": target.kind, "detail": target.detail},
        "original_size": len(original_payload),
        "minimized_size": len(minimized),
        "history_entries": len(history),
        "reduction_attempts": eval_counter[0],
        "max_reduction_attempts": args.max_evaluations,
        "final_payload": str(final_payload_path.resolve()),
        "final_trace": str(final_result.trace_path.resolve()),
        "final_log": str(final_result.log_path.resolve()),
        "final_findings": [{"kind": finding.kind, "detail": finding.detail} for finding in final_result.findings],
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
