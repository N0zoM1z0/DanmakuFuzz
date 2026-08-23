from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..repo import FINDINGS_DIR
from .schema import FindingMetadataError, load_finding_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate DanmakuFuzz finding.json metadata files.")
    parser.add_argument("path", nargs="*", type=Path, help="finding.json file or directory to scan")
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="fail when a finding directory does not contain finding.json",
    )
    return parser.parse_args()


def _metadata_paths(path: Path) -> list[Path]:
    resolved = path.resolve()
    if resolved.is_file():
        return [resolved]
    if not resolved.is_dir():
        raise FileNotFoundError(f"missing finding metadata input: {resolved}")
    return sorted(resolved.rglob("finding.json"))


def _finding_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_dir() and (path / "README.md").is_file())


def main() -> int:
    args = parse_args()
    inputs = args.path or [FINDINGS_DIR]
    paths: list[Path] = []
    for input_path in inputs:
        paths.extend(_metadata_paths(input_path))

    errors: list[dict[str, str]] = []
    for path in paths:
        try:
            load_finding_metadata(path)
        except (FindingMetadataError, json.JSONDecodeError, OSError) as exc:
            errors.append({"path": str(path), "error": str(exc)})

    missing: list[str] = []
    if args.require_all:
        for input_path in inputs:
            root = input_path.resolve()
            if root.is_file():
                continue
            for finding_dir in _finding_dirs(root):
                if not (finding_dir / "finding.json").is_file():
                    missing.append(str(finding_dir))

    report = {
        "schema": "danmakufuzz-finding-metadata-validation-v1",
        "inputs": [str(path.resolve()) for path in inputs],
        "checked": len(paths),
        "errors": errors,
        "missing": missing,
        "ok": not errors and not missing,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
