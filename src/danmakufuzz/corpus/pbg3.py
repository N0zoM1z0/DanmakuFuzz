from __future__ import annotations

from dataclasses import dataclass
import hashlib
from collections.abc import Sequence
from typing import Mapping


class Pbg3Error(ValueError):
    """Raised when a PBG3 archive is malformed."""


@dataclass(frozen=True)
class Pbg3Entry:
    filename: str
    checksum: int
    data_offset: int
    uncompressed_size: int
    unk1: int = 0
    unk2: int = 0


class _BitReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._bit_offset = 0

    def read_bits(self, count: int) -> int:
        if count < 0 or self._bit_offset + count > len(self._data) * 8:
            raise Pbg3Error("truncated PBG3 bitstream")
        value = 0
        for _ in range(count):
            byte = self._data[self._bit_offset // 8]
            shift = 7 - self._bit_offset % 8
            value = (value << 1) | ((byte >> shift) & 1)
            self._bit_offset += 1
        return value

    def read_varint(self) -> int:
        width = (8, 16, 24, 32)[self.read_bits(2)]
        return self.read_bits(width)

    def read_string(self, max_bytes: int = 256) -> str:
        raw = bytearray()
        for _ in range(max_bytes):
            value = self.read_bits(8)
            if value == 0:
                try:
                    return raw.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise Pbg3Error("PBG3 filename is not valid ASCII") from exc
            raw.append(value)
        raise Pbg3Error("PBG3 filename exceeds its 256-byte field")

    def seek_byte(self, offset: int) -> None:
        if not 0 <= offset < len(self._data):
            raise Pbg3Error("PBG3 byte offset is outside the archive")
        self._bit_offset = offset * 8

    @property
    def bit_offset(self) -> int:
        return self._bit_offset


class _BitWriter:
    def __init__(self) -> None:
        self._output = bytearray()
        self._current = 0
        self._count = 0

    def write_bits(self, value: int, count: int) -> None:
        if count < 0:
            raise ValueError("bit count must be non-negative")
        for shift in range(count - 1, -1, -1):
            bit = (value >> shift) & 1
            self._current = (self._current << 1) | bit
            self._count += 1
            if self._count == 8:
                self._output.append(self._current)
                self._current = 0
                self._count = 0

    def write_varint(self, value: int, *, width: int = 32) -> None:
        widths = {8: 0b00, 16: 0b01, 24: 0b10, 32: 0b11}
        if width not in widths:
            raise ValueError(f"unsupported PBG3 varint width: {width}")
        if value < 0 or value >= (1 << width):
            raise ValueError(f"value {value} does not fit in {width} bits")
        self.write_bits(widths[width], 2)
        self.write_bits(value, width)

    def write_string(self, value: str) -> None:
        raw = value.encode("ascii")
        if len(raw) >= 256:
            raise ValueError("PBG3 filename exceeds its 256-byte field")
        for byte in raw:
            self.write_bits(byte, 8)
        self.write_bits(0, 8)

    def finish(self) -> bytes:
        if self._count:
            self._output.append(self._current << (8 - self._count))
            self._current = 0
            self._count = 0
        return bytes(self._output)


def compress_literal_payload(payload: bytes) -> tuple[bytes, int]:
    writer = _BitWriter()
    for byte in payload:
        writer.write_bits(1, 1)
        writer.write_bits(byte, 8)
    writer.write_bits(0, 1)
    writer.write_bits(0, 13)
    compressed = writer.finish()
    return compressed, sum(compressed) & 0xFFFFFFFF


def _compress_literal_only(payload: bytes) -> tuple[bytes, int]:
    return compress_literal_payload(payload)


@dataclass(frozen=True)
class Pbg3Archive:
    data: bytes
    entries: tuple[Pbg3Entry, ...]
    table_offset: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "Pbg3Archive":
        reader = _BitReader(data)
        magic = bytes(reader.read_bits(8) for _ in range(4))
        if magic != b"PBG3":
            raise Pbg3Error("archive does not have the TH06 PBG3 magic")
        count = reader.read_varint()
        table_offset = reader.read_varint()
        if not 0 < count <= 4096:
            raise Pbg3Error(f"invalid PBG3 entry count: {count}")
        reader.seek_byte(table_offset)
        entries: list[Pbg3Entry] = []
        names: set[str] = set()
        for _ in range(count):
            unk2 = reader.read_varint()
            unk1 = reader.read_varint()
            checksum = reader.read_varint()
            data_offset = reader.read_varint()
            uncompressed_size = reader.read_varint()
            filename = reader.read_string()
            if filename in names:
                raise Pbg3Error(f"duplicate PBG3 entry: {filename}")
            if not 0 <= data_offset < table_offset:
                raise Pbg3Error(f"invalid data offset for PBG3 entry: {filename}")
            names.add(filename)
            entries.append(Pbg3Entry(
                filename=filename,
                checksum=checksum,
                data_offset=data_offset,
                uncompressed_size=uncompressed_size,
                unk1=unk1,
                unk2=unk2,
            ))
        if any(left.data_offset >= right.data_offset for left, right in zip(entries, entries[1:], strict=False)):
            raise Pbg3Error("PBG3 entries are not in increasing data-offset order")
        return cls(data=data, entries=tuple(entries), table_offset=table_offset)

    def entry_by_name(self, filename: str) -> Pbg3Entry:
        for entry in self.entries:
            if entry.filename == filename:
                return entry
        raise KeyError(filename)

    def _entry_bounds(self, entry: Pbg3Entry) -> tuple[int, int]:
        index = self.entries.index(entry)
        end = self.entries[index + 1].data_offset if index + 1 < len(self.entries) else self.table_offset
        return entry.data_offset, end

    def compressed_entries(self) -> tuple[tuple[Pbg3Entry, bytes], ...]:
        return tuple(
            (entry, self.data[start:end])
            for entry in self.entries
            for start, end in (self._entry_bounds(entry),)
        )

    def extract(self, filename: str) -> bytes:
        return self.extract_entry(self.entry_by_name(filename))

    def extract_entry(self, entry: Pbg3Entry) -> bytes:
        start, end = self._entry_bounds(entry)
        compressed = self.data[start:end]
        reader = _BitReader(compressed)
        dictionary = bytearray(0x2000)
        dictionary_head = 1
        output = bytearray()

        def write(value: int) -> None:
            nonlocal dictionary_head
            if len(output) >= entry.uncompressed_size:
                raise Pbg3Error(
                    f"PBG3 entry expands past its declared size: {entry.filename}"
                )
            output.append(value)
            dictionary[dictionary_head] = value
            dictionary_head = (dictionary_head + 1) & 0x1FFF

        while True:
            opcode = reader.read_bits(1)
            if opcode:
                write(reader.read_bits(8))
                continue
            match_offset = reader.read_bits(13)
            if match_offset == 0:
                break
            match_length = reader.read_bits(4) + 3
            for offset in range(match_length):
                write(dictionary[(match_offset + offset) & 0x1FFF])

        consumed_bytes = (reader.bit_offset + 7) // 8
        checksum = sum(compressed[:consumed_bytes]) & 0xFFFFFFFF
        if checksum != entry.checksum:
            raise Pbg3Error(
                f"PBG3 checksum mismatch for {entry.filename}: "
                f"{checksum:#x} != {entry.checksum:#x}"
            )
        if len(output) != entry.uncompressed_size:
            raise Pbg3Error(
                f"PBG3 size mismatch for {entry.filename}: "
                f"{len(output)} != {entry.uncompressed_size}"
            )
        return bytes(output)

    def replace(self, replacements: Mapping[str, bytes]) -> bytes:
        missing = sorted(set(replacements) - {entry.filename for entry in self.entries})
        if missing:
            raise KeyError(f"PBG3 archive is missing replacement entries: {missing}")

        compressed_entries: list[tuple[Pbg3Entry, bytes]] = []
        for entry in self.entries:
            payload = replacements.get(entry.filename)
            if payload is None:
                payload = self.extract_entry(entry)
            compressed, checksum = compress_literal_payload(payload)
            compressed_entries.append((
                Pbg3Entry(
                    filename=entry.filename,
                    checksum=checksum,
                    data_offset=0,
                    uncompressed_size=len(payload),
                    unk1=entry.unk1,
                    unk2=entry.unk2,
                ),
                compressed,
            ))
        return build_pbg3(compressed_entries)

def build_pbg3(
    entries_with_compressed: Sequence[tuple[Pbg3Entry, bytes]],
    *,
    magic: bytes = b"PBG3",
    count_override: int | None = None,
    table_offset_override: int | None = None,
    normalize_offsets: bool = True,
) -> bytes:
    if len(magic) != 4:
        raise ValueError("PBG3 magic must be 4 bytes")

    declared_count = len(entries_with_compressed) if count_override is None else int(count_override)
    header_probe = _BitWriter()
    header_probe.write_varint(declared_count, width=32)
    header_probe.write_varint(0, width=32)
    header_size = 4 + len(header_probe.finish())

    data_blob = bytearray()
    finalized_entries: list[Pbg3Entry] = []
    data_offset = header_size
    for entry, compressed in entries_with_compressed:
        finalized_entries.append(
            Pbg3Entry(
                filename=entry.filename,
                checksum=entry.checksum,
                data_offset=(data_offset if normalize_offsets else entry.data_offset),
                uncompressed_size=entry.uncompressed_size,
                unk1=entry.unk1,
                unk2=entry.unk2,
            )
        )
        data_blob += compressed
        data_offset += len(compressed)

    table_offset = (
        header_size + len(data_blob)
        if table_offset_override is None
        else int(table_offset_override)
    )
    writer = _BitWriter()
    for entry in finalized_entries:
        writer.write_varint(entry.unk2, width=32)
        writer.write_varint(entry.unk1, width=32)
        writer.write_varint(entry.checksum, width=32)
        writer.write_varint(entry.data_offset, width=32)
        writer.write_varint(entry.uncompressed_size, width=32)
        writer.write_string(entry.filename)
    table_blob = writer.finish()

    header = bytearray(magic)
    header_writer = _BitWriter()
    header_writer.write_varint(declared_count, width=32)
    header_writer.write_varint(table_offset, width=32)
    header += header_writer.finish()
    return bytes(header + data_blob + table_blob)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
