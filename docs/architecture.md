# Architecture

DanmakuFuzz splits runtime search from final confirmation.

## Lane split

### Semantic lane

The semantic lane owns:

- retail ECL seed extraction;
- structure-aware mutation;
- headless execution;
- semantic interestingness scoring;
- minimization before retail replay.

It does **not** own parser memory-corruption claims against unrelated file
formats.

### Parser lane

The parser lane owns:

- PBG3 archive parsing and decompression fuzzing;
- replay parser fuzzing;
- stage `.std` loader fuzzing;
- future standalone harnesses for other TH06 formats.

It does **not** own headless runtime orchestration.

## External boundaries

- `third_party/th06-headless/` is isolated and may be patched only through
  explicit, reviewable changes or patch files.
- retail Wine state remains outside this repository's tracked tree.
- `touhou-solver-th06-rl` is treated as reference material, not as mutable
  project state.

## Data boundaries

Tracked:

- source code
- configuration
- documentation
- small sample action streams

Ignored:

- proprietary game data
- extracted corpus payloads
- traces and artifacts
- Wine prefixes and worker state
- build outputs
