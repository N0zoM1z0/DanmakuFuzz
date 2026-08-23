from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from ..corpus.pbg3 import Pbg3Archive, Pbg3Entry, build_pbg3, compress_literal_payload, sha256_bytes
from ..repo import ARTIFACTS_DIR, REFERENCE_DIR, ensure_directory
from .pbg3_campaign import _baseline_summary, evaluate_pbg3_payload


DEFAULT_GAME_DIR = REFERENCE_DIR / "retail" / "game" / "th06"


@dataclass(frozen=True)
class Pbg3MetamorphicCase:
    name: str
    payload: bytes
    relation: str
    description: str
    sha256: str


def _slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-._")
    return slug or "archive"


def _archive_slug(path: Path) -> str:
    material = str(path.resolve()).encode("utf-8", errors="surrogateescape")
    suffix = hashlib.sha256(material).hexdigest()[:8]
    return f"{_slug(path.name)}-{suffix}"


def _replace_entry(entry: Pbg3Entry, **changes: object) -> Pbg3Entry:
    return Pbg3Entry(
        filename=changes.get("filename", entry.filename),  # type: ignore[arg-type]
        checksum=int(changes.get("checksum", entry.checksum)),
        data_offset=int(changes.get("data_offset", entry.data_offset)),
        uncompressed_size=int(changes.get("uncompressed_size", entry.uncompressed_size)),
        unk1=int(changes.get("unk1", entry.unk1)),
        unk2=int(changes.get("unk2", entry.unk2)),
    )


def _literal_entries(archive: Pbg3Archive) -> list[tuple[Pbg3Entry, bytes]]:
    entries: list[tuple[Pbg3Entry, bytes]] = []
    for entry in archive.entries:
        payload = archive.extract_entry(entry)
        compressed, checksum = compress_literal_payload(payload)
        entries.append(
            (
                Pbg3Entry(
                    filename=entry.filename,
                    checksum=checksum,
                    data_offset=0,
                    uncompressed_size=len(payload),
                    unk1=entry.unk1,
                    unk2=entry.unk2,
                ),
                compressed,
            )
        )
    return entries


def _add_padding(
    entries_with_compressed: Iterable[tuple[Pbg3Entry, bytes]],
    padding: bytes,
) -> list[tuple[Pbg3Entry, bytes]]:
    return [(entry, compressed + padding) for entry, compressed in entries_with_compressed]


def _case(name: str, payload: bytes, *, description: str) -> Pbg3MetamorphicCase:
    return Pbg3MetamorphicCase(
        name=name,
        payload=payload,
        relation="archive-entry-map-equivalence",
        description=description,
        sha256=sha256_bytes(payload),
    )


def generate_pbg3_metamorphic_cases(seed_payload: bytes) -> list[Pbg3MetamorphicCase]:
    archive = Pbg3Archive.from_bytes(seed_payload)
    source_entries = list(archive.compressed_entries())
    literal_entries = _literal_entries(archive)
    cases = [
        _case(
            "literal-repack-original-order",
            build_pbg3(literal_entries),
            description="Recompress every entry as literal-only data while preserving entry order and payloads.",
        ),
        _case(
            "source-compressed-repack-original-order",
            build_pbg3(source_entries),
            description="Rebuild the container/table around the original compressed entry streams.",
        ),
        _case(
            "source-compressed-repack-reversed-order",
            build_pbg3(list(reversed(source_entries))),
            description="Reverse entry order while preserving the filename->payload map.",
        ),
        _case(
            "source-compressed-repack-name-sorted",
            build_pbg3(sorted(source_entries, key=lambda item: item[0].filename)),
            description="Sort entries by filename while preserving the filename->payload map.",
        ),
        _case(
            "source-compressed-entry-padding-zero-8",
            build_pbg3(_add_padding(source_entries, b"\x00" * 8)),
            description="Append zero padding after every compressed stream terminator and update offsets.",
        ),
        _case(
            "source-compressed-entry-padding-aa-8",
            build_pbg3(_add_padding(source_entries, b"\xAA" * 8)),
            description="Append non-zero padding after every compressed stream terminator and update offsets.",
        ),
        _case(
            "literal-repack-entry-padding-zero-8",
            build_pbg3(_add_padding(literal_entries, b"\x00" * 8)),
            description="Literal-repack every entry, then append ignored zero padding after terminators.",
        ),
        _case(
            "append-trailing-garbage-zero-64",
            seed_payload + (b"\x00" * 64),
            description="Append bytes after the archive table; the entry map should be unchanged.",
        ),
        _case(
            "append-trailing-garbage-aa-64",
            seed_payload + (b"\xAA" * 64),
            description="Append non-zero bytes after the archive table; the entry map should be unchanged.",
        ),
        _case(
            "unknown-fields-zero",
            build_pbg3(
                [
                    (_replace_entry(entry, unk1=0, unk2=0), compressed)
                    for entry, compressed in source_entries
                ]
            ),
            description="Clear table unknown fields while preserving entry compressed data.",
        ),
        _case(
            "unknown-fields-pattern",
            build_pbg3(
                [
                    (_replace_entry(entry, unk1=0x5A5A, unk2=0xA5A5), compressed)
                    for entry, compressed in source_entries
                ]
            ),
            description="Set table unknown fields to a fixed non-zero pattern while preserving entry compressed data.",
        ),
    ]
    deduped: list[Pbg3MetamorphicCase] = []
    seen: set[tuple[str, str]] = set()
    for case in cases:
        key = (case.name, case.sha256)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(case)
    return deduped


