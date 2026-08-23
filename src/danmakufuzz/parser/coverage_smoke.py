from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

from ..corpus.pbg3 import Pbg3Archive, Pbg3Error, sha256_bytes
from ..repo import ARTIFACTS_DIR, ensure_directory
from .anm import DEFAULT_ARCHIVE as DEFAULT_ANM_ARCHIVE
from .anm import DEFAULT_ENTRY as DEFAULT_ANM_ENTRY
from .anm import parse_anm
from .anm_mutants import generate_anm_mutants
from .common import load_input_bytes
from .pbg3_campaign import DEFAULT_ARCHIVE as DEFAULT_PBG3_ARCHIVE
from .pbg3_mutants import generate_pbg3_mutants
from .replay import parse_stage_replay_data, replay_stage_action_masks, synthetic_replay_seed, validate_replay
from .replay_mutants import generate_replay_mutants
from .stage_std import parse_stage_std
from .stage_std_campaign import DEFAULT_ARCHIVE as DEFAULT_STAGE_STD_ARCHIVE
from .stage_std_campaign import DEFAULT_ENTRY as DEFAULT_STAGE_STD_ENTRY
from .stage_std_mutants import generate_stage_std_mutants


PARSER_TARGETS = ("pbg3", "replay", "anm", "stage-std")


@dataclass(frozen=True)
class ParserCoverageCase:
    target: str
    name: str
    payload: bytes
    source: str
    generation: int = 0

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-coverage-smoke" / stamp


def _normalize_error_message(message: str) -> str:
    normalized = re.sub(r"0x[0-9A-Fa-f]+", "0xN", message)
    normalized = re.sub(r"(?<![A-Za-z0-9])-?\d+(?![A-Za-z0-9])", "N", normalized)
    return normalized[:160]


def _bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 4:
        return "2-4"
    if value <= 16:
        return "5-16"
    if value <= 64:
        return "17-64"
    if value <= 256:
        return "65-256"
    return "257+"


def _jsonable_counter_keys(mapping: Mapping[object, object] | None, *, limit: int = 12) -> tuple[str, ...]:
    if not isinstance(mapping, Mapping):
        return ()
    return tuple(str(key) for key in sorted(mapping, key=lambda value: str(value))[:limit])


