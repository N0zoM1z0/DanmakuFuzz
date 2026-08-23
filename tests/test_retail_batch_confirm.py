from __future__ import annotations

import json
from pathlib import Path

from danmakufuzz.retail.batch_confirm import _discover_results


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def test_directory_discovery_skips_aggregate_summary_json(tmp_path: Path) -> None:
    aggregate = tmp_path / "summary.json"
    semantic = tmp_path / "case" / "result.json"
    anm = tmp_path / "anm" / "result.json"
    minimized = tmp_path / "minimized" / "summary.json"

    _write_json(aggregate, {"schema": "danmakufuzz-retail-batch-v1"})
    _write_json(semantic, {"override_dir": "/tmp/override", "seed_name": "ecldata1.ecl"})
    _write_json(anm, {"override_dir": "/tmp/override", "entry_name": "stg6bg.anm"})
    _write_json(minimized, {"final_payload": "/tmp/payload.ecl"})

    discovered = _discover_results([tmp_path], from_minimized=False)

    assert semantic.resolve() in discovered
    assert anm.resolve() in discovered
    assert minimized.resolve() in discovered
    assert aggregate.resolve() not in discovered


def test_explicit_summary_json_is_preserved_for_validation(tmp_path: Path) -> None:
    aggregate = tmp_path / "summary.json"
    _write_json(aggregate, {"schema": "danmakufuzz-retail-batch-v1"})

    assert _discover_results([aggregate], from_minimized=False) == [aggregate.resolve()]
