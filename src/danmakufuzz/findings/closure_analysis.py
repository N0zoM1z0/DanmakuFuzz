from __future__ import annotations

import argparse
import ctypes
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any

from ..corpus.pbg3 import Pbg3Archive
from ..ecl_ir.model import EclFile, TimelineInstruction
from ..ecl_ir.parser import parse_ecl
from ..ecl_ir.serializer import EclSerializeError, serialize_ecl_canonical
from ..parser.anm import AnmRawEntry, DEFAULT_ARCHIVE, parse_anm
from ..reduction import ddmin_sequence, first_prefix_divergence
from ..repo import ARTIFACTS_DIR, FINDINGS_DIR, REFERENCE_DIR, REPO_ROOT, ensure_directory


DEFAULT_ARTIFACT_DIR = ARTIFACTS_DIR / "checks" / "finding-closure-confirmed-20260823"
ECL_FINDING_DIR = FINDINGS_DIR / "semantic" / "ecl-timeline-arg0-retail-crash-stall-basin"
ANM_FINDING_DIR = FINDINGS_DIR / "runtime" / "anm-stage6bg-retail-crash-basin"

TRACE_STATE_SCALAR_FIELDS = (
    "terminal_reason",
    "supervisor_state",
    "stage",
    "game_frame",
    "rng_generation",
    "lives",
    "bombs",
    "score",
    "power",
    "point_items_stage",
    "point_items_total",
)
TRACE_STATE_MAPPING_FIELDS = {
    "player": ("x", "y", "state"),
    "stage_vm": (
        "loaded",
        "script_time",
        "instruction_index",
        "unpause_flag",
        "spellcard_state",
        "spellcard_ticks",
    ),
    "ecl_timeline": ("time", "next_time"),
    "anm_metrics": (
        "load_anm_calls",
        "load_anm_failures",
        "texture_load_failures",
        "alpha_texture_load_failures",
        "texture_size_mismatches",
        "sprites_loaded",
        "suspicious_sprites_loaded",
        "scripts_loaded",
        "set_active_sprite_failures",
        "execute_script_calls",
        "script_instruction_steps",
        "vm_non_finite",
        "suspicious_sprite_draws",
    ),
}
TRACE_COUNT_FIELDS = ("bullets", "enemies", "items", "lasers")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _jsonable_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"length": len(value), "sha256": sha256_bytes(value)}
    return value