def evaluate_parser_payload(
    target: str,
    payload: bytes,
    *,
    max_script_instructions: int = 4096,
) -> dict[str, object]:
    if target == "pbg3":
        try:
            archive = Pbg3Archive.from_bytes(payload)
        except (Pbg3Error, ValueError) as exc:
            return {
                "classification": "parse-error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        extracted = 0
        extracted_bytes = 0
        try:
            for entry in archive.entries:
                data = archive.extract_entry(entry)
                extracted += 1
                extracted_bytes += len(data)
        except (Pbg3Error, ValueError) as exc:
            return {
                "classification": "extract-error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "entry_count": len(archive.entries),
                "table_offset": archive.table_offset,
                "extracted_before_failure": extracted,
            }
        return {
            "classification": "accepted",
            "entry_count": len(archive.entries),
            "table_offset": archive.table_offset,
            "extracted_entries": extracted,
            "extracted_bytes": extracted_bytes,
        }

    if target == "replay":
        try:
            summary = validate_replay(payload)
            stages = parse_stage_replay_data(payload)
            populated = [index for index, stage_data in enumerate(stages, start=1) if stage_data is not None]
            action_lengths = {
                str(stage): len(replay_stage_action_masks(payload, stage, max_frames=512))
                for stage in populated
            }
            bookmark_counts = {
                str(index): len(stage_data.input_bookmarks)
                for index, stage_data in enumerate(stages, start=1)
                if stage_data is not None
            }
        except ValueError as exc:
            return {
                "classification": "parse-error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        return {
            "classification": "accepted",
            **summary,
            "populated_stages": populated,
            "bookmark_counts": bookmark_counts,
            "bounded_action_lengths": action_lengths,
        }

    if target == "anm":
        try:
            return {
                "classification": "accepted",
                **parse_anm(payload, max_script_instructions=max_script_instructions),
            }
        except ValueError as exc:
            return {
                "classification": "parse-error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

    if target == "stage-std":
        try:
            return {
                "classification": "accepted",
                **parse_stage_std(payload, max_script_instructions=max_script_instructions),
            }
        except ValueError as exc:
            return {
                "classification": "parse-error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

    raise ValueError(f"unknown parser target: {target}")


def coverage_signature(target: str, evaluation: Mapping[str, object]) -> tuple[object, ...]:
    classification = str(evaluation.get("classification"))
    if classification != "accepted":
        return (
            target,
            classification,
            evaluation.get("error_type"),
            _normalize_error_message(str(evaluation.get("error_message", ""))),
        )

    if target == "pbg3":
        return (
            target,
            classification,
            _bucket(int(evaluation.get("entry_count", 0))),
            _bucket(int(evaluation.get("extracted_bytes", 0))),
        )
    if target == "replay":
        action_lengths = evaluation.get("bounded_action_lengths")
        return (
            target,
            classification,
            tuple(evaluation.get("populated_stages", ())),
            tuple(sorted((evaluation.get("bookmark_counts") or {}).items())),  # type: ignore[union-attr]
            tuple(sorted(action_lengths.items())) if isinstance(action_lengths, Mapping) else (),
        )
    if target == "anm":
        scripts = evaluation.get("scripts")
        stop_reasons: tuple[str, ...] = ()
        if isinstance(scripts, list):
            stop_reasons = tuple(
                str(script.get("stop_reason"))
                for script in scripts[:16]
                if isinstance(script, Mapping)
            )
        return (
            target,
            classification,
            _bucket(int(evaluation.get("num_sprites", 0))),
            _bucket(int(evaluation.get("num_scripts", 0))),
            _bucket(int(evaluation.get("total_instructions", 0))),
            bool(evaluation.get("script_offsets_increasing")),
            _jsonable_counter_keys(evaluation.get("opcode_histogram") if isinstance(evaluation, Mapping) else None),
            stop_reasons,
        )
    if target == "stage-std":
        return (
            target,
            classification,
            _bucket(int(evaluation.get("nb_objects", 0))),
            _bucket(int(evaluation.get("nb_faces", 0))),
            _bucket(int(evaluation.get("quad_count_walked", 0))),
            _bucket(int(evaluation.get("script_instructions", 0))),
            evaluation.get("script_stop_reason"),
        )
    raise ValueError(f"unknown parser target: {target}")


def _case(target: str, name: str, payload: bytes, source: str, *, generation: int = 0) -> ParserCoverageCase:
    return ParserCoverageCase(target=target, name=name, payload=payload, source=source, generation=generation)


def initial_cases_for_target(target: str, seed_payload: bytes, *, mutation_limit: int = 32) -> list[ParserCoverageCase]:
    cases = [_case(target, "seed", seed_payload, "seed")]
    if target == "pbg3":
        mutants = generate_pbg3_mutants(seed_payload)[:mutation_limit]
        cases.extend(_case(target, mutant.name, mutant.payload, mutant.source) for mutant in mutants)
    elif target == "replay":
        mutants = generate_replay_mutants(seed_payload)[:mutation_limit]
        cases.extend(_case(target, mutant.name, mutant.payload, mutant.source) for mutant in mutants)
    elif target == "anm":
        mutants = generate_anm_mutants(seed_payload)[:mutation_limit]
        cases.extend(_case(target, mutant.name, mutant.payload, mutant.source) for mutant in mutants)
    elif target == "stage-std":
        mutants = generate_stage_std_mutants(seed_payload)[:mutation_limit]
        cases.extend(_case(target, mutant.name, mutant.payload, mutant.source) for mutant in mutants)
    else:
        raise ValueError(f"unknown parser target: {target}")
    return cases


def _anchor_offsets(payload: bytes) -> tuple[int, ...]:
    if not payload:
        return (0,)
    anchors = {
        0,
        min(1, len(payload) - 1),
        len(payload) // 4,
        len(payload) // 2,
        (len(payload) * 3) // 4,
        len(payload) - 1,
    }
    return tuple(sorted(offset for offset in anchors if 0 <= offset < len(payload)))


def _feedback_mutations(case: ParserCoverageCase, *, per_case_limit: int = 8) -> list[ParserCoverageCase]:
    payload = case.payload
    mutations: list[ParserCoverageCase] = []
    for offset in _anchor_offsets(payload):
        if payload:
            flipped = bytearray(payload)
            flipped[offset] ^= 0xFF
            mutations.append(
                _case(
                    case.target,
                    f"{case.name}-flip-{offset}",
                    bytes(flipped),
                    "coverage-feedback",
                    generation=case.generation + 1,
                )
            )
            zeroed = bytearray(payload)
            zeroed[offset] = 0
            mutations.append(
                _case(
                    case.target,
                    f"{case.name}-zero-{offset}",
                    bytes(zeroed),
                    "coverage-feedback",
                    generation=case.generation + 1,
                )
            )
        truncation = payload[:offset]
        mutations.append(
            _case(
                case.target,
                f"{case.name}-truncate-{offset}",
                truncation,
                "coverage-feedback",
                generation=case.generation + 1,
            )
        )
        if len(mutations) >= per_case_limit:
            break
    if payload:
        mutations.append(
            _case(
                case.target,
                f"{case.name}-append-garbage",
                payload + b"\xA5" * 16,
                "coverage-feedback",
                generation=case.generation + 1,
            )
        )
    return mutations[:per_case_limit]


def run_parser_coverage_smoke(
    seeds: Mapping[str, bytes],
    *,
    targets: Sequence[str] = PARSER_TARGETS,
    max_evaluations: int = 256,
    mutation_limit: int = 32,
    max_generation: int = 1,
    max_script_instructions: int = 4096,
) -> dict[str, object]:
    queue: deque[ParserCoverageCase] = deque()
    for target in targets:
        if target not in PARSER_TARGETS:
            raise ValueError(f"unknown parser target: {target}")
        queue.extend(initial_cases_for_target(target, seeds[target], mutation_limit=mutation_limit))

    seen_payloads: set[tuple[str, str]] = set()
    seen_signatures: set[tuple[object, ...]] = set()
    selected: list[dict[str, object]] = []
    summary: list[dict[str, object]] = []
    classification_counts: Counter[str] = Counter()
    signature_counts: Counter[str] = Counter()
    evaluations = 0

    while queue and evaluations < max_evaluations:
        case = queue.popleft()
        payload_key = (case.target, case.sha256)
        if payload_key in seen_payloads:
            continue
        seen_payloads.add(payload_key)
        evaluation = evaluate_parser_payload(
            case.target,
            case.payload,
            max_script_instructions=max_script_instructions,
        )
        signature = coverage_signature(case.target, evaluation)
        signature_key = json.dumps(signature, sort_keys=True, default=str)
        is_new = signature not in seen_signatures
        if is_new:
            seen_signatures.add(signature)
            selected.append(
                {
                    "target": case.target,
                    "case_name": case.name,
                    "source": case.source,
                    "generation": case.generation,
                    "payload_size": len(case.payload),
                    "payload_sha256": case.sha256,
                    "coverage_signature": signature,
                    "evaluation": evaluation,
                }
            )
            signature_counts[case.target] += 1
            if case.generation < max_generation:
                queue.extend(_feedback_mutations(case))
        classification_counts[f"{case.target}:{evaluation.get('classification')}"] += 1
        summary.append(
            {
                "target": case.target,
                "case_name": case.name,
                "source": case.source,
                "generation": case.generation,
                "payload_size": len(case.payload),
                "payload_sha256": case.sha256,
                "coverage_signature": signature,
                "coverage_signature_key": signature_key,
                "new_coverage": is_new,
                "classification": evaluation.get("classification"),
                "error_type": evaluation.get("error_type"),
                "error_message": evaluation.get("error_message"),
            }
        )
        evaluations += 1

    return {
        "schema": "danmakufuzz-parser-coverage-smoke-v1",
        "targets": list(targets),
        "evaluations": evaluations,
        "max_evaluations": max_evaluations,
        "unique_coverage_signatures": len(seen_signatures),
        "unique_coverage_by_target": dict(sorted(signature_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "selected": selected,
        "summary": summary,
    }


def _parse_targets(raw_targets: str) -> tuple[str, ...]:
    targets = tuple(target.strip() for target in raw_targets.split(",") if target.strip())
    if not targets:
        raise ValueError("at least one parser target is required")
    unknown = sorted(set(targets) - set(PARSER_TARGETS))
    if unknown:
        raise ValueError(f"unknown parser target(s): {unknown}")
    return targets


def _load_default_seeds(
    targets: Iterable[str],
    *,
    replay_input: Path | None,
) -> dict[str, bytes]:
    seeds: dict[str, bytes] = {}
    for target in targets:
        if target == "pbg3":
            seeds[target] = DEFAULT_PBG3_ARCHIVE.read_bytes()
        elif target == "replay":
            seeds[target] = replay_input.resolve().read_bytes() if replay_input is not None else synthetic_replay_seed()
        elif target == "anm":
            seeds[target], _ = load_input_bytes(
                input_path=None,
                archive_path=DEFAULT_ANM_ARCHIVE,
                entry_name=DEFAULT_ANM_ENTRY,
            )
        elif target == "stage-std":
            seeds[target], _ = load_input_bytes(
                input_path=None,
                archive_path=DEFAULT_STAGE_STD_ARCHIVE,
                entry_name=DEFAULT_STAGE_STD_ENTRY,
            )
        else:
            raise ValueError(f"unknown parser target: {target}")
    return seeds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run lightweight coverage-guided smoke fuzzing over local parser targets."
    )
    parser.add_argument("--targets", default=",".join(PARSER_TARGETS))
    parser.add_argument("--replay-input", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--max-evaluations", type=int, default=256)
    parser.add_argument("--mutation-limit", type=int, default=32)
    parser.add_argument("--max-generation", type=int, default=1)
    parser.add_argument("--max-script-instructions", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = _parse_targets(args.targets)
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)
    seeds = _load_default_seeds(targets, replay_input=args.replay_input)
    report = run_parser_coverage_smoke(
        seeds,
        targets=targets,
        max_evaluations=max(1, int(args.max_evaluations)),
        mutation_limit=max(1, int(args.mutation_limit)),
        max_generation=max(0, int(args.max_generation)),
        max_script_instructions=max(1, int(args.max_script_instructions)),
    )
    summary_path = artifact_dir / "summary.jsonl"
    with summary_path.open("w", encoding="utf-8") as handle:
        for item in report["summary"]:  # type: ignore[index]
            handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    report["artifact_dir"] = str(artifact_dir)
    report["summary"] = str(summary_path.resolve())
    report["seed_sha256"] = {target: sha256_bytes(payload) for target, payload in seeds.items()}
    (artifact_dir / "campaign.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
