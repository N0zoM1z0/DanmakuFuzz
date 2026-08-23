# Parser fuzzing lane

Initial parser targets:

- `PBG3` archive header parsing and LZSS decompression;
- replay validation and deobfuscation;
- stage `.std` loading and object/script walking.

The tracked Python code in `src/danmakufuzz/corpus/pbg3.py` provides a clean
reference parser for corpus extraction and format understanding. Native
harnesses under `fuzzers/parser/` will target the original or reconstructed C++
implementations for sanitizer-backed fuzzing.

Current first-pass parser-lane entrypoints:

- `danmakufuzz.parser.pbg3_archive` validates archive structure and optional
  decompression;
- `danmakufuzz.parser.pbg3_campaign` mutates one retail PBG3 archive seed and
  classifies each malformed case as `parse-error`, `extract-error`, or
  `accepted`;
- `danmakufuzz.parser.replay` validates replay magic, deobfuscation, checksum,
  version, and stage offsets;
- `danmakufuzz.parser.replay_campaign` mutates one replay seed and classifies
  each accepted case by which summary fields changed;
- `danmakufuzz.parser.stage_std` walks the stage header, object table, quad
  chains, and script region summary.
- `danmakufuzz.parser.stage_std_campaign` mutates one retail `.std` seed and
  classifies each case as rejected or accepted-with-drift against the baseline
  stage walk summary.
