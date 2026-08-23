# Semantic lane

This lane owns:

- ECL seed corpus generation;
- ECL mutation;
- headless execution;
- semantic interestingness scoring;
- later minimization and retail replay handoff.

Native runtime changes, when needed, should be staged through
`third_party/th06-headless/` with minimal, reviewable patches.

## Current entrypoint

Run a targeted Stage ECL campaign with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.ecl_campaign \
  --seed-ecl reference/corpus/ecl/original/ecldata6.ecl \
  --limit 32
```

Switch that entrypoint into the reusable cross-game `core` profile with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.ecl_campaign \
  --profile core \
  --seed-ecl reference/corpus/ecl/original/ecldata6.ecl \
  --limit 32
```

The `core` profile narrows mutation selection to portable control-flow, timing,
bullet-count, drop-item, raw opcode/arg, and timeline families. It skips
structural payload damage and boss-only families by default.

Add `--mutation-mode exploration` to switch from fixed targeted cases to the
seeded sampler. That sampler still keeps semantic anchor values, but each site
also mixes context-aware, relative, scaled, bit-flip, and wide random values.
Use `--random-seed` to roam the sampler and `--samples-per-site` to control the
per-site fanout without changing the surrounding campaign logic.

When exploration mode runs without an explicit limit, the runners now apply a
small automatic mutant budget instead of materializing the full sampled set:

- `semantic.ecl_campaign`: `128` mutants;
- `semantic.family_sweep`: `32` mutants per seed;
- `semantic.boss_sweep`: `32` mutants per seed;
- `semantic.exploration_grid`: `32` mutants per task.

Pass an explicit `--limit` / `--limit-per-seed` / `--limit-per-task` to choose
another budget, or `--full-mutant-set` to force the old unbounded behavior.

Exploration mode now defaults `selection_mode=auto` to `family-site` instead of
plain `site`. In that mode, limit-based selection first round-robins across
mutation families, then round-robins across opcode sites inside each family.
That keeps the small auto-budget from being swallowed by one high-site-count
family such as `shoot-interval`, while still spreading picks across distinct
sites inside each family.

When the campaign uses `selection_mode=site` or `selection_mode=family-site`,
the exploration lane also reorders mutants inside each ECL site before
limit-based selection. This avoids the older append-order bias where low
`--limit` runs mostly exercised the first family/value emitted per site, which
was too close to template testing.

Inside each sampled field family, low `--samples-per-site` budgets also now
shuffle the candidate-lane schedule itself instead of always draining the first
few groups in a fixed order. That matters because earlier `4`-sample runs kept
over-exercising anchor/relative lanes while starving later bit-flip, wide
random, and crossed-pair lanes. Paired-field exploration additionally mixes
left/right sampled pools directly now, so cross-field lanes are not limited to
just diagonal or mirrored pairs. Exploration also now emits adjacent
instruction-time paired mutants as first-class multi-site cases, with explicit
`site_key` / `sites` metadata so later selection and findings can distinguish
them from single-site scalar mutations. The source-less lane now also emits raw
families such as `generic-opcode`, `generic-arg16`, `generic-arg32-cross`,
`timeline-time`, `timeline-arg0`, and `adjacent-timeline-time-cross`, so
future games can still be fuzzed meaningfully before opcode semantics are fully
labeled.

Sweep that reusable family set across the playable retail seeds with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.family_sweep \
  --limit-per-seed 8
```

Push the same reusable lane across a seed-ECL × sampler-seed grid with isolated
worker game copies using:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.exploration_grid \
  --seed-ecl reference/corpus/ecl/original/ecldata1.ecl \
  --seed-ecl reference/corpus/ecl/original/ecldata2.ecl \
  --random-seed-count 4 \
  --limit-per-task 8 \
  --worker-count 2
```

This runner keeps the campaign logic generic but lifts throughput in the way
that matters for finding weird cases:

- each worker gets its own copied game directory under the artifact root;
- each task is one `(seed_ecl, random_seed)` pair, so you can widen exploration
  without changing the mutator families themselves;
- worker-local baseline traces are cached per stage/profile/control-seed, so the
  same worker does not rerun an identical baseline for every sampler seed;
- every task still writes its own `summary.jsonl` and `campaign.json`, keeping
  later clustering, minimization, and retail replay handoff decoupled.

