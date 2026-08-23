# Architecture

DanmakuFuzz is built around one separation: fast search is not final proof.

## System model

The project has three layers.

### 1. Search layer

This is where throughput matters.

- deterministic headless runs
- semantic mutation and replay/input mutation
- parser acceptance/rejection campaigns
- clustering and minimization

This layer is allowed to be aggressive, disposable, and artifact-heavy.

### 2. Confirmation layer

This is where trust matters.

- retail Wine replay
- isolated retail environment setup
- replay of already-triaged cases

The confirmation layer is intentionally slower and narrower. It should consume
reviewed candidates, not raw exploration output.

### 3. Findings layer

This is the durable layer.

- `findings/` documents what matters
- each finding must rebuild its payload via `reproduce.py`
- large artifact trees are optional evidence, never the only source of truth

## Lane split

### Semantic lane

Semantic fuzzing owns gameplay and runtime oddities:

- ECL seed extraction and mutation
- source-less/raw field mutation families
- input/action mutation
- replay-native and replay-coordinated mutation
- ANM runtime-entry campaigns
- headless execution and semantic scoring
- minimization before retail confirmation

It does not own generic file-format acceptance claims.

### Parser lane

Parser fuzzing owns retail data formats:

- PBG3 archives
- replay files
- stage `.std`
- message `.dat`
- `cfg`
- `score.dat`
- ANM/resource loaders

It does not own headless runtime orchestration.

## Portability boundary

The intended shape is binary-first and source-optional.

- TH06 source or decompilation is useful, but not required for the long-term
  architecture.
- New game support should land as thin profiles/adapters, not as TH06-specific
  special cases inside the mutator core.
- Generic mutation families should stay useful even when opcode semantics are
  only partially labeled.

## External boundaries

- `third_party/th06-headless/` stays isolated and should only change via
  explicit, reviewable patches.
- retail Wine state stays outside tracked repository data.
- `touhou-solver-th06-rl` is reference material, not shared mutable state for
  this project.
- game-specific filesystem/layout differences belong in profiles or wrappers,
  not in the generic semantic core.

## Data boundaries

Tracked:

- source code
- documentation
- configuration
- compact reproduction metadata
- small sample action streams

Ignored:

- proprietary game data
- extracted seed corpora from owned games
- traces, campaign outputs, and temporary artifacts
- Wine prefixes and worker-local state
- build products