def _load_trace_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def trace_state_projection(record: dict[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for field in TRACE_STATE_SCALAR_FIELDS:
        if field in record:
            projection[field] = record[field]
    for key, fields in TRACE_STATE_MAPPING_FIELDS.items():
        value = record.get(key)
        if isinstance(value, dict):
            projection[key] = {field: value.get(field) for field in fields if field in value}
    for key in TRACE_COUNT_FIELDS:
        value = record.get(key)
        if isinstance(value, list):
            projection[f"{key}_count"] = len(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            projection[f"{key}_count"] = value
    return projection


def _diff_paths(left: Any, right: Any, *, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_diff_paths(left.get(key), right.get(key), prefix=child_prefix))
        return paths
    if left != right:
        return [prefix or "$"]
    return []


def _trace_record_summary(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    summary = {
        "tick": record.get("tick"),
        "game_frame": record.get("game_frame"),
        "terminal_reason": record.get("terminal_reason"),
    }
    for key in ("stage_vm", "ecl_timeline", "anm_metrics"):
        value = record.get(key)
        if isinstance(value, dict):
            summary[key] = value
    return summary


def _headless_temporal_markers(result: dict[str, Any]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    findings = result.get("findings")
    if not isinstance(findings, list):
        return markers
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        detail = finding.get("detail")
        if not isinstance(detail, str):
            continue
        marker: dict[str, Any] = {
            "kind": finding.get("kind"),
            "detail": detail,
        }
        tick_match = re.search(r"\btick\s+(\d+)\b", detail)
        if tick_match:
            marker["tick"] = int(tick_match.group(1))
        baseline_tick_match = re.search(r"\bbaseline_tick=(\d+)\b", detail)
        if baseline_tick_match:
            marker["baseline_tick"] = int(baseline_tick_match.group(1))
        case_tick_match = re.search(r"\bcase_tick=(\d+)\b", detail)
        if case_tick_match:
            marker["case_tick"] = int(case_tick_match.group(1))
        if any(key in marker for key in ("tick", "baseline_tick", "case_tick")):
            markers.append(marker)
    return markers


def first_temporal_divergence(
    baseline_records: list[dict[str, Any]],
    case_records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    index = first_prefix_divergence(
        baseline_records,
        case_records,
        project=trace_state_projection,
    )
    if index is None:
        return None
    baseline_record = baseline_records[index] if index < len(baseline_records) else None
    case_record = case_records[index] if index < len(case_records) else None
    if baseline_record is None or case_record is None:
        return {
            "line": index + 1,
            "baseline_tick": baseline_record.get("tick") if baseline_record is not None else None,
            "case_tick": case_record.get("tick") if case_record is not None else None,
            "baseline_game_frame": baseline_record.get("game_frame") if baseline_record is not None else None,
            "case_game_frame": case_record.get("game_frame") if case_record is not None else None,
            "fields": ["trace_length"],
            "field_count": 1,
            "baseline_length": len(baseline_records),
            "case_length": len(case_records),
            "baseline": trace_state_projection(baseline_record) if baseline_record is not None else None,
            "case": trace_state_projection(case_record) if case_record is not None else None,
        }
    baseline_projection = trace_state_projection(baseline_record) if baseline_record is not None else None
    case_projection = trace_state_projection(case_record) if case_record is not None else None
    fields = _diff_paths(baseline_projection, case_projection)
    return {
        "line": index + 1,
        "baseline_tick": baseline_record.get("tick") if baseline_record is not None else None,
        "case_tick": case_record.get("tick") if case_record is not None else None,
        "baseline_game_frame": baseline_record.get("game_frame") if baseline_record is not None else None,
        "case_game_frame": case_record.get("game_frame") if case_record is not None else None,
        "fields": fields[:32],
        "field_count": len(fields),
        "baseline": baseline_projection,
        "case": case_projection,
    }


def _find_baseline_trace(result_path: Path, result: dict[str, Any]) -> Path | None:
    explicit = result.get("baseline_trace")
    if isinstance(explicit, str) and Path(explicit).is_file():
        return Path(explicit).resolve()

    campaign_path = result_path.parent.parent / "campaign.json"
    if campaign_path.is_file():
        campaign = _load_json(campaign_path)
        baseline = campaign.get("baseline")
        if isinstance(baseline, dict):
            trace = baseline.get("trace")
            if isinstance(trace, str) and Path(trace).is_file():
                return Path(trace).resolve()

    candidates = (
        result_path.parent.parent / "_baseline" / "trace.jsonl",
        result_path.parent.parent / "baseline" / "trace.jsonl",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _trace_summary_for_result(result_path: Path | None, result: dict[str, Any]) -> dict[str, Any]:
    trace_value = result.get("trace")
    trace_path = Path(trace_value) if isinstance(trace_value, str) else None
    case_records = _load_trace_records(trace_path) if trace_path is not None and trace_path.is_file() else []
    baseline_trace = _find_baseline_trace(result_path, result) if result_path is not None else None
    baseline_records = _load_trace_records(baseline_trace) if baseline_trace is not None else []
    divergence = (
        first_temporal_divergence(baseline_records, case_records)
        if baseline_records and case_records
        else None
    )
    status = "baseline-divergence-located" if divergence is not None else "no-divergence"
    if not case_records:
        status = "case-trace-missing"
    elif baseline_trace is None:
        status = "baseline-trace-missing"
    return {
        "status": status,
        "case_trace": str(trace_path.resolve()) if trace_path is not None and trace_path.is_file() else None,
        "case_trace_lines": len(case_records),
        "case_terminal": _trace_record_summary(case_records[-1] if case_records else None),
        "baseline_trace": str(baseline_trace) if baseline_trace is not None else None,
        "baseline_trace_lines": len(baseline_records),
        "baseline_terminal": _trace_record_summary(baseline_records[-1] if baseline_records else None),
        "first_divergence": divergence,
        "headless_temporal_markers": _headless_temporal_markers(result),
    }


def describe_ecl_semantic_deltas(original: EclFile, mutant: EclFile) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    if original.sub_count != mutant.sub_count:
        deltas.append(
            {
                "domain": "ecl",
                "kind": "header-field",
                "field": "sub_count",
                "original": original.sub_count,
                "mutated": mutant.sub_count,
            }
        )
    if original.main_count != mutant.main_count:
        deltas.append(
            {
                "domain": "ecl",
                "kind": "header-field",
                "field": "main_count",
                "original": original.main_count,
                "mutated": mutant.main_count,
            }
        )

    for index in range(max(len(original.timeline), len(mutant.timeline))):
        if index >= len(original.timeline) or index >= len(mutant.timeline):
            deltas.append(
                {
                    "domain": "ecl",
                    "kind": "timeline-structural",
                    "timeline_index": index,
                    "original_present": index < len(original.timeline),
                    "mutated_present": index < len(mutant.timeline),
                }
            )
            continue
        old = original.timeline[index]
        new = mutant.timeline[index]
        for field in ("time", "arg0", "opcode", "size", "args"):
            old_value = getattr(old, field)
            new_value = getattr(new, field)
            if old_value != new_value:
                deltas.append(
                    {
                        "domain": "ecl",
                        "kind": "timeline-field",
                        "timeline_index": index,
                        "field": field,
                        "original": _jsonable_value(old_value),
                        "mutated": _jsonable_value(new_value),
                        "instruction": {
                            "original_time": old.time,
                            "mutated_time": new.time,
                            "original_arg0": old.arg0,
                            "mutated_arg0": new.arg0,
                            "original_opcode": old.opcode,
                            "mutated_opcode": new.opcode,
                            "original_size": old.size,
                            "mutated_size": new.size,
                        },
                    }
                )

    for sub_index in range(max(len(original.subs), len(mutant.subs))):
        if sub_index >= len(original.subs) or sub_index >= len(mutant.subs):
            deltas.append(
                {
                    "domain": "ecl",
                    "kind": "sub-structural",
                    "sub_index": sub_index,
                    "original_present": sub_index < len(original.subs),
                    "mutated_present": sub_index < len(mutant.subs),
                }
            )
            continue
        old_sub = original.subs[sub_index]
        new_sub = mutant.subs[sub_index]
        for instruction_index in range(max(len(old_sub.instructions), len(new_sub.instructions))):
            if instruction_index >= len(old_sub.instructions) or instruction_index >= len(new_sub.instructions):
                deltas.append(
                    {
                        "domain": "ecl",
                        "kind": "sub-instruction-structural",
                        "sub_index": sub_index,
                        "instruction_index": instruction_index,
                        "original_present": instruction_index < len(old_sub.instructions),
                        "mutated_present": instruction_index < len(new_sub.instructions),
                    }
                )
                continue
            old = old_sub.instructions[instruction_index]
            new = new_sub.instructions[instruction_index]
            for field in (
                "time",
                "opcode",
                "offset_to_next",
                "unk8",
                "skip_for_difficulty",
                "unk_a",
                "unk_b",
                "args",
            ):
                old_value = getattr(old, field)
                new_value = getattr(new, field)
                if old_value != new_value:
                    deltas.append(
                        {
                            "domain": "ecl",
                            "kind": "sub-instruction-field",
                            "sub_index": sub_index,
                            "instruction_index": instruction_index,
                            "field": field,
                            "original": _jsonable_value(old_value),
                            "mutated": _jsonable_value(new_value),
                        }
                    )
    return deltas


def apply_ecl_timeline_delta(original_payload: bytes, delta: dict[str, Any]) -> bytes:
    if delta.get("kind") != "timeline-field":
        raise ValueError(f"unsupported ECL delta kind for rebuild: {delta.get('kind')!r}")
    field = delta.get("field")
    if field not in {"time", "arg0", "opcode", "size"}:
        raise ValueError(f"unsupported ECL timeline field for rebuild: {field!r}")
    index = int(delta["timeline_index"])
    ecl = parse_ecl(original_payload).clone()
    if not 0 <= index < len(ecl.timeline):
        raise IndexError(f"timeline index outside original ECL: {index}")
    old = ecl.timeline[index]
    values = {
        "time": old.time,
        "arg0": old.arg0,
        "opcode": old.opcode,
        "size": old.size,
        "args": old.args,
    }
    values[str(field)] = int(delta["mutated"])
    ecl.timeline[index] = TimelineInstruction(**values)
    return serialize_ecl_canonical(ecl)


def _select_ecl_target_delta(
    deltas: list[dict[str, Any]],
    case: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any] | None:
    metadata = result.get("mutation_metadata")
    sites = result.get("sites")
    site_index: int | None = None
    if isinstance(metadata, dict):
        metadata_sites = metadata.get("sites")
        if isinstance(metadata_sites, list) and metadata_sites and isinstance(metadata_sites[0], dict):
            raw_index = metadata_sites[0].get("instruction_index")
            if isinstance(raw_index, int):
                site_index = raw_index
    if site_index is None and isinstance(sites, list) and sites and isinstance(sites[0], dict):
        raw_index = sites[0].get("instruction_index")
        if isinstance(raw_index, int):
            site_index = raw_index

    field = metadata.get("field_name") if isinstance(metadata, dict) else None
    value = metadata.get("value") if isinstance(metadata, dict) else None
    if value is None:
        value = case.get("timeline_arg0")

    for delta in deltas:
        if delta.get("kind") != "timeline-field":
            continue
        if site_index is not None and delta.get("timeline_index") != site_index:
            continue
        if isinstance(field, str) and delta.get("field") != field:
            continue
        if value is not None and delta.get("mutated") != value:
            continue
        return delta
    return None


def _same_delta_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = (
        "domain",
        "kind",
        "field",
        "timeline_index",
        "sub_index",
        "instruction_index",
        "table",
        "index",
        "byte_offset",
        "mutated",
    )
    return all(left.get(key) == right.get(key) for key in keys)


def _reduce_to_target_delta(
    deltas: list[dict[str, Any]],
    target_delta: dict[str, Any] | None,
) -> dict[str, Any]:
    if target_delta is None:
        return {
            "status": "target-delta-missing",
            "semantic_delta_count": len(deltas),
            "minimized_delta_count": None,
            "evaluations": 0,
            "history": [],
            "minimized_deltas": [],
        }

    def predicate(candidate: tuple[dict[str, Any], ...]) -> bool:
        return any(_same_delta_identity(delta, target_delta) for delta in candidate)

    reduction = ddmin_sequence(deltas, predicate, min_size=1)
    status = "single-semantic-delta" if len(reduction.items) == 1 and predicate(reduction.items) else "not-minimized"
    return {
        "status": status,
        "semantic_delta_count": len(deltas),
        "minimized_delta_count": len(reduction.items),
        "evaluations": reduction.evaluations,
        "exhausted_budget": reduction.exhausted_budget,
        "history": list(reduction.history),
        "minimized_deltas": list(reduction.items),
    }


def _override_payload(result: dict[str, Any], payload_name: str) -> bytes:
    override_dir = result.get("override_dir")
    if not isinstance(override_dir, str):
        raise ValueError("source result is missing override_dir")
    path = Path(override_dir) / "data" / payload_name
    return path.read_bytes()


def _case_source_result_path(case: dict[str, Any]) -> Path | None:
    value = case.get("source_result") or case.get("source_result_artifact")
    if not isinstance(value, str):
        return None
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve() if path.is_file() else None


def _ecl_seed_name(case: dict[str, Any]) -> str:
    return str(case.get("seed_name") or f"ecldata{case['stage']}.ecl")


def _build_ecl_mutant_payload(original_payload: bytes, case: dict[str, Any]) -> bytes:
    ecl = parse_ecl(original_payload).clone()
    index = int(case["timeline_index"])
    old = ecl.timeline[index]
    ecl.timeline[index] = TimelineInstruction(
        time=old.time,
        arg0=int(case["timeline_arg0"]),
        opcode=old.opcode,
        size=old.size,
        args=old.args,
    )
    return serialize_ecl_canonical(ecl)


def _synthetic_ecl_result(case: dict[str, Any], seed_name: str) -> dict[str, Any]:
    index = int(case["timeline_index"])
    return {
        "case_name": case.get("name"),
        "mutant_name": f"timeline-arg0-{case.get('timeline_arg0')}",
        "seed_name": seed_name,
        "payload_sha256": case.get("payload_sha256"),
        "mutation_metadata": {
            "family": "timeline-arg0",
            "field_name": "arg0",
            "value": case.get("timeline_arg0"),
            "site_key": f"tl{index:04d}",
            "sites": [{"site_kind": "timeline", "instruction_index": index}],
        },
        "sites": [{"site_kind": "timeline", "instruction_index": index}],
        "findings": [],
    }


def _analyze_ecl_case(case: dict[str, Any]) -> dict[str, Any]:
    result_path = _case_source_result_path(case)
    seed_name = _ecl_seed_name(case)
    result = _load_json(result_path) if result_path is not None else _synthetic_ecl_result(case, seed_name)
    original_path = REFERENCE_DIR / "corpus" / "ecl" / "original" / seed_name
    original_payload = original_path.read_bytes()
    mutant_payload = _override_payload(result, seed_name) if result_path is not None else _build_ecl_mutant_payload(original_payload, case)

    original = parse_ecl(original_payload)
    mutant = parse_ecl(mutant_payload)
    deltas = describe_ecl_semantic_deltas(original, mutant)
    target_delta = _select_ecl_target_delta(deltas, case, result)
    reducer = _reduce_to_target_delta(deltas, target_delta)

    rebuild: dict[str, Any]
    if target_delta is None:
        rebuild = {"status": "skipped-target-delta-missing"}
    else:
        try:
            rebuilt_payload = apply_ecl_timeline_delta(original_payload, target_delta)
            rebuild = {
                "status": "matched" if sha256_bytes(rebuilt_payload) == case["payload_sha256"] else "sha256-mismatch",
                "payload_sha256": sha256_bytes(rebuilt_payload),
                "matches_case_payload_sha256": sha256_bytes(rebuilt_payload) == case["payload_sha256"],
            }
        except (EclSerializeError, ValueError, IndexError) as exc:
            rebuild = {"status": "failed", "error": str(exc)}

    model = {
        "domain": "ecl-timeline-vm",
        "stage": case.get("stage"),
        "seed_name": seed_name,
        "site_key": result.get("mutation_metadata", {}).get("site_key")
        if isinstance(result.get("mutation_metadata"), dict)
        else None,
        "target_delta": target_delta,
        "classification": case.get("classification"),
        "retail_signature_key": case.get("retail_signature_key"),
        "headless_findings": result.get("findings"),
    }
    if target_delta is not None and target_delta.get("kind") == "timeline-field":
        index = int(target_delta["timeline_index"])
        original_instruction = original.timeline[index]
        model["timeline_instruction"] = {
            "index": index,
            "time": original_instruction.time,
            "arg0": original_instruction.arg0,
            "opcode": original_instruction.opcode,
            "size": original_instruction.size,
        }

    return {
        "schema": "danmakufuzz-finding-closure-case-v1",
        "finding": "semantic/ecl-timeline-arg0-retail-crash-stall-basin",
        "case": case.get("name"),
        "source_result": str(result_path.resolve()) if result_path is not None else None,
        "source_result_status": "loaded" if result_path is not None else "rebuilt-from-case-recipe",
        "payload_sha256": sha256_bytes(mutant_payload),
        "payload_sha256_matches_metadata": sha256_bytes(mutant_payload) == case["payload_sha256"],
        "original_payload_sha256": sha256_bytes(original_payload),
        "semantic_delta_count": len(deltas),
        "semantic_deltas": deltas,
        "reducer": reducer,
        "rebuild": rebuild,
        "model": model,
        "temporal_bisection": _trace_summary_for_result(result_path, result),
    }


def _anm_layout(data: bytes) -> dict[str, int]:
    if len(data) < ctypes.sizeof(AnmRawEntry):
        raise ValueError("ANM payload is smaller than AnmRawEntry")
    entry = AnmRawEntry.from_buffer_copy(data)
    num_sprites = int(entry.numSprites)
    num_scripts = int(entry.numScripts)
    if num_sprites < 0 or num_scripts < 0:
        raise ValueError("ANM header has negative table counts")
    header_size = ctypes.sizeof(AnmRawEntry)
    sprite_table_offset = header_size
    script_table_offset = sprite_table_offset + num_sprites * 4
    if script_table_offset + num_scripts * 8 > len(data):
        raise ValueError("ANM tables are truncated")
    return {
        "header_size": header_size,
        "num_sprites": num_sprites,
        "num_scripts": num_scripts,
        "sprite_table_offset": sprite_table_offset,
        "script_table_offset": script_table_offset,
    }


def describe_anm_table_deltas(original_payload: bytes, mutant_payload: bytes) -> list[dict[str, Any]]:
    original_layout = _anm_layout(original_payload)
    mutant_layout = _anm_layout(mutant_payload)
    deltas: list[dict[str, Any]] = []
    for field in ("num_sprites", "num_scripts"):
        if original_layout[field] != mutant_layout[field]:
            deltas.append(
                {
                    "domain": "anm",
                    "kind": "header-field",
                    "field": field,
                    "original": original_layout[field],
                    "mutated": mutant_layout[field],
                }
            )
    for index in range(min(original_layout["num_sprites"], mutant_layout["num_sprites"])):
        byte_offset = original_layout["sprite_table_offset"] + index * 4
        original_value = struct.unpack_from("<I", original_payload, byte_offset)[0]
        mutant_value = struct.unpack_from("<I", mutant_payload, byte_offset)[0]
        if original_value != mutant_value:
            deltas.append(
                {
                    "domain": "anm",
                    "kind": "table-u32",
                    "table": "sprite_offsets",
                    "index": index,
                    "field": "offset",
                    "byte_offset": byte_offset,
                    "original": original_value,
                    "mutated": mutant_value,
                }
            )
    for index in range(min(original_layout["num_scripts"], mutant_layout["num_scripts"])):
        entry_offset = original_layout["script_table_offset"] + index * 8
        for field, relative_offset in (("id", 0), ("first_instruction", 4)):
            byte_offset = entry_offset + relative_offset
            original_value = struct.unpack_from("<I", original_payload, byte_offset)[0]
            mutant_value = struct.unpack_from("<I", mutant_payload, byte_offset)[0]
            if original_value != mutant_value:
                deltas.append(
                    {
                        "domain": "anm",
                        "kind": "table-u32",
                        "table": "script_entries",
                        "index": index,
                        "field": field,
                        "byte_offset": byte_offset,
                        "original": original_value,
                        "mutated": mutant_value,
                    }
                )
    return deltas


def apply_anm_table_delta(original_payload: bytes, delta: dict[str, Any]) -> bytes:
    if delta.get("kind") != "table-u32":
        raise ValueError(f"unsupported ANM delta kind for rebuild: {delta.get('kind')!r}")
    byte_offset = int(delta["byte_offset"])
    output = bytearray(original_payload)
    struct.pack_into("<I", output, byte_offset, int(delta["mutated"]))
    return bytes(output)


def _changed_byte_ranges(left: bytes, right: bytes) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    index = 0
    limit = min(len(left), len(right))
    while index < limit:
        if left[index] == right[index]:
            index += 1
            continue
        start = index
        while index < limit and left[index] != right[index]:
            index += 1
        ranges.append({"start": start, "stop": index, "length": index - start})
    if len(left) != len(right):
        ranges.append({"start": limit, "stop": max(len(left), len(right)), "length": abs(len(left) - len(right))})
    return ranges


def _select_anm_target_delta(deltas: list[dict[str, Any]], case: dict[str, Any]) -> dict[str, Any] | None:
    mutant_name = case.get("mutant_name") or case.get("name")
    expectations = {
        "first-sprite-offset-zero": ("sprite_offsets", 0, "offset", 0),
        "first-script-id-ffff": ("script_entries", 0, "id", 65535),
        "first-script-offset-zero": ("script_entries", 0, "first_instruction", 0),
    }
    expected = expectations.get(str(mutant_name))
    if expected is None and len(deltas) == 1:
        return deltas[0]
    for delta in deltas:
        if (
            expected is not None
            and delta.get("table") == expected[0]
            and delta.get("index") == expected[1]
            and delta.get("field") == expected[2]
            and delta.get("mutated") == expected[3]
        ):
            return delta
    return None


def _load_anm_original(entry_name: str, archive_path: Path) -> bytes:
    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    return archive.extract(entry_name)


def _build_anm_mutant_payload(original_payload: bytes, case: dict[str, Any]) -> bytes:
    mutation = case.get("mutation")
    if not isinstance(mutation, dict):
        raise ValueError(f"ANM case is missing mutation recipe: {case.get('name')}")
    table = mutation.get("table")
    index = int(mutation["index"])
    field = mutation.get("field")
    entry = AnmRawEntry.from_buffer_copy(original_payload)
    header_size = ctypes.sizeof(AnmRawEntry)
    if table == "sprite_offsets" and field == "offset":
        byte_offset = header_size + index * 4
    elif table == "script_entries" and field in {"id", "first_instruction"}:
        script_table_offset = header_size + int(entry.numSprites) * 4
        byte_offset = script_table_offset + index * 8 + (4 if field == "first_instruction" else 0)
    else:
        raise ValueError(f"unsupported ANM mutation recipe: {mutation!r}")
    output = bytearray(original_payload)
    struct.pack_into("<I", output, byte_offset, int(mutation["value"]))
    return bytes(output)


def _analyze_anm_case(case: dict[str, Any], original_payload: bytes) -> dict[str, Any]:
    result_path = _case_source_result_path(case)
    result = _load_json(result_path) if result_path is not None else {
        "case_name": case.get("name"),
        "mutant_name": case.get("mutant_name"),
        "entry_name": case.get("entry_name"),
        "payload_sha256": case.get("payload_sha256"),
        "findings": [],
        "target_hits": [],
    }
    entry_name = str(case.get("entry_name") or result.get("entry_name") or "stg6bg.anm")
    mutant_payload = _override_payload(result, entry_name) if result_path is not None else _build_anm_mutant_payload(original_payload, case)
    deltas = describe_anm_table_deltas(original_payload, mutant_payload)
    target_delta = _select_anm_target_delta(deltas, case)
    reducer = _reduce_to_target_delta(deltas, target_delta)
    byte_ranges = _changed_byte_ranges(original_payload, mutant_payload)

    if target_delta is None:
        rebuild = {"status": "skipped-target-delta-missing"}
    else:
        rebuilt_payload = apply_anm_table_delta(original_payload, target_delta)
        rebuild = {
            "status": "matched" if sha256_bytes(rebuilt_payload) == case["payload_sha256"] else "sha256-mismatch",
            "payload_sha256": sha256_bytes(rebuilt_payload),
            "matches_case_payload_sha256": sha256_bytes(rebuilt_payload) == case["payload_sha256"],
        }

    parser_evaluation = result.get("parser_evaluation")
    model = {
        "domain": "anm-stage6-resource-loader",
        "entry_name": entry_name,
        "stage": case.get("stage"),
        "target_delta": target_delta,
        "classification": case.get("classification"),
        "retail_signature_key": case.get("retail_signature_key"),
        "target_hits": result.get("target_hits"),
        "headless_findings": result.get("findings"),
        "parser_changed_fields": parser_evaluation.get("changed_fields")
        if isinstance(parser_evaluation, dict)
        else None,
    }
    if isinstance(parser_evaluation, dict):
        model["parser_shape"] = {
            "num_sprites": parser_evaluation.get("num_sprites"),
            "num_scripts": parser_evaluation.get("num_scripts"),
            "sprite_offsets": parser_evaluation.get("sprite_offsets"),
            "script_entries": parser_evaluation.get("script_entries"),
            "total_instructions": parser_evaluation.get("total_instructions"),
            "opcode_histogram": parser_evaluation.get("opcode_histogram"),
        }
    else:
        model["parser_shape"] = parse_anm(mutant_payload)

    return {
        "schema": "danmakufuzz-finding-closure-case-v1",
        "finding": "runtime/anm-stage6bg-retail-crash-basin",
        "case": case.get("name"),
        "source_result": str(result_path.resolve()) if result_path is not None else None,
        "source_result_status": "loaded" if result_path is not None else "rebuilt-from-case-recipe",
        "payload_sha256": sha256_bytes(mutant_payload),
        "payload_sha256_matches_metadata": sha256_bytes(mutant_payload) == case["payload_sha256"],
        "original_payload_sha256": sha256_bytes(original_payload),
        "semantic_delta_count": len(deltas),
        "semantic_deltas": deltas,
        "raw_changed_byte_ranges": byte_ranges,
        "reducer": reducer,
        "rebuild": rebuild,
        "model": model,
        "temporal_bisection": _trace_summary_for_result(result_path, result),
    }


def _cases_from_finding(finding_dir: Path) -> list[dict[str, Any]]:
    data = _load_json(finding_dir / "cases.json")
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"cases.json is missing a cases list: {finding_dir}")
    return [case for case in cases if isinstance(case, dict)]


def _summary_from_case_rows(kind: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stage_counts = Counter(str(row.get("model", {}).get("stage")) for row in rows)
    classification_counts = Counter(str(row.get("model", {}).get("classification")) for row in rows)
    reducer_counts = Counter(str(row.get("reducer", {}).get("status")) for row in rows)
    temporal_counts = Counter(str(row.get("temporal_bisection", {}).get("status")) for row in rows)
    rebuild_counts = Counter(str(row.get("rebuild", {}).get("status")) for row in rows)
    payload_ok = sum(1 for row in rows if row.get("payload_sha256_matches_metadata") is True)
    single_delta = sum(1 for row in rows if row.get("semantic_delta_count") == 1)

    deltas_by_key: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        reducer = row.get("reducer")
        minimized = reducer.get("minimized_deltas") if isinstance(reducer, dict) else None
        if not isinstance(minimized, list) or not minimized:
            continue
        delta = minimized[0]
        if not isinstance(delta, dict):
            continue
        if kind == "ecl":
            key = f"timeline[{delta.get('timeline_index')}].{delta.get('field')}"
        else:
            key = f"{delta.get('table')}[{delta.get('index')}].{delta.get('field')}"
        deltas_by_key[key].append(str(delta.get("mutated")))

    return {
        "schema": "danmakufuzz-finding-closure-summary-v1",
        "kind": kind,
        "case_count": len(rows),
        "payload_sha256_metadata_matches": payload_ok,
        "single_semantic_delta_cases": single_delta,
        "all_cases_single_semantic_delta": single_delta == len(rows),
        "all_rebuilds_match_case_payload": all(
            row.get("rebuild", {}).get("matches_case_payload_sha256") is True for row in rows
        ),
        "stage_counts": dict(sorted(stage_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "reducer_status_counts": dict(sorted(reducer_counts.items())),
        "rebuild_status_counts": dict(sorted(rebuild_counts.items())),
        "temporal_status_counts": dict(sorted(temporal_counts.items())),
        "minimized_delta_values": {key: sorted(values) for key, values in sorted(deltas_by_key.items())},
    }


def analyze_ecl_finding(
    *,
    finding_dir: Path = ECL_FINDING_DIR,
    output_dir: Path = DEFAULT_ARTIFACT_DIR / "ecl-timeline-arg0",
) -> dict[str, Any]:
    ensure_directory(output_dir)
    rows = [_analyze_ecl_case(case) for case in _cases_from_finding(finding_dir)]
    cases_jsonl = output_dir / "cases.jsonl"
    summary_path = output_dir / "summary.json"
    _write_jsonl(cases_jsonl, rows)
    summary = _summary_from_case_rows("ecl", rows)
    summary["finding"] = "semantic/ecl-timeline-arg0-retail-crash-stall-basin"
    summary["cases_jsonl"] = str(cases_jsonl.resolve())
    _write_json(summary_path, summary)
    return summary


def analyze_anm_finding(
    *,
    finding_dir: Path = ANM_FINDING_DIR,
    output_dir: Path = DEFAULT_ARTIFACT_DIR / "anm-stage6bg",
    archive_path: Path = DEFAULT_ARCHIVE,
) -> dict[str, Any]:
    ensure_directory(output_dir)
    cases = _cases_from_finding(finding_dir)
    entry_name = str(cases[0].get("entry_name", "stg6bg.anm")) if cases else "stg6bg.anm"
    original_payload = _load_anm_original(entry_name, archive_path)
    rows = [_analyze_anm_case(case, original_payload) for case in cases]
    cases_jsonl = output_dir / "cases.jsonl"
    summary_path = output_dir / "summary.json"
    _write_jsonl(cases_jsonl, rows)
    summary = _summary_from_case_rows("anm", rows)
    summary["finding"] = "runtime/anm-stage6bg-retail-crash-basin"
    summary["archive"] = str(archive_path.resolve())
    summary["entry_name"] = entry_name
    summary["cases_jsonl"] = str(cases_jsonl.resolve())
    _write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimize and model confirmed DanmakuFuzz findings.")
    parser.add_argument(
        "--finding",
        choices=("all", "ecl-timeline-arg0", "anm-stage6bg"),
        default="all",
        help="confirmed finding family to close",
    )
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--anm-archive", type=Path, default=DEFAULT_ARCHIVE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output: dict[str, Any] = {
        "schema": "danmakufuzz-finding-closure-run-v1",
        "artifact_dir": str(args.artifact_dir.resolve()),
        "summaries": {},
    }
    if args.finding in {"all", "ecl-timeline-arg0"}:
        output["summaries"]["ecl-timeline-arg0"] = analyze_ecl_finding(
            output_dir=args.artifact_dir / "ecl-timeline-arg0",
        )
    if args.finding in {"all", "anm-stage6bg"}:
        output["summaries"]["anm-stage6bg"] = analyze_anm_finding(
            output_dir=args.artifact_dir / "anm-stage6bg",
            archive_path=args.anm_archive,
        )
    _write_json(args.artifact_dir / "run.json", output)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