Switch that entrypoint into a longer boss-oriented profile with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.ecl_campaign \
  --profile boss \
  --seed-ecl reference/corpus/ecl/original/ecldata6.ecl \
  --limit 8
```

The `boss` profile promotes the longer `1800`-tick action stream, forces
`--continue-after-hit`, widens the timeout, and defaults the mutant selection to
boss/timer/script families such as `boss-timer-` and `time-set-`. Add repeated
`--name-filter` flags to narrow further.

Sweep those boss-oriented families across the playable retail seeds with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.boss_sweep \
  --limit-per-seed 8
```

This sweep skips `ecldata7.ecl` by default because current headless Practice
startup only supports stages `1..6`.

## ANM runtime entry lane

Run the generic ANM runtime-entry campaign with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.anm_runtime_campaign
```

By default this lane:

- auto-selects archive entries matching `stgXbg.anm`, `stgXenm.anm`, and
  `stgXenm2.anm`;
- includes Extra stage seeds when headless Practice supports them;
- reuses one headless baseline trace per stage instead of rerunning the same
  baseline for every entry;
- focuses the initial mutant budget on four source-less ANM sites that already
  map well onto runtime weirdness:
  `first-sprite-offset-zero`, `first-script-id-ffff`,
  `first-script-offset-zero`, and `first-instr-argsize-zero`;
- filters review toward `anm-script-drift`, `anm-non-finite`, and
  `anm-set-active-sprite-failure`.

Useful knobs:

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.anm_runtime_campaign \
  --entry stg1bg.anm \
  --entry stg1enm.anm \
  --mutant-profile accepted \
  --limit-per-entry 8
```

This lane keeps the full per-case payload and `result.json` under each entry
artifact directory, but the top-level review files stay compact:

- `summary.jsonl` records one concise line per executed case;
- `target-hits.jsonl` keeps only cases that hit the chosen runtime target
  kinds;
- `campaign.json` records baseline reuse, per-entry hit counts, and skipped
  entries.

Two useful accepted-sweep entrypoints are:

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.anm_runtime_campaign \
  --entry-kind enm2 \
  --mutant-profile accepted \
  --limit-per-entry 6
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.anm_runtime_campaign \
  --stage-filter 7 \
  --mutant-profile accepted \
  --limit-per-entry 6
```

Those sweeps now also write `clusters.json` beside each entry summary and at the
campaign root, plus a compact `filters` block in `campaign.json`, so later
basin harvest does not need to rediscover which stage / entry-kind slice was
actually run.

## Input lane

Run the generic headless input/action lane with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.input_campaign \
  --stage 6 \
  --seed 7 \
  --actions config/headless_baseline_actions_1800.txt \
  --max-ticks 1800 \
  --continue-after-hit \
  --limit 12 \
  --random-seed 7 \
  --samples-per-site 3
```

This lane is intentionally narrower than raw gameplay differential fuzzing:

- it mutates the action stream instead of ECL;
- it reruns every mutant twice with the same seed;
- it only keeps strong runtime findings such as stalls, late script/timeline
  wedges, explosions, non-finite values, or repeat-desyncs;
- it round-robins selection across input families and input sites when
  `--limit` is active, so the budget does not get swallowed by early `t0`
  bursts.

Each case gets its own ignored artifact directory containing:

- the loose-resource override payload;
- the headless trace;
- the combined runtime log;
- a `result.json` summary.

For runtime stability, the campaign now archives each payload under that case
artifact path but stages the active override into one fixed per-worker
directory before launching headless. That keeps the preserved payloads portable
without letting per-case artifact path strings perturb the semantic run.

The semantic lane now defaults headless traces to a compact count-oriented
format for `items`, `bullets`, and `lasers`. That keeps the scheduler-facing
enemy/state data intact while cutting the hottest trace size and JSON parse
costs. Compact traces also retain aggregate non-finite counters for those
entity classes so the semantic oracle does not silently lose that signal. Use
`--full-entity-trace` on `semantic.ecl_campaign` or `headless.baseline` when
you explicitly need the legacy per-entity arrays.

The campaign root also writes `summary.jsonl` and `campaign.json`.

## Replay semantic/desync lane

Run the replay-derived semantic lane with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_desync_campaign \
  --stage 6 \
  --difficulty 3 \
  --character 0 \
  --shot-type 0 \
  --actions config/headless_baseline_actions_1800.txt \
  --max-ticks 1800 \
  --continue-after-hit \
  --limit 12 \
  --trace-compact-counts
