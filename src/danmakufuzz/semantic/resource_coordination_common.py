from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..headless.baseline import DEFAULT_GAME_DIR
from ..interestingness.rules import load_trace_records
from ..repo import ARTIFACTS_DIR


def load_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json object expected: {path}")
    return value


def trace_sha256(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def first_diff_line(
    baseline_records: list[dict[str, Any]],
    case_records: list[dict[str, Any]],
) -> int | None:
    limit = min(len(baseline_records), len(case_records))
    for index in range(limit):
        if baseline_records[index] != case_records[index]:
            return index + 1
    if len(baseline_records) != len(case_records):
        return limit + 1
    return None


def coarse_sink_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    player = record.get("player")
    player_state = player.get("state") if isinstance(player, dict) else None
    return {
        "terminal_reason": record.get("terminal_reason"),
        "supervisor_state": record.get("supervisor_state"),
        "game_frame": record.get("game_frame"),
        "tick": record.get("tick"),
        "player_state": player_state,
        "lives": record.get("lives"),
        "bombs": record.get("bombs"),
        "power": record.get("power"),
        "enemy_count": record.get("enemy_count"),
        "stage_vm": record.get("stage_vm"),
        "ecl_timeline": record.get("ecl_timeline"),
        "boss_ui": record.get("boss_ui"),
        "spellcard": record.get("spellcard"),
    }


def sink_signature_from_records(
    records: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None, int | None]:
    if not records:
        return None, None, None
    sink_record = records[-1]
    snapshot = coarse_sink_snapshot(sink_record)
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), snapshot, sink_record.get("tick") if isinstance(sink_record.get("tick"), int) else None


def result_paths_from_summary_jsonl(path: Path) -> list[Path]:
    discovered: list[Path] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"summary.jsonl entry is not an object: {path}:{line_number}")
            case_name = value.get("case_name")
            if not isinstance(case_name, str):
                raise ValueError(f"summary.jsonl entry is missing case_name: {path}:{line_number}")
            result_path = (path.parent / case_name / "result.json").resolve()
            if not result_path.is_file():
                raise FileNotFoundError(f"summary.jsonl entry points to missing result.json: {result_path}")
            discovered.append(result_path)
    return discovered


def discover_resource_results(result_args: list[Path], from_artifacts: bool) -> list[Path]:
    discovered: list[Path] = []
    for item in result_args:
        resolved = item.resolve()
        if resolved.is_file():
            if resolved.name == "result.json":
                discovered.append(resolved)
                continue
            if resolved.name == "summary.jsonl":
                discovered.extend(result_paths_from_summary_jsonl(resolved))
                continue
            if resolved.name == "campaign.json":
                campaign = load_json_object(resolved)
                summary_path = campaign.get("summary")
                if not isinstance(summary_path, str):
                    raise ValueError(f"campaign.json is missing summary path: {resolved}")
                discovered.extend(result_paths_from_summary_jsonl(Path(summary_path).resolve()))
                continue
            raise ValueError(f"unsupported resource-coordination input file: {resolved}")
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("result.json")))
            continue
        raise FileNotFoundError(f"resource-coordination input does not exist: {resolved}")
    if from_artifacts:
        discovered.extend(sorted((ARTIFACTS_DIR / "semantic-resource-coordination").glob("**/result.json")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def campaign_path_for_result(result_path: Path) -> Path | None:
    candidate = result_path.parent.parent / "campaign.json"
    return candidate if candidate.is_file() else None


def baseline_trace_for_result(result_path: Path) -> Path | None:
    candidate = result_path.parent.parent / "_baseline" / "trace.jsonl"
    return candidate if candidate.is_file() else None


def game_dir_for_result(result_path: Path, case_result: dict[str, object]) -> Path:
    cwd = case_result.get("cwd")
    if isinstance(cwd, str):
        return Path(cwd).resolve()
    campaign_path = campaign_path_for_result(result_path)
    if campaign_path is not None:
        campaign = load_json_object(campaign_path)
        baseline = campaign.get("baseline")
        if isinstance(baseline, dict):
            baseline_cwd = baseline.get("cwd")
            if isinstance(baseline_cwd, str):
                return Path(baseline_cwd).resolve()
    return DEFAULT_GAME_DIR.resolve()


def override_payload_paths(case_result: dict[str, object], result_path: Path) -> dict[str, Path]:
    override_dir = case_result.get("override_dir")
    override_keys = case_result.get("override_keys")
    if not isinstance(override_dir, str):
        raise ValueError(f"resource result is missing override_dir: {result_path}")
    if not isinstance(override_keys, list) or not all(isinstance(item, str) for item in override_keys):
        raise ValueError(f"resource result is missing override_keys: {result_path}")
    root = Path(override_dir).resolve() / "data"
    payloads: dict[str, Path] = {}
    for key in override_keys:
        payload_path = root / key
        if not payload_path.is_file():
            raise FileNotFoundError(f"missing override payload {key}: {payload_path}")
        payloads[key] = payload_path
    return payloads


def load_trace_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    return load_trace_records(path)
