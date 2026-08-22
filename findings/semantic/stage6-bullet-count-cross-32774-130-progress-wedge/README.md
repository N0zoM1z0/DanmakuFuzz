# Stage 6 cross-field `bullet-count=(32774,130)` progress wedge

Observed on August 22, 2026.

This finding comes from the widened generic `bullet-count-cross` semantic
exploration lane. On `ecldata6.ecl`, the Stage 6 pattern at `(sub=1,
instruction=3)` originally uses `bullet-count1=6` and `bullet-count2=2`.
Mutating that single opcode site to the exact cross-field pair
`(32774, 130)` produces a stable late-stage progress wedge:

- the case still looks "alive" for a long time, but `game_frame` freezes at
  `1382` from tick `1382` through tick `1800`;
- the first `stage_vm` and `ecl_timeline` drifts both appear at tick `1383`;
- the semantic lane reports both `stalled-progress` and `stalled-frame`;
- the run reaches a 640-bullet crest at tick `637`, then eventually wedges
  with `405` bullets still present at tick `1800`;
- baseline keeps advancing to `game_frame=1731`, while the wedged case stays
  stuck at `1382`.

Rebuild the exact payload from the local Stage 6 seed and rerun the headless
differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count-cross-32774-130-progress-wedge/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count-cross-32774-130-progress-wedge/reproduce.py \
  --retail
```

The finding directory also keeps a compact exact-payload reconstruction patch:

- `findings/semantic/stage6-bullet-count-cross-32774-130-progress-wedge/payload_patch.json`

The reproducer canonicalizes the seed ECL once and then applies that patch, so
the exact payload can be rebuilt on another machine without depending on
ignored artifact output or the current exploration sampler internals.

Current local evidence:

- short cross-field exploration sweep:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic/cross-count-stage6-seed7-ecldata6/campaign.json`
- long-run confirmation sweep:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic/cross-count-stage6-long-a/campaign.json`
- long-run source case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic/cross-count-stage6-long-a/0001-bullet-count-cross-sampled-32774-130-s01-i0003/result.json`

Why this one matters:

- it comes from a reusable generic cross-field mutator family rather than a
  Stage 6-only bespoke patch;
- it is stronger than a short-run bullet-count drift: the run wedges hundreds
  of frames early and stops making stage progress;
- it shows that paired count fields on one opcode site can produce a much more
  pathological state than either field explored alone.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive a Stage 6 Practice confirmation under Wine.
