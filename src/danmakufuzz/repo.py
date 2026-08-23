from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DOCS_DIR = REPO_ROOT / "docs"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
FINDINGS_DIR = REPO_ROOT / "findings"
REFERENCE_DIR = REPO_ROOT / "reference"
STATE_DIR = REPO_ROOT / "state"
THIRD_PARTY_DIR = REPO_ROOT / "third_party"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
