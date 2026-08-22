# DanmakuFuzz

DanmakuFuzz is a Touhou 6 fuzzing workbench.

The repository is organized around two intentionally separate lanes:

- `semantic/`: structure-aware ECL and danmaku fuzzing against a deterministic
  headless runtime, with retail Wine replay kept as the confirmation oracle.
- `parser/`: traditional parser and loader fuzzing for PBG3, replay, stage
  data, and adjacent file formats.

The project is designed to avoid coupling runtime orchestration, corpus
management, mutation logic, and native harness code. Each lane can evolve
independently.

## Current focus

The first milestone set is:

1. extract the immutable retail ECL seed corpus;
2. produce a fixed-seed headless baseline trace;
3. prepare a fuzz-only resource override path for headless execution;
4. implement a first-pass ECL IR parser/serializer and targeted mutators;
5. implement semantic interestingness rules;
6. scaffold parser fuzz harnesses for PBG3, replay, and stage loaders;
7. replay interesting cases against retail Wine only after headless triage.

## Repository layout

- `src/danmakufuzz/`: Python tooling for corpus extraction, headless
  orchestration, ECL IR mutation, and semantic triage.
- `docs/`: design contracts and separation boundaries.
- `fuzzers/`: per-lane harness layout and native-target planning.
- `config/`: tracked non-proprietary configuration, sample actions, and lane
  defaults.
- `scripts/`: thin shell wrappers around third-party runtime setup.
- `third_party/`: isolated upstream dependencies such as `th06-headless`.

Runtime artifacts, extracted game data, mutable corpora, traces, and local
state are intentionally ignored.

## Local data policy

This repository never commits proprietary Touhou assets. Expected local-only
inputs live under ignored directories such as:

- `reference/retail/game/th06/`
- `reference/corpus/ecl/original/`
- `artifacts/headless/`
- `artifacts/retail/`

## Quick start

Create the immutable ECL baseline corpus directly from an owned TH06 RAR:

```bash
python -m danmakufuzz.corpus.extract_ecl \
  --rar /path/to/th06.rar
```

Prepare the headless dependency:

```bash
scripts/build_headless.sh
```

Run a deterministic baseline trace once the headless runtime and retail game
directory are available:

```bash
python -m danmakufuzz.headless.baseline \
  --game-dir /path/to/th06 \
  --stage 6 \
  --seed 7
```

## Status

This repository is the orchestration and fuzzing layer. It does not claim
Windows-equivalent execution by itself. Headless acceleration is a search
engine; retail Wine remains the final confirmation target.
