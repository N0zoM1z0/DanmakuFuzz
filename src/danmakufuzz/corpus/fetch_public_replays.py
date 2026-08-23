from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from danmakufuzz.parser.replay import replay_populated_stages, validate_replay


DEFAULT_MANIFEST = Path("reference/corpus/replay/public/th06/manifest.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/replay-corpus-public/th06")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest must contain a non-empty entries list")
    return manifest


def _download_bytes(url: str) -> bytes:
    with urlopen(url) as response:  # noqa: S310 - explicit public corpus fetcher
        return response.read()


def _validate_entry(payload: bytes, entry: dict[str, Any]) -> dict[str, Any]:
    meta = validate_replay(payload)
    stages = list(replay_populated_stages(payload))

    expected_sha256 = entry.get("sha256")
    if expected_sha256 is not None and _sha256_bytes(payload) != expected_sha256:
        raise ValueError(f"sha256 mismatch for {entry.get('name')}: expected {expected_sha256}")

    expected_size = entry.get("size")
    if expected_size is not None and len(payload) != int(expected_size):
        raise ValueError(
            f"size mismatch for {entry.get('name')}: expected {expected_size}, got {len(payload)}"
        )

    expected_difficulty = entry.get("difficulty")
    if expected_difficulty is not None and meta["difficulty"] != int(expected_difficulty):
        raise ValueError(
            f"difficulty mismatch for {entry.get('name')}: expected {expected_difficulty}, got {meta['difficulty']}"
        )

    expected_shottype = entry.get("shottype_chara")
    if expected_shottype is not None and meta["shottype_chara"] != int(expected_shottype):
        raise ValueError(
            f"shottype mismatch for {entry.get('name')}: expected {expected_shottype}, got {meta['shottype_chara']}"
        )

    expected_stages = entry.get("populated_stages")
    if expected_stages is not None and stages != list(expected_stages):
        raise ValueError(
            f"populated stages mismatch for {entry.get('name')}: expected {expected_stages}, got {stages}"
        )

    return {
        "difficulty": meta["difficulty"],
        "shottype_chara": meta["shottype_chara"],
        "populated_stages": stages,
        "size": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and validate a public replay corpus manifest.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--write-summary", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest: {manifest_path}")
    manifest = _load_manifest(manifest_path)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    requested = set(args.only)
    entries = manifest["entries"]
    if requested:
        entries = [entry for entry in entries if entry.get("name") in requested]
        missing = sorted(requested.difference(entry.get("name") for entry in entries))
        if missing:
            raise ValueError(f"requested entries not found in manifest: {missing}")

    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("manifest entry must be an object")
        name = str(entry["name"])
        filename = str(entry["filename"])
        url = str(entry["url"])
        target = output_dir / filename

        if args.skip_existing and target.is_file():
            payload = target.read_bytes()
            source = "existing"
        else:
            payload = _download_bytes(url)
            target.write_bytes(payload)
            source = "downloaded"

        validation = _validate_entry(payload, entry)
        results.append(
            {
                "name": name,
                "filename": filename,
                "path": str(target),
                "url": url,
                "source": source,
                **validation,
            }
        )

    summary = {
        "schema": "danmakufuzz-public-replay-fetch-v1",
        "manifest": str(manifest_path),
        "output_dir": str(output_dir),
        "count": len(results),
        "entries": results,
    }
    if args.write_summary is not None:
        summary_path = args.write_summary.resolve()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
