# Stage 6 `bullet-count1=256` progress wedge

Observed on August 22, 2026.

This finding comes from the dedicated `bullet-count` semantic exploration lane.
On `ecldata6.ecl`, the bullet pattern at `(sub=1, instruction=3)` originally
uses `bullet-count1=6`. Raising that field to the still in-range value `256`
produces a stable late Stage 6 progress wedge:

- the mutated run trips both `stalled-progress` and `stalled-frame`;
- `game_frame` freezes at `1385` from tick `1385` through tick `1800`;
- the first `stage_vm` and `ecl_timeline` drift both appear at tick `1386`,
  where the case has already stopped advancing while the baseline continues;
- at tick `1800`, the case still carries `408` bullets, `33` items, and
  `4` enemies, while the baseline is much further ahead with only `170`
  bullets, `14` items, and `6` enemies.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count1-256-progress-wedge/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count1-256-progress-wedge/reproduce.py \
  --retail
```

The finding directory also keeps a compact exact-payload reconstruction patch:

- `findings/semantic/stage6-bullet-count1-256-progress-wedge/payload_patch.json`

The reproducer canonicalizes the seed ECL once and then applies that patch, so
the exact payload can be rebuilt on another machine without depending on ignored
artifact output.

Current local evidence:

- source semantic case:
  `artifacts/semantic-family-sweep/20260822T-bullet-count-explore-a/ecldata6/0001-bullet-count1-sampled-256-s01-i0003/result.json`
- bullet-count family sweep summary:
  `artifacts/semantic-family-sweep/20260822T-bullet-count-explore-a/summary.json`
- hotspot summary:
  `artifacts/semantic-hotspots/bullet-count-explore-a/summary.json`
- trace basin summary:
  `artifacts/semantic-trace-basins/bullet-count-explore-a/summary.json`

Why this one matters:

- it comes from a reusable core mutator family rather than a Stage 6-only
  bespoke patch;
- it is not a weak scalar drift: the run visibly stops making stage progress
  hundreds of frames earlier than baseline;
- the trigger value `256` is large but still a normal signed 32-bit count,
  which makes this a good candidate for later VM and object-lifecycle audit.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive a Stage 6 Practice confirmation under Wine.
