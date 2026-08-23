from danmakufuzz.ecl_ir.model import EclFile
from danmakufuzz.ecl_ir.mutators import Mutant, _mutant_dedupe_key


def test_mutant_dedupe_key_uses_metadata_site_key_for_pathless_mutants() -> None:
    ecl = EclFile(sub_count=0, main_count=0, timeline_offsets=(0, 0, 0), timeline=[], subs=[])
    first = Mutant("timeline-time-sampled-0", None, ecl, metadata={"site_key": "timeline:i0000"})
    second = Mutant("timeline-time-sampled-0", None, ecl, metadata={"site_key": "timeline:i0001"})
    assert _mutant_dedupe_key(first) != _mutant_dedupe_key(second)
