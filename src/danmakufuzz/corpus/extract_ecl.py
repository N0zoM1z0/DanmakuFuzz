from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Final

from .pbg3 import Pbg3Archive, sha256_bytes
from ..repo import REFERENCE_DIR, ensure_directory


DEFAULT_OUTPUT_DIR: Final = REFERENCE_DIR / "corpus" / "ecl" / "original"
DEFAULT_MANIFEST: Final = DEFAULT_OUTPUT_DIR / "manifest.json"
DEFAULT_ARCHIVE_ENTRY: Final = "th06/紅魔郷ST.DAT"


def _read_rar_entry(rar_path: Path, entry_path: str) -> bytes:
    command = ["7z", "x", "-so", str(rar_path), entry_path]
    result = subprocess.run(command, check=True, capture_output=True)
    if not result.stdout:
        raise ValueError(f"archive entry is empty or missing: {entry_path}")
    return result.stdout


def _load_archive_bytes(archive: Path | None, rar: Path | None, entry_path: str) -> tuple[bytes, dict[str, str]]:
    if archive is not None:
        payload = archive.read_bytes()
        return payload, {
            "source_kind": "archive",
            "archive_path": str(archive.resolve()),
            "archive_sha256": sha256_bytes(payload),
        }
    if rar is None:
        raise ValueError("one of --archive or --rar is required")
    payload = _read_rar_entry(rar.resolve(), entry_path)
    return payload, {
        "source_kind": "rar-entry",
        "rar_path": str(rar.resolve()),
        "rar_entry": entry_path,
        "archive_sha256": sha256_bytes(payload),
    }


def extract_ecl_corpus(
    *,
    archive: Path | None,
    rar: Path | None,
    rar_entry: str,
    output_dir: Path,
    manifest_path: Path,
    expected_count: int,
) -> dict[str, object]:
    archive_bytes, source_info = _load_archive_bytes(archive, rar, rar_entry)
    parsed = Pbg3Archive.from_bytes(archive_bytes)
    ecl_entries = tuple(entry for entry in parsed.entries if entry.filename.lower().endswith(".ecl"))
    if len(ecl_entries) != expected_count:
        raise ValueError(f"expected {expected_count} ECL entries, found {len(ecl_entries)}")
    ensure_directory(output_dir)
    manifest_entries: dict[str, dict[str, object]] = {}
    for entry in ecl_entries:
        payload = parsed.extract_entry(entry)
        target = output_dir / entry.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != payload:
            raise ValueError(f"refusing to overwrite mismatched corpus entry: {target}")
        target.write_bytes(payload)
        manifest_entries[entry.filename] = {
            "sha256": sha256_bytes(payload),
            "size": len(payload),
            "pbg3_checksum": entry.checksum,
        }
    manifest = {
        "schema": "danmakufuzz-th06-ecl-corpus-v1",
        "expected_entry_count": expected_count,
        **source_info,
        "entries": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__ or "Extract the TH06 ECL baseline corpus.")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--rar", type=Path)
    parser.add_argument("--rar-entry", default=DEFAULT_ARCHIVE_ENTRY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--expected-count", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = extract_ecl_corpus(
        archive=args.archive.resolve() if args.archive else None,
        rar=args.rar.resolve() if args.rar else None,
        rar_entry=args.rar_entry,
        output_dir=args.output_dir.resolve(),
        manifest_path=args.manifest.resolve(),
        expected_count=args.expected_count,
    )
    print(json.dumps({
        "output_dir": str(args.output_dir.resolve()),
        "manifest": str(args.manifest.resolve()),
        "entries": sorted(manifest["entries"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
