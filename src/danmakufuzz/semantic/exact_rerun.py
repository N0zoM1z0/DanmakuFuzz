from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ..headless.baseline import DEFAULT_ACTION_FILE, DEFAULT_GAME_DIR, default_headless_binary, run_baseline
from ..headless.prepare_worker_game_dir import prepare_worker_game_dir
from ..repo import ARTIFACTS_DIR, ensure_directory
from .ecl_campaign import LONG_ACTION_FILE, run_case
from .payload_mutants import PayloadMutant


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-exact-rerun" / stamp


@dataclass(frozen=True)
class ExactCase:
    source_result: Path
    case_name: str
    mutant_name: str
    seed_name: str
    stage: int
    cwd: Path
    payload_path: Path
    path: tuple[int, int] | None
    command: list[str]
    mutation_metadata: dict[str, object] | None
    findings: list[dict[str, object]]
    interesting: bool


def _parse_result_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"result json is not an object: {path}")
    return data


def _result_paths_from_summary(summary_path: Path) -> list[Path]:
    discovered: list[Path] = []
    with summary_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"summary entry is not an object: {summary_path}:{line_number}")
            case_name = data.get("case_name")
            if not isinstance(case_name, str) or not case_name:
                raise ValueError(f"summary entry is missing case_name: {summary_path}:{line_number}")
            result_path = (summary_path.parent / case_name / "result.json").resolve()
            if not result_path.is_file():
                raise FileNotFoundError(f"summary entry points to a missing result.json: {result_path}")
            discovered.append(result_path)
    return discovered


def _discover_result_paths(input_path: Path) -> list[Path]:
    resolved = input_path.resolve()
    if resolved.is_dir():
        return sorted(resolved.rglob("result.json"))
    if not resolved.is_file():
        raise FileNotFoundError(f"missing rerun input: {resolved}")
    if resolved.name == "result.json":
        return [resolved]
    if resolved.name == "summary.jsonl":
        return _result_paths_from_summary(resolved)
    if resolved.name == "campaign.json":
        data = _parse_result_json(resolved)
        summary_value = data.get("summary")
        if isinstance(summary_value, str):
            return _result_paths_from_summary(Path(summary_value))
        return sorted(resolved.parent.rglob("result.json"))
    raise ValueError(f"unsupported rerun input: {resolved}")


def _command_value(command: list[str], flag: str) -> str | None:
    if flag not in command:
        return None
    index = command.index(flag)
    if index + 1 >= len(command):
        raise ValueError(f"missing value for command flag {flag}")
    return command[index + 1]


def _command_has_flag(command: list[str], flag: str) -> bool:
    return flag in command


def _path_from_result(data: dict[str, object]) -> tuple[int, int] | None:
    raw_path = data.get("path")
    if raw_path is None:
        return None
    if not isinstance(raw_path, dict):
        raise ValueError(f"result path is not an object: {raw_path!r}")
    sub_index = raw_path.get("sub_index")
    instruction_index = raw_path.get("instruction_index")
    if not isinstance(sub_index, int) or not isinstance(instruction_index, int):
        raise ValueError(f"result path is missing sub_index/instruction_index: {raw_path!r}")
    return (sub_index, instruction_index)


def _load_exact_case(result_path: Path) -> ExactCase:
    data = _parse_result_json(result_path)
    case_name = data.get("case_name")
    mutant_name = data.get("mutant_name")
    seed_name = data.get("seed_name")
    stage = data.get("stage")
    cwd = data.get("cwd")
    override_dir = data.get("override_dir")
    command = data.get("command")
    mutation_metadata = data.get("mutation_metadata")
    findings = data.get("findings")
    interesting = data.get("interesting")
    if not isinstance(case_name, str) or not case_name:
        raise ValueError(f"result is missing case_name: {result_path}")
    if not isinstance(mutant_name, str) or not mutant_name:
        raise ValueError(f"result is missing mutant_name: {result_path}")
    if not isinstance(seed_name, str) or not seed_name:
        raise ValueError(f"result is missing seed_name: {result_path}")
    if not isinstance(stage, int):
        raise ValueError(f"result is missing stage: {result_path}")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError(f"result is missing cwd: {result_path}")
    if not isinstance(override_dir, str) or not override_dir:
        raise ValueError(f"result is missing override_dir: {result_path}")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise ValueError(f"result command is invalid: {result_path}")
    if mutation_metadata is not None and not isinstance(mutation_metadata, dict):
        raise ValueError(f"result mutation_metadata is invalid: {result_path}")
    if not isinstance(findings, list):
        raise ValueError(f"result findings are invalid: {result_path}")
    if not isinstance(interesting, bool):
        raise ValueError(f"result interesting flag is invalid: {result_path}")
    payload_path = (Path(override_dir) / "data" / seed_name).resolve()
    if not payload_path.is_file():
        raise FileNotFoundError(f"result payload is missing: {payload_path}")
    return ExactCase(
        source_result=result_path.resolve(),
        case_name=case_name,
        mutant_name=mutant_name,
        seed_name=seed_name,
        stage=stage,
        cwd=Path(cwd).resolve(),
        payload_path=payload_path,
        path=_path_from_result(data),
        command=command,
        mutation_metadata=mutation_metadata,
        findings=[entry for entry in findings if isinstance(entry, dict)],
        interesting=interesting,
    )


