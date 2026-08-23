from danmakufuzz.corpus.pbg3 import Pbg3Archive, Pbg3Entry, build_pbg3, compress_literal_payload, sha256_bytes
from danmakufuzz.parser.pbg3_metamorphic import (
    evaluate_pbg3_metamorphic_payload,
    generate_pbg3_metamorphic_cases,
)


def _tiny_archive() -> bytes:
    first_payload = b"ABC"
    second_payload = b"DEF!"
    first_compressed, first_checksum = compress_literal_payload(first_payload)
    second_compressed, second_checksum = compress_literal_payload(second_payload)
    return build_pbg3(
        [
            (Pbg3Entry("b.bin", first_checksum, 0, len(first_payload), unk1=1, unk2=2), first_compressed),
            (Pbg3Entry("a.bin", second_checksum, 0, len(second_payload), unk1=3, unk2=4), second_compressed),
        ]
    )


def _entry_hashes(payload: bytes) -> dict[str, str]:
    archive = Pbg3Archive.from_bytes(payload)
    return {
        entry.filename: sha256_bytes(archive.extract_entry(entry))
        for entry in archive.entries
    }


def test_pbg3_metamorphic_cases_preserve_entry_map() -> None:
    seed = _tiny_archive()
    baseline = _entry_hashes(seed)

    cases = generate_pbg3_metamorphic_cases(seed)

    assert {case.name for case in cases} >= {
        "literal-repack-original-order",
        "source-compressed-repack-reversed-order",
        "source-compressed-entry-padding-aa-8",
        "append-trailing-garbage-aa-64",
        "unknown-fields-pattern",
    }
    for case in cases:
        evaluation = evaluate_pbg3_metamorphic_payload(case.payload, baseline)
        assert evaluation["relation_holds"] is True, case.name
        assert evaluation["metamorphic_violation"] is False, case.name


def test_pbg3_metamorphic_violation_reports_changed_entry() -> None:
    seed = _tiny_archive()
    baseline = _entry_hashes(seed)
    archive = Pbg3Archive.from_bytes(seed)
    changed = archive.replace({"a.bin": b"changed"})

    evaluation = evaluate_pbg3_metamorphic_payload(changed, baseline)

    assert evaluation["relation_holds"] is False
    assert evaluation["metamorphic_violation"] is True
    assert evaluation["violation_kind"] == "accepted-with-drift"
