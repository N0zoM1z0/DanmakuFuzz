from __future__ import annotations

from pathlib import Path

from ..corpus.pbg3 import Pbg3Archive


def load_input_bytes(*, input_path: Path | None, archive_path: Path | None, entry_name: str | None) -> tuple[bytes, str]:
    if input_path is not None:
        resolved = input_path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"missing input file: {resolved}")
        return resolved.read_bytes(), str(resolved)

    if archive_path is None or entry_name is None:
        raise ValueError("either --input or both --archive and --entry are required")

    resolved_archive = archive_path.resolve()
    if not resolved_archive.is_file():
        raise FileNotFoundError(f"missing archive: {resolved_archive}")
    archive = Pbg3Archive.from_bytes(resolved_archive.read_bytes())
    return archive.extract(entry_name), f"{resolved_archive}!{entry_name}"