```

Or point it at a real `.rpy` and let the lane infer stage / difficulty / shot
layout directly from the replay header and stage payload:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_desync_campaign \
  --input path/to/case.rpy \
  --max-ticks 1800 \
  --continue-after-hit \
  --limit 12
```

This lane keeps the setup generic across Touhou games that still have the same
replay-style compressed input timeline:

- it turns replay stage payloads into raw headless input masks instead of
  depending on labeled TH06-only input semantics;
- it can synthesize a replay seed from actions, or mutate a real replay file;
- when `--input` is a real replay, it now also defaults the headless RNG seed
  from that replay stage payload instead of forcing a fixed external seed;
- Extra-stage TH06 replays expose `difficulty=4`; the current TH06 headless
  runner only accepts `0..3`, so the replay lane normalizes Stage 7 / Extra
  into headless difficulty `3` while preserving the original replay difficulty
  in campaign metadata;
- it reruns every mutant twice and keeps only strong runtime wedges and
  repeat-desyncs;
- `--limit` uses family/site-diverse replay-mutant selection instead of plain
  append order, so short sweeps do not collapse into only `t0` cases.

Replay mutation now has three profiles:

- `input`: mutate the expanded action-mask stream only;
- `native`: mutate replay-native fields such as header route/difficulty,
  stage RNG seed, compressed bookmark timing, and same-replay stage-payload
  borrowing;
- `coordinated`: mutate multiple replay-native sites together, currently
  `header-route + stage-seed`, `header-difficulty + stage-seed`,
  `stage-payload-borrow + stage-seed`, and
  `stage-payload-borrow + header-route + stage-seed`, plus
  stage-local `bookmark + stage-seed` combinations for single-slot replays
  such as Extra-stage corpora;
- `all`: combine `input + native`, then apply the same diverse selection pass;
- `all-coordinated`: combine `coordinated + input + native`.

For native replay fuzzing specifically:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_desync_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-002.rpy \
  --stage 7 \
  --max-ticks 1800 \
  --mutant-profile native \
  --limit 6 \
  --continue-after-hit \
  --trace-compact-counts
```

For replay-native coordinated fuzzing specifically:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_desync_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-001.rpy \
  --stage 4 \
  --max-ticks 1800 \
  --mutant-profile coordinated \
  --limit 8 \
  --continue-after-hit \
  --trace-compact-counts
```

The artifact root keeps `seed.rpy`, `baseline-actions.txt`, one per-case
`input.rpy`, plus `summary.jsonl`, `clusters.json`, and `campaign.json`.

Replay clustering groups cases three ways:

- `exact_clusters`, keyed by the exact `run_a.trace_sha256`;
- `sink_clusters`, keyed by a coarser replay/runtime sink signature so “same
  late basin, different prelude” stays visible.
- `pattern_clusters`, keyed by stage + replay mutation pattern + coarse sink
  metadata, so one replay-specific mutant like `stage-payload-borrow-next-s2`
  can be reviewed across multiple source replays even when each trace hash is
  different.

It also emits two replay-specific post-pass views for the noisy
`replay-stable-trace-drift` class:

- `stable_drift_clusters`, which collapse “same late wedge, different replay
  prelude” cases more aggressively and keep non-stable companion findings such
  as `stage-script-drift`, `ecl-timeline-drift`, `stalled-progress`, or
  `process-exit`;
- `stable_drift_review_queue`, which reprioritizes those clusters for human
  review and adds a greedy `mutant_cover`, so one basin with many near-duplicate
  mutants can be reviewed from a much smaller representative subset.

Rebuild that summary later from any replay result, summary, campaign, or a
whole replay artifact tree with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_cluster \
  --result artifacts/semantic-replay/.../campaign.json
```

When you want to feed real full-game `.rpy` corpora instead of a single
isolated stage replay, use the corpus runner:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input-dir artifacts/replay-corpus-public/th06 \
  --limit-replays 3 \
  --limit-stage-slots 6 \
  --limit 6 \
  --continue-after-hit \
  --trace-compact-counts
```

This runner validates each replay, enumerates its populated stage slots, and
then launches one child replay-desync campaign per `(replay, stage-slot)` pair.
That matters for public TH06 corpora because most score replays are full-game
records with stages `1..6` populated, while Extra records usually only populate
slot `7`. The corpus root also writes a cross-replay `clusters.json`, so
stable-trace-drift basins can be reviewed without opening every child campaign
manually.

