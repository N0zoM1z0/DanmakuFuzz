# DanmakuFuzz

DanmakuFuzz is a structure-aware fuzzing workbench for Touhou danmaku games.
The current target is TH06, but the design is deliberately binary-first and
source-optional: learn the file formats, mutate the spell machinery, run fast
headless traces, then make the real game under Wine pronounce judgment.

It is built for more than parser crashes. The interesting failures are the ones
that feel like the Scarlet Devil Mansion's machinery slipping a gear:

- ECL timelines that turn a stage into a crash or a frozen frame;
- replay bookmark edits that desync the action stream cleanly;
- ANM resource tables that are accepted, loaded, and then break retail;
- parser behaviors that are equivalent, benign drift, or actual candidates,
  with those claims kept separate.

## Oracle Model

DanmakuFuzz keeps search and confirmation separate:

- Headless runtime is the fast scout.
- Local parsers explain payload shape.
- Reducers collapse candidates to the smallest useful semantic change.
- Wine/retail is the promotion gate.
- Findings are committed as reproducible recipes and metadata, not raw artifact
  dumps.

That split is the main contract. Headless can say "this is worth a look."
Retail confirmation says "this happens to the shipped game."

## Two lanes

- Semantic lane: mutate ECL, replay payloads, input streams, and coordinated
  runtime resources; run them against deterministic headless traces; cluster
  and minimize the candidates before retail confirmation.
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
- metamorphic checks for known-equivalent replay, PBG3, ANM, and STD changes;
- confirmed findings tracked under `findings/` with `reproduce.py` entrypoints
  and portable payload recipes.

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

- [fuzzers/semantic/README.md](fuzzers/semantic/README.md)
- [fuzzers/parser/README.md](fuzzers/parser/README.md)
- [docs/retail-confirmation.md](docs/retail-confirmation.md)
- [docs/source-less-portability.md](docs/source-less-portability.md)
- [findings/README.md](findings/README.md)

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

## Local Data

This repository never commits proprietary Touhou assets. Local-only inputs and
generated outputs stay under ignored paths such as:

- `reference/retail/game/th06/`
- `reference/corpus/ecl/original/`
- `artifacts/`

Most of `artifacts/` is disposable search output: worker game copies, Wine
prefixes, screenshots, traces, and queue scratch space. The durable pieces are
the checked-in recipes under `findings/` and the owned local seed data under
`reference/`.

To prune generated artifact directories while keeping the current replay corpus,
curated replay review bundles, and the compact closure summaries for promoted
findings, run:

```sh
scripts/prune_artifacts.sh --dry-run
scripts/prune_artifacts.sh
```

## Current TH06 Status

The TH06 pass now has retail-confirmed ECL and ANM crash/stall basins, replay
and parser format observations, and a stricter false-positive boundary between
headless candidates and Wine positives. The project is ready to stop treating
raw artifacts as the product: the product is the oracle pipeline plus the
reproducible findings.
