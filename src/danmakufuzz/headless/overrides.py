from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Mapping

from ..repo import ARTIFACTS_DIR, ensure_directory


def materialize_override_bundle(case_dir: Path, payloads: Mapping[str, bytes]) -> Path:
    if not payloads:
        raise ValueError("override bundle must not be empty")
    override_dir = case_dir / "override"
    ensure_directory(override_dir / "data")
    for relative_name, payload in sorted(payloads.items()):
        path = override_dir / "data" / relative_name
        ensure_directory(path.parent)
        path.write_bytes(payload)
    return override_dir


def stage_active_override_bundle(
    game_dir: Path,
    payloads: Mapping[str, bytes],
    *,
    namespace: str = "default",
) -> Path:
    if not payloads:
        raise ValueError("active override bundle must not be empty")
    worker_material = f"{game_dir.resolve()}::{namespace}".encode("utf-8")
    worker_key = hashlib.sha256(worker_material).hexdigest()[:16]
    active_override_dir = ARTIFACTS_DIR / "_active-overrides" / worker_key
    if active_override_dir.exists():
        shutil.rmtree(active_override_dir)
    ensure_directory(active_override_dir / "data")
    for relative_name, payload in sorted(payloads.items()):
        path = active_override_dir / "data" / relative_name
        ensure_directory(path.parent)
        path.write_bytes(payload)
    return active_override_dir
