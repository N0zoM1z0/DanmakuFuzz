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
bullet-count, drop-item, and `time-set` families. It skips structural payload
damage and boss-only families by default.

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

Each case gets its own ignored artifact directory containing:

- the loose-resource override payload;
- the headless trace;
- the combined runtime log;
- a `result.json` summary.

For runtime stability, the campaign now archives each payload under that case
artifact path but stages the active override into one fixed per-worker
directory before launching headless. That keeps the preserved payloads portable
without letting per-case artifact path strings perturb the semantic run.

The campaign root also writes `summary.jsonl` and `campaign.json`.

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