def _case_matches(case: ExactCase, *, interesting_only: bool, match_kinds: set[str]) -> bool:
    if interesting_only and not case.interesting:
        return False
    if match_kinds:
        case_kinds = {
            str(entry.get("kind"))
            for entry in case.findings
            if isinstance(entry.get("kind"), str)
        }
        if not (case_kinds & match_kinds):
            return False
    return True


def _build_mutant(case: ExactCase) -> PayloadMutant:
    payload = case.payload_path.read_bytes()
    return PayloadMutant(
        name=case.mutant_name,
        payload=payload,
        source="exact-rerun",
        path=case.path,
        metadata=case.mutation_metadata,
    )


def _resolve_actions(case: ExactCase, override_actions: Path | None, *, max_ticks: int) -> Path:
    if override_actions is not None:
        return override_actions.resolve()
    value = _command_value(case.command, "--actions")
    if value is None:
        raise ValueError(f"result command is missing --actions: {case.source_result}")
    resolved = Path(value).resolve()
    if max_ticks > 600 and resolved == DEFAULT_ACTION_FILE.resolve():
        return LONG_ACTION_FILE.resolve()
    return resolved


def _resolve_max_ticks(case: ExactCase, override_max_ticks: int | None) -> int:
    if override_max_ticks is not None:
        return override_max_ticks
    value = _command_value(case.command, "--max-ticks")
    if value is None:
        raise ValueError(f"result command is missing --max-ticks: {case.source_result}")
    return int(value)


