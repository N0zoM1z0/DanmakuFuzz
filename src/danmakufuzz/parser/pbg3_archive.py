from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..corpus.pbg3 import Pbg3Archive, sha256_bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and optionally extract TH06 PBG3 archives.")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--extract", type=str)
    parser.add_argument("--extract-all", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing archive: {archive_path}")
    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    result: dict[str, object] = {
        "archive": str(archive_path),
        "entry_count": len(archive.entries),
        "table_offset": archive.table_offset,
        "entries": [
            {
                "filename": entry.filename,
                "checksum": entry.checksum,
                "data_offset": entry.data_offset,
                "uncompressed_size": entry.uncompressed_size,
            }
            for entry in archive.entries
        ],
    }
    if args.extract:
        payload = archive.extract(args.extract)
        result["extract"] = {
            "filename": args.extract,
            "size": len(payload),
            "sha256": sha256_bytes(payload),
        }
    elif args.extract_all:
        result["extract_all"] = [
            {
                "filename": entry.filename,
                "size": len(payload := archive.extract_entry(entry)),
                "sha256": sha256_bytes(payload),
            }
            for entry in archive.entries
        ]

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