The tracked source-of-truth for the initial public TH06 corpus lives under:

```text
reference/corpus/replay/public/th06/
```

Rebuild it locally with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.corpus.fetch_public_replays \
  --manifest reference/corpus/replay/public/th06/manifest.json \
  --output-dir artifacts/replay-corpus-public/th06
```

Then a focused stage-seed sweep across the public corpus looks like:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input-dir artifacts/replay-corpus-public/th06 \
  --stage-filter 1 --stage-filter 2 --stage-filter 3 \
  --stage-filter 4 --stage-filter 5 --stage-filter 6 --stage-filter 7 \
  --max-ticks 1800 \
  --mutant-profile native \
  --name-filter stage-seed \
  --limit 8 \
  --continue-after-hit \
  --trace-compact-counts \
  --artifact-dir artifacts/replay-stage-seed-focus-v1
```

And a focused coordinated borrow/seed sweep looks like:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-001.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-801.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-802.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-804.rpy \
  --stage-filter 4 \
  --max-ticks 1800 \
  --mutant-profile coordinated \
  --name-filter coordinated-borrow \
  --limit 8 \
  --continue-after-hit \
  --trace-compact-counts \
  --artifact-dir artifacts/replay-coordinated-stage4-borrow-focus-v1
```

For an Extra-only coordinated harvest, where stage-payload borrowing is usually
unavailable and the new `bookmark + seed` families matter, use:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-002.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-803.rpy \
  --stage-filter 7 \
  --max-ticks 1800 \
  --mutant-profile coordinated \
  --limit 12 \
  --continue-after-hit \
  --trace-compact-counts \
  --artifact-dir artifacts/replay-coordinated-extra-v2
```

And the broader coordinated corpus harvest used on August 23, 2026 was:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input-dir artifacts/replay-corpus-public/th06 \
  --stage-filter 1 --stage-filter 2 --stage-filter 3 \
  --stage-filter 4 --stage-filter 5 --stage-filter 6 --stage-filter 7 \
  --max-ticks 1800 \
  --mutant-profile coordinated \
  --limit 8 \
  --continue-after-hit \
  --trace-compact-counts \
  --artifact-dir artifacts/replay-coordinated-corpus-v2
```

## Coordinated resource lane

Run coordinated stage-resource mutation with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.resource_coordination_campaign \
  --stage 7 \
  --mode anm-triad \
  --limit 4
```

Or widen into coupled `ANM + ECL` cases with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.resource_coordination_campaign \
  --stage 7 \
  --mode all \
  --limit 6
```

This lane is the current generic answer to “multi-resource weirdness”:

- `anm-triad` applies the same accepted ANM mutant across the stage
  `bg/enm/enm2` bundle at once;
- `anm-ecl` anchors one accepted ANM mutant, then pairs it with source-less ECL
  exploration families such as `generic-opcode`, `generic-arg16`,
  `generic-arg32-cross`, `timeline-time`, and `instruction-time`;
- every case keeps a portable per-case override bundle under its artifact
  directory, then stages one active override tree just before launch so the
  preserved payload paths do not perturb runtime behavior.

The current implementation is still TH06-backed for execution, but the case
construction is intentionally stage-resource-oriented rather than hardcoding
TH06-only stage logic. That is the piece meant to carry forward into later
games first.

Each coordinated-resource campaign now also writes `clusters.json` beside
`summary.jsonl`, with two useful views:

- `exact_clusters`, grouped by exact `trace_sha256`;
- `sink_clusters`, grouped by a coarser sink signature derived from the late
  trace snapshot.

Rebuild that clustering later from a result, summary, campaign, or whole
artifact directory with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.resource_coordination_cluster \
  --result artifacts/tmp-resource-coordination-smoke
```

And minimize one coordinated bundle by dropping whole override files while
preserving the same coarse sink with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.resource_coordination_minimize \
  --result artifacts/tmp-resource-coordination-smoke/0004-anm-triad-first-instr-opcode-255/result.json