def _resolve_timeout(case: ExactCase, override_timeout: float | None) -> float:
    if override_timeout is not None:
        return override_timeout
    max_ticks = _resolve_max_ticks(case, None)
    return 15.0 if max_ticks > 600 else 5.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rerun exact semantic case payloads from prior result.json artifacts."
    )
    parser.add_argument(
        "--result",
        action="append",
        type=Path,
        required=True,
        help="result.json, summary.jsonl, campaign.json, or a directory to scan recursively",
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--headless-bin", type=Path, default=default_headless_binary())
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--no-reuse-worker-game-dir", action="store_true")
    parser.add_argument("--interesting-only", action="store_true")
    parser.add_argument("--match-kind", action="append")
    parser.add_argument("--actions", type=Path)
    parser.add_argument("--max-ticks", type=int)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--difficulty", type=int)
    parser.add_argument("--character", type=int)
    parser.add_argument("--shot-type", type=int)
    parser.add_argument("--auto-shoot", dest="auto_shoot", action="store_true")
    parser.add_argument("--no-auto-shoot", dest="auto_shoot", action="store_false")
    parser.add_argument("--continue-after-hit", dest="continue_after_hit", action="store_true")
    parser.add_argument("--stop-after-hit", dest="continue_after_hit", action="store_false")
    parser.set_defaults(auto_shoot=None, continue_after_hit=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    result_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for input_path in args.result:
        for result_path in _discover_result_paths(input_path):
            resolved = result_path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            result_paths.append(resolved)
    if not result_paths:
        raise ValueError("exact rerun did not find any result.json inputs")

    match_kinds = {value for value in args.match_kind or [] if value}
    cases = [
        case
        for case in (_load_exact_case(path) for path in result_paths)
        if _case_matches(case, interesting_only=args.interesting_only, match_kinds=match_kinds)
    ]
    if not cases:
        raise ValueError("exact rerun inputs did not leave any cases after filtering")

    worker_game_dir = artifact_dir / "worker-game"
    worker_prepare = prepare_worker_game_dir(
        source_game_dir=args.game_dir.resolve(),
        destination=worker_game_dir,
        worker_name="semantic-exact-rerun",
        reuse=not args.no_reuse_worker_game_dir,
    )

    baseline_cache: dict[tuple[object, ...], Path] = {}
    rerun_results: list[dict[str, object]] = []
    summary_path = artifact_dir / "summary.jsonl"
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, case in enumerate(cases, start=1):
            seed = args.seed if args.seed is not None else int(_command_value(case.command, "--seed") or 7)
            difficulty = (
                args.difficulty if args.difficulty is not None else int(_command_value(case.command, "--difficulty") or 3)
            )
            character = (
                args.character if args.character is not None else int(_command_value(case.command, "--character") or 0)
            )
            shot_type = (
                args.shot_type if args.shot_type is not None else int(_command_value(case.command, "--shot-type") or 0)
            )
            max_ticks = _resolve_max_ticks(case, args.max_ticks)
            actions = _resolve_actions(case, args.actions, max_ticks=max_ticks)
            timeout_seconds = _resolve_timeout(case, args.timeout_seconds)
            auto_shoot = args.auto_shoot if args.auto_shoot is not None else _command_has_flag(case.command, "--auto-shoot")
            continue_after_hit = (
                args.continue_after_hit
                if args.continue_after_hit is not None
                else _command_has_flag(case.command, "--continue-after-hit")
            )

            baseline_key = (
                case.stage,
                seed,
                difficulty,
                character,
                shot_type,
                str(actions),
                max_ticks,
                auto_shoot,
                continue_after_hit,
            )
            baseline_trace = baseline_cache.get(baseline_key)
            if baseline_trace is None:
                baseline_artifact_dir = artifact_dir / f"_baseline-stage{case.stage}-seed{seed}-ticks{max_ticks}"
                baseline_metadata = run_baseline(
                    binary=args.headless_bin.resolve(),
                    game_dir=worker_game_dir.resolve(),
                    resource_override_dir=None,
                    stage=case.stage,
                    seed=seed,
                    action_file=actions,
                    artifact_dir=baseline_artifact_dir.resolve(),
                    difficulty=difficulty,
                    character=character,
                    shot_type=shot_type,
                    max_ticks=max_ticks,
                    auto_shoot=auto_shoot,
                    continue_after_hit=continue_after_hit,
                    dry_run=False,
                )
                baseline_trace_value = baseline_metadata.get("trace")
                if not isinstance(baseline_trace_value, str):
                    raise RuntimeError(f"baseline trace is missing for {case.source_result}")
                baseline_trace = Path(baseline_trace_value).resolve()
                if not baseline_trace.is_file():
                    raise FileNotFoundError(f"baseline trace is missing: {baseline_trace}")
                baseline_cache[baseline_key] = baseline_trace

            rerun = run_case(
                binary=args.headless_bin.resolve(),
                game_dir=worker_game_dir.resolve(),
                stage=case.stage,
                seed=seed,
                action_file=actions,
                difficulty=difficulty,
                character=character,
                shot_type=shot_type,
                max_ticks=max_ticks,
                auto_shoot=auto_shoot,
                continue_after_hit=continue_after_hit,
                timeout_seconds=timeout_seconds,
                campaign_dir=artifact_dir,
                seed_name=case.seed_name,
                mutant=_build_mutant(case),
                case_index=case_index,
                baseline_trace=baseline_trace,
            )
            enriched = {
                "source_result": str(case.source_result),
                "source_case_name": case.case_name,
                "payload_path": str(case.payload_path),
                "rerun_case_name": rerun["case_name"],
                "rerun_result": str((artifact_dir / rerun["case_name"] / "result.json").resolve()),
                "interesting": rerun["interesting"],
                "findings": rerun["findings"],
            }
            rerun_results.append(enriched)
            summary_handle.write(json.dumps(enriched) + "\n")
            print(json.dumps(enriched, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-semantic-exact-rerun-v1",
        "artifact_dir": str(artifact_dir),
        "worker_prepare": worker_prepare,
        "inputs": [str(path) for path in result_paths],
        "interesting_only": args.interesting_only,
        "match_kinds": sorted(match_kinds),
        "actions_override": str(args.actions.resolve()) if args.actions is not None else None,
        "max_ticks_override": args.max_ticks,
        "timeout_seconds_override": args.timeout_seconds,
        "seed_override": args.seed,
        "difficulty_override": args.difficulty,
        "character_override": args.character,
        "shot_type_override": args.shot_type,
        "auto_shoot_override": args.auto_shoot,
        "continue_after_hit_override": args.continue_after_hit,
        "cases_run": len(rerun_results),
        "interesting_cases": sum(int(bool(item["interesting"])) for item in rerun_results),
        "summary": str(summary_path.resolve()),
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
