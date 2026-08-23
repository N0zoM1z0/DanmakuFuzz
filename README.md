# DanmakuFuzz

DanmakuFuzz is a structure-aware fuzzing workbench for Touhou danmaku games.
It is built to find the fun failures, not just parser crashes:

- stage scripts that stall or drift;
- impossible timeline state;
- replay desyncs and replay-native wedges;
- ANM/runtime resource weirdness;
- accepted-but-wrong parser behavior in retail file formats.

The current implementation starts from TH06, but the project shape is
deliberately binary-first and source-optional so the same workflow can move
toward TH07/TH08-era games.

## Search model

DanmakuFuzz keeps search and confirmation separate.

- Headless runtime is the fast search engine.
- Retail Wine is the final oracle.
- Findings live as reproducible scripts plus compact payload metadata, not as
  one-off artifact directories.

That split is the core design choice: high-throughput exploration first, then
replay the interesting cases through the slower real game path.

## Two lanes

- Semantic lane: mutate ECL, replay payloads, input streams, and coordinated
  runtime resources; run them against deterministic headless traces; cluster
  and minimize the weird cases before retail confirmation.
- Parser lane: fuzz PBG3, replay, stage `.std`, message `.dat`, `cfg`,
  `score.dat`, and ANM/resource loaders in a binary-first style.

The lane boundary matters. Semantic fuzzing owns gameplay/runtime oddities.
Parser fuzzing owns accepted/rejected file-format behavior. The codebase keeps
those two ideas separate on purpose.

## What is already here

- retail ECL extraction and structure-aware mutation;
- portable source-less semantic mutation families;
- replay-native and replay-coordinated fuzzing;
- input/action semantic fuzzing;
- ANM runtime-entry campaigns;
- parser campaigns for the main TH06 retail formats;
- clustering, minimization, and retail replay handoff;
- findings tracked under `findings/` with `reproduce.py` entrypoints.

## Repository map

- `src/danmakufuzz/`: orchestration, mutation, clustering, minimization, and
  harness glue.
- `fuzzers/`: lane-level operator docs and campaign entrypoints.
- `findings/`: reviewed findings plus self-contained reproduction metadata.
- `docs/`: architecture, boundaries, portability, and retail/headless notes.
- `config/`: tracked action streams and lane defaults.
- `scripts/`: thin local setup and maintenance helpers.
- `third_party/`: isolated upstream components such as `th06-headless`.

Start here after cloning:

- [fuzzers/semantic/README.md](/home/yann/yann/touhou/DanmakuFuzz/fuzzers/semantic/README.md)
- [fuzzers/parser/README.md](/home/yann/yann/touhou/DanmakuFuzz/fuzzers/parser/README.md)
- [docs/architecture.md](/home/yann/yann/touhou/DanmakuFuzz/docs/architecture.md)
- [docs/source-less-portability.md](/home/yann/yann/touhou/DanmakuFuzz/docs/source-less-portability.md)

## Quick start

Extract the immutable TH06 ECL seed corpus from an owned game RAR:

```sh
PYTHONPATH=src python3 -m danmakufuzz.corpus.extract_ecl \
  --rar /path/to/th06.rar
```

Build the headless runtime:

```sh
scripts/build_headless.sh
```

Bootstrap an isolated local retail game directory from owned extracted files:

```sh
scripts/bootstrap_game_dir.sh /path/to/extracted/th06
```

Run one deterministic baseline:

```sh
PYTHONPATH=src python3 -m danmakufuzz.headless.baseline \
  --game-dir reference/retail/game/th06 \
  --stage 6 \
  --seed 7
```

Run one small semantic campaign:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.ecl_campaign \
  --profile core \
  --seed-ecl reference/corpus/ecl/original/ecldata6.ecl \
  --limit 32
```

## Local data and artifact policy

This repository never commits proprietary Touhou assets. Local-only inputs and
generated outputs stay under ignored paths such as:

- `reference/retail/game/th06/`
- `reference/corpus/ecl/original/`
- `artifacts/`

Most of `artifacts/` is disposable search output. Keep only the seed corpora
and a few curated review bundles you still care about. To prune generated
artifact directories while keeping the current replay corpus and the curated
replay review bundles, run:

```sh
scripts/prune_artifacts.sh --dry-run
scripts/prune_artifacts.sh
```

## Status

DanmakuFuzz is the fuzzing/orchestration layer. It does not pretend that the
headless runtime is the game. Headless is for throughput and triage; retail
Wine is still the authority when a case is worth confirming.