```

The current Stage 7 `anm-triad` / `anm-ecl` SIGSEGV basin is a good example of
why this matters: multiple different coordinated bundles collapse into the same
late `tick=440` sink, and the minimizer shows that sink is reducible to just
`stg7enm.anm`.

The generic differential oracle is intentionally a bit stricter than before for
plain bullet-count drift. It still keeps large sustained surges and collapses,
but it no longer treats every small persistent bullet delta as equally
interesting. That keeps the portable exploration lane focused on stronger
semantic route changes instead of flooding reviews with weak count wobble.

Minimize a captured interesting case with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.minimize_case \
  --result artifacts/semantic/.../result.json
```

Cluster interesting semantic cases before minimization or retail replay with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.cluster_cases \
  --from-artifacts
```

The cluster summary groups cases by primary headless finding plus mutant name,
adds a wider finding/source family view, and annotates which source cases
already have minimized summaries for easier retail handoff.

Turn that cluster summary into a batch minimization queue with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.batch_minimize \
  --cluster-summary artifacts/semantic-clusters/.../summary.json \
  --only-missing
```

This wrapper skips cluster representatives that already have a minimized summary
and only runs `semantic.minimize_case` on the missing handoff candidates.

Group a family sweep or one finding family by common first-divergence tick and
common sink snapshot with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.trace_basins \
  artifacts/semantic-family-sweep/20260822T-call-sub-portable-explore-a/ecldata3/summary.jsonl
```

This is useful when multiple different mutations collapse into one weird late
state and you want to prove they first diverge at the same tick / field instead
of hand-reading traces one by one.

Map one exact i32 ECL site across a hand-picked value set with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.site_basin_mapper \
  --seed-ecl reference/corpus/ecl/original/ecldata2.ecl \
  --stage 2 \
  --sub-index 2 \
  --instruction-index 9 \
  --field-offset 8 \
  --family bullet-count2 \
  --field-name bullet_count2 \
  --expected-opcode 69 \
  --expected-original-value 2 \
  --value 1 \
  --value 0 \
  --value -12208722 \
  --value 2147483596 \
  --value 3 \
  --value 5
```

This mapper keeps one deterministic baseline trace, rebuilds exact payloads for
one site, and then groups the outcomes in two ways:

- strict `trace_sha256` groups when you want exact replay-equivalent basins;
- broader `scheduler_signature` groups when multiple traces still collapse into
  the same frozen script/timeline state.

Use it when one hotspot looks more like a fractured value landscape than a
single reproducible finding and you want to decide which basin is worth
promoting into `findings/semantic/`.

When a case only reproduces under the original loose-resource override path,
`semantic.minimize_case` now falls back automatically and records the selected
`reproduction_mode` in `summary.json` and `history.jsonl`.

Prepare or launch an isolated retail confirmation worker from either a
semantic case or a minimized case with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.confirm_case \
  --result artifacts/semantic-minimized/.../summary.json \
  --prepare-only \
  --dry-run
```

Batch replay minimized or semantic results through the retail runner with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.batch_confirm \
  --from-minimized \
  --practice-stage 6 \
  --difficulty 3 \
  --timeout-seconds 20
```

Preview a prioritized replay queue without launching Wine with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.batch_confirm \
  --from-minimized \
  --interesting-only \
  --max-per-finding 1 \
  --list-only
```

Load prior retail summaries/reports and skip source cases that already have a
retail confirmation with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.batch_confirm \
  --history artifacts/tmp-retail-oracle2-smoke.V69OIr \
  --skip-known-source \
  --list-only \
  --result artifacts/semantic-minimized/bullet-sprite-16-s01-i0003/summary.json
```

Skip only when prior retail history predicts one stable normalized signature with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.batch_confirm \
  --history artifacts/tmp-retail-batch-priority-smoke.51UKuj/summary.json \
  --from-minimized \
  --interesting-only \
  --max-per-finding 1 \
  --skip-known-signature \
  --list-only
```

Drive one Stage 6 semantic case into retail Practice Lunatic / Reimu A with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.confirm_case \
  --result artifacts/semantic/fullstage6-stage6-seed7-ecldata6/0004-bullet-count1-zero-s01-i0003/result.json \
  --practice-stage 6 \
  --difficulty 3 \
  --timeout-seconds 20
```

The retail runner now records a window census and classifies at least:

- `game-window-live`
- `crash-dialog`
- `wine-crash-log`
- `abnormal-exit`

Crash signatures are normalized before they become batch-level
`retail_signature_key`s, so the same Wine crash still groups together when only
thread ids or fault addresses drift between replays.
