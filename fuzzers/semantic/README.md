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

The campaign root also writes `summary.jsonl` and `campaign.json`.

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
