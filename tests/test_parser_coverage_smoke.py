import ctypes

from danmakufuzz.corpus.pbg3 import Pbg3Entry, build_pbg3, compress_literal_payload
from danmakufuzz.parser.anm import AnmRawEntry
from danmakufuzz.parser.coverage_smoke import (
    coverage_signature,
    evaluate_parser_payload,
    run_parser_coverage_smoke,
)
from danmakufuzz.parser.replay import synthetic_replay_seed
from danmakufuzz.parser.stage_std import RawStageHeader


def _pbg3_seed() -> bytes:
    compressed, checksum = compress_literal_payload(b"abc")
    return build_pbg3(
        [
            (
                Pbg3Entry(
                    filename="a.txt",
                    checksum=checksum,
                    data_offset=0,
                    uncompressed_size=3,
                ),
                compressed,
            )
        ]
    )


def _anm_seed() -> bytes:
    entry = AnmRawEntry()
    entry.numSprites = 0
    entry.numScripts = 0
    entry.nameOffset = ctypes.sizeof(AnmRawEntry)
    entry.alphaNameOffset = 0
    entry.version = 2
    entry.nextOffset = 0
    return bytes(entry) + b"unit.anm\x00"


def _stage_std_seed() -> bytes:
    header = RawStageHeader()
    header.nbObjects = 0
    header.nbFaces = 0
    header.facesOffset = ctypes.sizeof(RawStageHeader)
    header.scriptOffset = ctypes.sizeof(RawStageHeader)
    header.stageName = b"unit-stage"
    return bytes(header)


def test_coverage_signature_separates_acceptance_and_error_paths() -> None:
    accepted = evaluate_parser_payload("pbg3", _pbg3_seed())
    rejected = evaluate_parser_payload("pbg3", b"BAD!")

    assert accepted["classification"] == "accepted"
    assert rejected["classification"] == "parse-error"
    assert coverage_signature("pbg3", accepted) != coverage_signature("pbg3", rejected)


def test_parser_coverage_smoke_discovers_signatures_for_all_targets() -> None:
    report = run_parser_coverage_smoke(
        {
            "pbg3": _pbg3_seed(),
            "replay": synthetic_replay_seed(),
            "anm": _anm_seed(),
            "stage-std": _stage_std_seed(),
        },
        max_evaluations=120,
        mutation_limit=8,
        max_generation=1,
    )

    by_target = report["unique_coverage_by_target"]
    assert set(by_target) == {"pbg3", "replay", "anm", "stage-std"}
    assert all(count >= 1 for count in by_target.values())
    assert report["unique_coverage_signatures"] >= 8
    assert any(item["new_coverage"] is True for item in report["summary"])
