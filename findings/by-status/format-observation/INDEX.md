# Format Observation

These entries document accepted/equivalent format behavior or loader model
facts. They are useful for understanding parser boundaries, but they are not
bug findings.

- `findings/parser/pbg3-append-garbage-equivalent-acceptance`: accepted and
  extraction-equivalent trailing-garbage behavior. This is explicitly
  `FORMAT_CHARACTERIZATION`, not a bug candidate.
- `findings/parser/pbg3-entry-map-metamorphic-equivalence`: 66/66
  archive-level PBG3 metamorphic transforms across 6 unique retail archives
  preserved the filename-to-extracted-payload map.
- `findings/runtime/anm-stage6-metamorphic-runtime-equivalence`: 12/12 Stage 6
  ANM header/script-table metamorphic transforms produced the same headless
  runtime trace as baseline.
- `findings/semantic/replay-action-stream-metamorphic-equivalence`: 35/35
  replay encoding metamorphic transforms preserved bounded action streams and
  headless runtime trace/state.
- `findings/runtime/stage-std-metadata-metamorphic-runtime-equivalence`: 49/49
  stage `.std` metadata/unknown-field transforms preserved headless runtime
  trace across stages 1-7.

Parser findings that are accepted with semantic drift, extraction failure, or
native crash evidence should stay outside this bucket.
