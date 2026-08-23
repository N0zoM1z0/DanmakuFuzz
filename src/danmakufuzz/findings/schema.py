from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EVIDENCE_LEVELS = {
    "FORMAT_REJECTED",
    "FORMAT_CHARACTERIZATION",
    "MODEL_PARSER_ONLY",
    "HEADLESS_CANDIDATE",
    "HEADLESS_REPRODUCED",
    "RETAIL_LAUNCH_SMOKE",
    "RETAIL_BEHAVIOR_DIVERGENCE",
    "RETAIL_CRASH_REPRODUCED",
    "RETAIL_CRASH_WITH_BACKTRACE",
    "SECURITY_RELEVANT",
}

TRIAGE_STATUSES = {
    "confirmed-retail",
    "retail-disconfirmed",
    "retail-observation",
    "headless-pending-retail",
    "blocked-retail-oracle",
    "format-observation",
    "needs-reproduction",
}

REQUIRED_FIELDS = {
    "schema",
    "id",
    "title",
    "kind",
    "evidence_level",
    "headless_runs",
    "retail_runs",
    "payload_sha256",
    "model_revision",
    "retail_exe_sha256",
    "expected_oracle",
}


class FindingMetadataError(ValueError):
    """Raised when a finding.json payload does not match the local contract."""


def _require_string(data: dict[str, Any], key: str) -> None:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise FindingMetadataError(f"{key} must be a non-empty string")


def _validate_run_counts(data: dict[str, Any], key: str) -> None:
    value = data.get(key)
    if not isinstance(value, dict):
        raise FindingMetadataError(f"{key} must be an object")
    passed = value.get("pass")
    total = value.get("total")
    if not isinstance(passed, int) or isinstance(passed, bool) or passed < 0:
        raise FindingMetadataError(f"{key}.pass must be a non-negative integer")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise FindingMetadataError(f"{key}.total must be a non-negative integer")
    if passed > total:
        raise FindingMetadataError(f"{key}.pass cannot exceed {key}.total")


def _validate_sha256_or_null(data: dict[str, Any], key: str) -> None:
    value = data.get(key)
    if value is None:
        return
    values = value if isinstance(value, list) else [value]
    if not values:
        raise FindingMetadataError(f"{key} list must not be empty")
    for item in values:
        if not isinstance(item, str) or len(item) != 64:
            raise FindingMetadataError(f"{key} must be null, a sha256 string, or a list of sha256 strings")
        try:
            int(item, 16)
        except ValueError as exc:
            raise FindingMetadataError(f"{key} must contain valid hexadecimal sha256 strings") from exc


def _validate_expected_oracle(data: dict[str, Any]) -> None:
    value = data.get("expected_oracle")
    if value is None:
        return
    if not isinstance(value, dict):
        raise FindingMetadataError("expected_oracle must be null or an object")
    classification = value.get("classification")
    signature_key = value.get("retail_signature_key")
    if classification is not None and not isinstance(classification, str):
        raise FindingMetadataError("expected_oracle.classification must be a string or null")
    if signature_key is not None and not isinstance(signature_key, str):
        raise FindingMetadataError("expected_oracle.retail_signature_key must be a string or null")


def validate_finding_metadata(data: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        raise FindingMetadataError(f"finding metadata is missing required fields: {missing}")
    if data.get("schema") != "danmakufuzz-finding-v1":
        raise FindingMetadataError("schema must be danmakufuzz-finding-v1")
    for key in ("id", "title", "kind"):
        _require_string(data, key)
    evidence_level = data.get("evidence_level")
    if evidence_level not in EVIDENCE_LEVELS:
        raise FindingMetadataError(f"unsupported evidence_level: {evidence_level!r}")
    _validate_run_counts(data, "headless_runs")
    _validate_run_counts(data, "retail_runs")
    _validate_sha256_or_null(data, "payload_sha256")
    _validate_sha256_or_null(data, "retail_exe_sha256")
    model_revision = data.get("model_revision")
    if model_revision is not None and not isinstance(model_revision, str):
        raise FindingMetadataError("model_revision must be a string or null")
    _validate_expected_oracle(data)
    triage_status = data.get("triage_status")
    if triage_status is not None and triage_status not in TRIAGE_STATUSES:
        raise FindingMetadataError(f"unsupported triage_status: {triage_status!r}")


def load_finding_metadata(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FindingMetadataError(f"finding metadata must be an object: {path}")
    validate_finding_metadata(data)
    return data
