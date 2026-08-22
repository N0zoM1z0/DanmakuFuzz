from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

BASE64_CHUNK_CHARS = 120


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode_patch_bytes(data: bytes) -> list[str]:
    encoded = base64.b64encode(data).decode("ascii")
    return [
        encoded[index:index + BASE64_CHUNK_CHARS]
        for index in range(0, len(encoded), BASE64_CHUNK_CHARS)
    ]


def _decode_patch_bytes(raw_hunk: dict[str, Any]) -> bytes:
    if "data_b64_chunks" in raw_hunk:
        chunks = raw_hunk["data_b64_chunks"]
        if not isinstance(chunks, list) or not all(isinstance(chunk, str) for chunk in chunks):
            raise ValueError("payload patch data_b64_chunks must be a list of strings")
        encoded = "".join(chunks)
    else:
        encoded = raw_hunk.get("data_b64")
        if not isinstance(encoded, str):
            raise ValueError("payload patch hunk must contain data_b64 or data_b64_chunks")
    return base64.b64decode(encoded)


def create_payload_patch(base: bytes, target: bytes) -> dict[str, Any]:
    prefix = 0
    limit = min(len(base), len(target))
    while prefix < limit and base[prefix] == target[prefix]:
        prefix += 1

    suffix = 0
    while (
        suffix < len(base) - prefix
        and suffix < len(target) - prefix
        and base[len(base) - 1 - suffix] == target[len(target) - 1 - suffix]
    ):
        suffix += 1

    hunks: list[dict[str, Any]] = []
    if prefix != len(base) or prefix != len(target):
        hunks.append(
            {
                "base_start": prefix,
                "base_end": len(base) - suffix,
                "data_b64_chunks": _encode_patch_bytes(target[prefix:len(target) - suffix]),
            }
        )
    return {
        "schema": "danmakufuzz-payload-patch-v1",
        "base_size": len(base),
        "target_size": len(target),
        "base_sha256": sha256_bytes(base),
        "target_sha256": sha256_bytes(target),
        "hunks": hunks,
    }


def apply_payload_patch(base: bytes, patch: dict[str, Any]) -> bytes:
    if patch.get("schema") != "danmakufuzz-payload-patch-v1":
        raise ValueError("unsupported payload patch schema")
    if int(patch.get("base_size", -1)) != len(base):
        raise ValueError("payload patch base size mismatch")
    if patch.get("base_sha256") != sha256_bytes(base):
        raise ValueError("payload patch base sha256 mismatch")

    hunks = patch.get("hunks")
    if not isinstance(hunks, list):
        raise ValueError("payload patch hunks must be a list")

    cursor = 0
    output = bytearray()
    for raw_hunk in hunks:
        if not isinstance(raw_hunk, dict):
            raise ValueError("payload patch hunk must be an object")
        start = int(raw_hunk["base_start"])
        end = int(raw_hunk["base_end"])
        if not (0 <= cursor <= start <= end <= len(base)):
            raise ValueError("payload patch hunk offsets are invalid or unsorted")
        output += base[cursor:start]
        output += _decode_patch_bytes(raw_hunk)
        cursor = end
    output += base[cursor:]
    result = bytes(output)
    if len(result) != int(patch.get("target_size", -1)):
        raise ValueError("payload patch target size mismatch")
    if patch.get("target_sha256") != sha256_bytes(result):
        raise ValueError("payload patch target sha256 mismatch")
    return result


def load_payload_patch(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"payload patch must be an object: {path}")
    return value
