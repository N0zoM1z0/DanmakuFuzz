from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from danmakufuzz.corpus.pbg3 import Pbg3Archive
from danmakufuzz.parser.anm import DEFAULT_ARCHIVE, parse_anm
from danmakufuzz.parser.anm_campaign import evaluate_anm_payload
from danmakufuzz.parser.anm_mutants import generate_anm_mutants
from danmakufuzz.repo import ARTIFACTS_DIR, ensure_directory


TARGET_ENTRY = "stg1enm.anm"
TARGET_MUTANT_NAME = "first-sprite-offset-zero"
EXPECTED_PAYLOAD_SHA256 = "ead6a463f988a2ea97b1ec1c484e7d4d5fd57bb325cb344ba3b64e3d1c59cd4b"
EXPECTED_BASELINE_FIRST_SPRITE_OFFSET = 288
EXPECTED_MUTANT_FIRST_SPRITE_OFFSET = 0
EXPECTED_MUTANT_FIRST_SPRITE_ID = 24
EXPECTED_CHANGED_FIELDS = ["sprite_offsets"]
EXPECTED_MUTANT_FLOATS = {
    "offset_x": 1.1210387714598537e-44,
    "offset_y": 0.0,
    "size_x": 3.587324068671532e-43,
    "size_y": 3.587324068671532e-43,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the ANM first-sprite-offset-zero structural-acceptance finding."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--entry", type=str, default=TARGET_ENTRY)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACTS_DIR / "findings" / "parser-anm-first-sprite-offset-zero-structural-acceptance",
    )
    parser.add_argument("--max-script-instructions", type=int, default=4096)
    return parser.parse_args()


def _expect_close(label: str, actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-45):
        raise RuntimeError(f"{label} drifted: expected {expected!r}, got {actual!r}")


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing retail archive seed: {archive_path}")

    artifact_dir = args.artifact_dir.resolve()
    ensure_directory(artifact_dir)

    archive = Pbg3Archive.from_bytes(archive_path.read_bytes())
    seed_payload = archive.extract(args.entry)
    baseline = parse_anm(seed_payload, max_script_instructions=args.max_script_instructions)
    baseline_sprites = baseline.get("sprites")
    if not isinstance(baseline_sprites, list) or not baseline_sprites:
        raise RuntimeError(f"baseline sprite list drifted: {baseline}")
    if int(baseline_sprites[0]["offset"]) != EXPECTED_BASELINE_FIRST_SPRITE_OFFSET:
        raise RuntimeError(
            "baseline first sprite offset drifted: "
            f"expected {EXPECTED_BASELINE_FIRST_SPRITE_OFFSET}, got {baseline_sprites[0]['offset']}"
        )

    mutant = next(
        (candidate for candidate in generate_anm_mutants(seed_payload) if candidate.name == TARGET_MUTANT_NAME),
        None,
    )
    if mutant is None:
        raise RuntimeError(f"missing target mutant {TARGET_MUTANT_NAME}")
    if mutant.sha256 != EXPECTED_PAYLOAD_SHA256:
        raise RuntimeError(
            f"mutant payload sha drifted: expected {EXPECTED_PAYLOAD_SHA256}, got {mutant.sha256}"
        )

    payload_path = artifact_dir / args.entry
    payload_path.write_bytes(mutant.payload)

    evaluation = evaluate_anm_payload(
        mutant.payload,
        {"input": f"{archive_path}!{args.entry}", **baseline},
        max_script_instructions=args.max_script_instructions,
    )
    if evaluation["classification"] != "accepted":
        raise RuntimeError(f"mutant stopped being accepted: {evaluation}")
    if not bool(evaluation["interesting"]):
        raise RuntimeError(f"mutant stopped being interesting: {evaluation}")
    if bool(evaluation["equivalent_to_baseline"]):
        raise RuntimeError(f"mutant unexpectedly became equivalent: {evaluation}")
    if evaluation["changed_fields"] != EXPECTED_CHANGED_FIELDS:
        raise RuntimeError(f"changed_fields drifted: {evaluation['changed_fields']}")

    parsed = parse_anm(mutant.payload, max_script_instructions=args.max_script_instructions)
    sprites = parsed.get("sprites")
    if not isinstance(sprites, list) or not sprites:
        raise RuntimeError(f"mutant sprite list drifted: {parsed}")
    first_sprite = sprites[0]
    if int(first_sprite["offset"]) != EXPECTED_MUTANT_FIRST_SPRITE_OFFSET:
        raise RuntimeError(
            "mutant first sprite offset drifted: "
            f"expected {EXPECTED_MUTANT_FIRST_SPRITE_OFFSET}, got {first_sprite['offset']}"
        )
    if int(first_sprite["id"]) != EXPECTED_MUTANT_FIRST_SPRITE_ID:
        raise RuntimeError(
            f"mutant first sprite id drifted: expected {EXPECTED_MUTANT_FIRST_SPRITE_ID}, got {first_sprite['id']}"
        )
    offset_xy = first_sprite.get("offset_xy")
    size_xy = first_sprite.get("size_xy")
    if not isinstance(offset_xy, list) or not isinstance(size_xy, list) or len(offset_xy) != 2 or len(size_xy) != 2:
        raise RuntimeError(f"mutant first sprite shape drifted: {first_sprite}")
    _expect_close("offset_x", float(offset_xy[0]), EXPECTED_MUTANT_FLOATS["offset_x"])
    _expect_close("offset_y", float(offset_xy[1]), EXPECTED_MUTANT_FLOATS["offset_y"])
    _expect_close("size_x", float(size_xy[0]), EXPECTED_MUTANT_FLOATS["size_x"])
    _expect_close("size_y", float(size_xy[1]), EXPECTED_MUTANT_FLOATS["size_y"])

    summary = {
        "finding": "parser/anm-first-sprite-offset-zero-structural-acceptance",
        "archive": str(archive_path),
        "entry": args.entry,
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": mutant.sha256,
        "baseline": baseline,
        "evaluation": evaluation,
        "parsed": parsed,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
