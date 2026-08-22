from danmakufuzz.corpus.pbg3 import Pbg3Archive, Pbg3Entry, build_pbg3, compress_literal_payload, sha256_bytes
from danmakufuzz.parser.pbg3_campaign import evaluate_pbg3_payload
from danmakufuzz.parser.pbg3_mutants import generate_pbg3_mutants


def _tiny_archive() -> bytes:
    first_payload = b"ABC"
    second_payload = b"DEF!"
    first_compressed, first_checksum = compress_literal_payload(first_payload)
    second_compressed, second_checksum = compress_literal_payload(second_payload)
    return build_pbg3(
        [
            (Pbg3Entry("a.bin", first_checksum, 0, len(first_payload)), first_compressed),
            (Pbg3Entry("b.bin", second_checksum, 0, len(second_payload)), second_compressed),
        ]
    )


def test_build_pbg3_roundtrip_extracts_payloads() -> None:
    blob = _tiny_archive()
    archive = Pbg3Archive.from_bytes(blob)
    assert [entry.filename for entry in archive.entries] == ["a.bin", "b.bin"]
    assert archive.extract("a.bin") == b"ABC"
    assert archive.extract("b.bin") == b"DEF!"


def test_generate_pbg3_mutants_includes_accepted_and_rejected_families() -> None:
    mutants = {mutant.name for mutant in generate_pbg3_mutants(_tiny_archive())}
    assert "append-garbage-256" in mutants
    assert "first-entry-checksum-zero" in mutants
    assert "duplicate-entry-name" in mutants


def test_evaluate_pbg3_payload_distinguishes_parse_and_acceptance() -> None:
    baseline = Pbg3Archive.from_bytes(_tiny_archive())
    baseline_hashes = {
        entry.filename: sha256_bytes(baseline.extract_entry(entry))
        for entry in baseline.entries
    }
    accepted = evaluate_pbg3_payload(_tiny_archive() + (b"\xAA" * 32), baseline_hashes)
    assert accepted["classification"] == "accepted"
    parse_error = evaluate_pbg3_payload(b"\x00\x00\x00\x00" + _tiny_archive()[4:], baseline_hashes)
    assert parse_error["classification"] == "parse-error"
