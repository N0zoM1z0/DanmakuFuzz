# Architecture

DanmakuFuzz splits runtime search from final confirmation.

## Lane split

### Semantic lane

The semantic lane owns:

- retail ECL seed extraction;
- structure-aware mutation;
- action/input mutation and replay-style determinism checks;
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
- stage message `.dat` loader fuzzing;
- cfg / `score.dat` / ANM loader fuzzing;
- future standalone harnesses for other Touhou retail formats.

It does **not** own headless runtime orchestration.

The long-term shape is binary-first and source-less: parser lanes should remain
useful even when only retail assets exist for TH07/TH08-era games.

## External boundaries

- `third_party/th06-headless/` is isolated and may be patched only through
  explicit, reviewable changes or patch files.
- retail Wine state remains outside this repository's tracked tree.
- `touhou-solver-th06-rl` is treated as reference material, not as mutable
  project state.
- game-specific path/layout differences should stay behind thin profile or
  adapter boundaries, not inside the mutator core.

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
