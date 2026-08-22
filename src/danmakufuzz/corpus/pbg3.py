from __future__ import annotations

from dataclasses import dataclass
import hashlib


class Pbg3Error(ValueError):
    """Raised when a PBG3 archive is malformed."""


@dataclass(frozen=True)
class Pbg3Entry:
    filename: str
    checksum: int
    data_offset: int
    uncompressed_size: int


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
                return raw.decode("ascii")
            raw.append(value)
        raise Pbg3Error("PBG3 filename exceeds its 256-byte field")

    def seek_byte(self, offset: int) -> None:
        if not 0 <= offset < len(self._data):
            raise Pbg3Error("PBG3 byte offset is outside the archive")
        self._bit_offset = offset * 8

    @property
    def bit_offset(self) -> int:
        return self._bit_offset


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
            reader.read_varint()  # unk2
            reader.read_varint()  # unk1
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