def evaluate_pbg3_metamorphic_payload(
    payload: bytes,
    baseline_hashes: dict[str, str],
) -> dict[str, object]:
    evaluation = evaluate_pbg3_payload(payload, baseline_hashes)
    relation_holds = (
        evaluation.get("classification") == "accepted"
        and bool(evaluation.get("equivalent_to_baseline"))
    )
    violation_kind = None
    if not relation_holds:
        violation_kind = str(evaluation.get("observation_kind") or evaluation.get("classification") or "unknown")
    return {
        **evaluation,
        "metamorphic_relation": "archive-entry-map-equivalence",
        "relation_holds": relation_holds,
        "metamorphic_violation": not relation_holds,
        "violation_kind": violation_kind,
        "interesting": not relation_holds,
    }


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "parser-pbg3-metamorphic" / stamp


def _discover_archives(game_dir: Path) -> list[Path]:
    unique: list[Path] = []
    seen_content: set[str] = set()
    for path in sorted(game_dir.glob("*.DAT")):
        if not path.is_file():
            continue
        digest = sha256_bytes(path.read_bytes())
        if digest in seen_content:
            continue
        seen_content.add(digest)
        unique.append(path)
    return unique


def _write_case_result(case_dir: Path, result: dict[str, object]) -> None:
    (case_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def _run_archive(
    archive_path: Path,
    *,
    artifact_dir: Path,
    limit: int | None,
    name_filters: list[str],
    emit_cases: bool,
) -> dict[str, object]:
    seed_payload = archive_path.read_bytes()
    archive_dir = artifact_dir / _archive_slug(archive_path)
    ensure_directory(archive_dir)
    baseline = _baseline_summary(seed_payload, archive_path)
    (archive_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    cases = generate_pbg3_metamorphic_cases(seed_payload)
    if name_filters:
        cases = [
            case
            for case in cases
            if any(name_filter in case.name for name_filter in name_filters)
        ]
    if limit is not None:
        cases = cases[:limit]

    summary_path = archive_dir / "summary.jsonl"
    classification_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    violation_counts: Counter[str] = Counter()
    with summary_path.open("w", encoding="utf-8") as summary_handle:
        for case_index, case in enumerate(cases, start=1):
            case_name = f"{case_index:04d}-{case.name}"
            case_dir = archive_dir / case_name
            ensure_directory(case_dir)
            payload_path = case_dir / "input.pbg3"
            payload_path.write_bytes(case.payload)
            evaluation = evaluate_pbg3_metamorphic_payload(
                case.payload,
                baseline["entry_hashes"],  # type: ignore[arg-type]
            )
            result = {
                "case_name": case_name,
                "mutant_name": case.name,
                "relation": case.relation,
                "description": case.description,
                "archive": str(archive_path.resolve()),
                "archive_path": str(payload_path.resolve()),
                "payload_size": len(case.payload),
                "payload_sha256": case.sha256,
                **evaluation,
            }
            classification_counts[str(result["classification"])] += 1
            relation_counts["holds" if bool(result["relation_holds"]) else "violated"] += 1
            if result["violation_kind"] is not None:
                violation_counts[str(result["violation_kind"])] += 1
            _write_case_result(case_dir, result)
            summary_handle.write(json.dumps(result) + "\n")
            if emit_cases:
                print(json.dumps(result, ensure_ascii=False))

    report = {
        "schema": "danmakufuzz-pbg3-metamorphic-archive-v1",
        "archive": str(archive_path.resolve()),
        "baseline": {
            "entry_count": baseline["entry_count"],
            "table_offset": baseline["table_offset"],
        },
        "metamorphic_relation": "archive-entry-map-equivalence",
        "cases_generated": len(cases),
        "relation_counts": dict(sorted(relation_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "violation_counts": dict(sorted(violation_counts.items())),
        "summary": str(summary_path.resolve()),
    }
    (archive_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PBG3 metamorphic equivalence checks over one or more TH06 archives."
    )
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name-filter", action="append", default=[])
    parser.add_argument("--emit-cases", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archives = [path.resolve() for path in args.archive] or _discover_archives(args.game_dir.resolve())
    if not archives:
        raise FileNotFoundError(f"no PBG3 .DAT archives found under {args.game_dir.resolve()}")
    missing = [str(path) for path in archives if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing archive(s): {missing}")
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    reports = [
        _run_archive(
            archive_path,
            artifact_dir=artifact_dir,
            limit=args.limit,
            name_filters=args.name_filter,
            emit_cases=args.emit_cases,
        )
        for archive_path in archives
    ]
    relation_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    violation_counts: Counter[str] = Counter()
    for report in reports:
        relation_counts.update(report.get("relation_counts", {}))  # type: ignore[arg-type]
        classification_counts.update(report.get("classification_counts", {}))  # type: ignore[arg-type]
        violation_counts.update(report.get("violation_counts", {}))  # type: ignore[arg-type]
    campaign = {
        "schema": "danmakufuzz-pbg3-metamorphic-campaign-v1",
        "artifact_dir": str(artifact_dir),
        "archives": [str(path.resolve()) for path in archives],
        "archive_reports": [
            str((artifact_dir / _archive_slug(Path(str(report["archive"]))) / "campaign.json").resolve())
            for report in reports
        ],
        "cases_generated": sum(int(report["cases_generated"]) for report in reports),
        "metamorphic_relation": "archive-entry-map-equivalence",
        "relation_counts": dict(sorted(relation_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "violation_counts": dict(sorted(violation_counts.items())),
    }
    (artifact_dir / "campaign.json").write_text(json.dumps(campaign, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(campaign, indent=2))
    return 1 if violation_counts else 0


if __name__ == "__main__":
    raise SystemExit(main())
