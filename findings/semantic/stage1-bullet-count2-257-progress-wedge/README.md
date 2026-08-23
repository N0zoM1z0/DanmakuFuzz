# Stage 1 `bullet-count2=257` progress wedge

Observed on August 22, 2026.

This finding comes from the widened generic semantic exploration lane after
removing the old append-order bias inside site-level selection. On
`ecldata1.ecl`, the bullet pattern at `(sub=1, instruction=5)` originally uses
`bullet-count1=1` and `bullet-count2=1`. Raising only `bullet-count2` to the
still in-range value `257` produces a stable late Stage 1 progress wedge:

- the mutated run trips both `stalled-progress` and `stalled-frame`;
- `game_frame` freezes at `951` from tick `951` through tick `1800`;
- the first `stage_vm` and `ecl_timeline` drift both appear at tick `952`,
  where the case has already stopped advancing while the baseline continues;
- at tick `1800`, the case still carries `150` bullets, while the baseline has
  only `61`, even though both runs have already unloaded the stage VM.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-bullet-count2-257-progress-wedge/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 1 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-bullet-count2-257-progress-wedge/reproduce.py \
  --retail
```

The finding directory also keeps a compact exact-payload reconstruction patch:

- `findings/semantic/stage1-bullet-count2-257-progress-wedge/payload_patch.json`

The reproducer canonicalizes the seed ECL once and then applies that patch, so
the exact payload can be rebuilt on another machine without depending on ignored
artifact output.

Current local evidence:

- source semantic case:
  `artifacts/semantic-family-sweep/20260822T-portable-core-explore-d/ecldata1/0003-bullet-count2-sampled-257-s01-i0005/result.json`
- widened portable core sweep summary:
  `artifacts/semantic-family-sweep/20260822T-portable-core-explore-d/summary.json`
- widened portable core hotspot summary:
  `artifacts/semantic-hotspots/portable-core-explore-d/summary.json`
- widened portable core trace basin summary:
  `artifacts/semantic-trace-basins/portable-core-explore-d/summary.json`

Why this one matters:

- it comes from the reusable generic semantic lane, not a bespoke stage patch;
- it is a different family from the earlier `bullet-count1` findings, so it
  widens the actually useful search surface rather than repeating the same axis;
- it is not just a scalar drift: the run freezes `850` ticks early and leaves a
  clearly different bullet field behind.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive a Stage 1 Practice confirmation under Wine.
