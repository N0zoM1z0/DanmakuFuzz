from __future__ import annotations

from dataclasses import dataclass

from ..corpus.pbg3 import Pbg3Archive, Pbg3Entry, build_pbg3, sha256_bytes


@dataclass(frozen=True)
class Pbg3Mutant:
    name: str
    payload: bytes
    source: str
    sha256: str


def _replace_entry(entry: Pbg3Entry, **changes: object) -> Pbg3Entry:
    return Pbg3Entry(
        filename=changes.get("filename", entry.filename),  # type: ignore[arg-type]
        checksum=int(changes.get("checksum", entry.checksum)),
        data_offset=int(changes.get("data_offset", entry.data_offset)),
        uncompressed_size=int(changes.get("uncompressed_size", entry.uncompressed_size)),
        unk1=int(changes.get("unk1", entry.unk1)),
        unk2=int(changes.get("unk2", entry.unk2)),
    )


def _flip_first_byte(data: bytes, *, mask: int = 0x80) -> bytes:
    if not data:
        return bytes([mask])
    return bytes([data[0] ^ mask]) + data[1:]


def generate_pbg3_mutants(seed_payload: bytes) -> list[Pbg3Mutant]:
    archive = Pbg3Archive.from_bytes(seed_payload)
    encoded_entries = list(archive.compressed_entries())
    first_entry, first_compressed = encoded_entries[0]
    mutants: list[Pbg3Mutant] = []

    def add(name: str, payload: bytes, source: str) -> None:
        mutants.append(Pbg3Mutant(name=name, payload=payload, source=source, sha256=sha256_bytes(payload)))

    add("magic-zero", b"\x00\x00\x00\x00" + seed_payload[4:], "header")
    add("truncate-header-8", seed_payload[:8], "header")
    add("append-garbage-256", seed_payload + (b"\xAA" * 256), "trailing")
    add("entry-count-one", build_pbg3(encoded_entries, count_override=1), "header")
    add("entry-count-too-large", build_pbg3(encoded_entries, count_override=len(encoded_entries) + 8), "header")
    add(
        "table-offset-inside-data",
        build_pbg3(
            encoded_entries,
            table_offset_override=first_entry.data_offset + max(1, len(first_compressed) // 2),
        ),
        "header",
    )
    add(
        "truncate-first-entry-data-half",
        seed_payload[: first_entry.data_offset + max(1, len(first_compressed) // 2)],
        "data",
    )

    def rebuild_first(entry: Pbg3Entry, compressed: bytes, *, normalize_offsets: bool = True) -> bytes:
        tail = encoded_entries[1:]
        return build_pbg3([(entry, compressed), *tail], normalize_offsets=normalize_offsets)

    add(
        "first-entry-checksum-zero",
        rebuild_first(_replace_entry(first_entry, checksum=0), first_compressed),
        "table",
    )
    add(
        "first-entry-size-zero",
        rebuild_first(_replace_entry(first_entry, uncompressed_size=0), first_compressed),
        "table",
    )
    add(
        "first-entry-size-inflate",
        rebuild_first(
            _replace_entry(first_entry, uncompressed_size=first_entry.uncompressed_size + 1024),
            first_compressed,
        ),
        "table",
    )
    add(
        "first-entry-offset-zero",
        rebuild_first(_replace_entry(first_entry, data_offset=0), first_compressed, normalize_offsets=False),
        "table",
    )

    flipped = _flip_first_byte(first_compressed)
    add("first-entry-bitflip", rebuild_first(first_entry, flipped), "data")
    add(
        "first-entry-bitflip-resummed",
        rebuild_first(_replace_entry(first_entry, checksum=sum(flipped) & 0xFFFFFFFF), flipped),
        "data",
    )
    add("first-entry-empty-payload", archive.replace({first_entry.filename: b""}), "payload")

    if len(encoded_entries) > 1:
        second_entry, second_compressed = encoded_entries[1]
        add(
            "duplicate-entry-name",
            build_pbg3(
                [
                    (first_entry, first_compressed),
                    (_replace_entry(second_entry, filename=first_entry.filename), second_compressed),
                    *encoded_entries[2:],
                ]
            ),
            "table",
        )
        add(
            "first-entry-offset-second",
            build_pbg3(
                [
                    (_replace_entry(first_entry, data_offset=second_entry.data_offset), first_compressed),
                    *encoded_entries[1:],
                ],
                normalize_offsets=False,
            ),
            "table",
        )

    deduped: list[Pbg3Mutant] = []
    seen: set[tuple[str, str]] = set()
    for mutant in mutants:
        key = (mutant.name, mutant.sha256)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mutant)
    return deduped
