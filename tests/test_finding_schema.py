import pytest

from danmakufuzz.findings.schema import FindingMetadataError, validate_finding_metadata


def _valid_metadata() -> dict[str, object]:
    return {
        "schema": "danmakufuzz-finding-v1",
        "id": "semantic/example",
        "title": "Example finding",
        "kind": "semantic-progress-wedge",
        "evidence_level": "HEADLESS_REPRODUCED",
        "headless_runs": {"pass": 5, "total": 5},
        "retail_runs": {"pass": 0, "total": 0},
        "payload_sha256": "0" * 64,
        "model_revision": "th06-headless:abc123",
        "retail_exe_sha256": None,
        "expected_oracle": {"classification": "game-window-static"},
    }


def test_validate_finding_metadata_accepts_required_contract() -> None:
    validate_finding_metadata(_valid_metadata())


def test_validate_finding_metadata_rejects_bad_run_counts() -> None:
    metadata = _valid_metadata()
    metadata["headless_runs"] = {"pass": 6, "total": 5}
    with pytest.raises(FindingMetadataError):
        validate_finding_metadata(metadata)


def test_validate_finding_metadata_rejects_bad_hash() -> None:
    metadata = _valid_metadata()
    metadata["payload_sha256"] = "not-a-hash"
    with pytest.raises(FindingMetadataError):
        validate_finding_metadata(metadata)


def test_validate_finding_metadata_rejects_bad_triage_status() -> None:
    metadata = _valid_metadata()
    metadata["triage_status"] = "maybe-confirmed"
    with pytest.raises(FindingMetadataError):
        validate_finding_metadata(metadata)
