# Parser fuzzing lane

Initial parser targets:

- `PBG3` archive header parsing and LZSS decompression;
- replay validation and deobfuscation;
- stage `.std` loading and object/script walking;
- stage message `.dat` loading and instruction walking;
- game cfg loading;
- `score.dat` loading;
- ANM/resource-script loading.

The tracked Python code in `src/danmakufuzz/corpus/pbg3.py` provides a clean
reference parser for corpus extraction and format understanding. Native
harnesses under `fuzzers/parser/` will target the original or reconstructed C++
implementations for sanitizer-backed fuzzing.

Current first-pass parser-lane entrypoints:

- `danmakufuzz.parser.pbg3_archive` validates archive structure and optional
  decompression;
- `danmakufuzz.parser.pbg3_campaign` mutates one retail PBG3 archive seed and
  classifies each malformed case as `parse-error`, `extract-error`, or
  `accepted`. Accepted-equivalent payloads are format characterizations, not
  interesting bug candidates;
- `danmakufuzz.parser.replay` validates replay magic, deobfuscation, checksum,
  version, and stage offsets;
- `danmakufuzz.parser.replay_campaign` mutates one replay seed and classifies
  each accepted case by which summary fields changed;
- `danmakufuzz.parser.stage_std` walks the stage header, object table, quad
  chains, and script region summary.
- `danmakufuzz.parser.stage_std_campaign` mutates one retail `.std` seed and
  classifies each case as rejected or accepted-with-drift against the baseline
  stage walk summary.
- `danmakufuzz.parser.msg_dat` walks stage message tables plus per-message
  instruction streams.
- `danmakufuzz.parser.msg_dat_campaign` mutates one retail message-script seed
  and classifies each case as rejected or accepted-with-drift against the
  baseline message summary.
- `danmakufuzz.parser.game_cfg_campaign` mutates one retail cfg seed and
  classifies fallback-default basins plus effective-field drift.
- `danmakufuzz.parser.score_dat_campaign` mutates one retail `score.dat` seed
  and classifies fallback-empty versus loaded-with-drift outcomes.
- `danmakufuzz.parser.anm_campaign` mutates one retail ANM seed and classifies
  parse errors versus accepted-with-drift resource/script summaries.

These parser lanes are intentionally binary-first. The point is to stay useful
when a future Touhou target has retail assets but no reconstructed source.
