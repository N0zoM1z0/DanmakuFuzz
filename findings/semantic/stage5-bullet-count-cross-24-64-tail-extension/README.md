# Stage 5 cross-field `bullet-count=(24,64)` tail extension

Observed on August 22, 2026.

This finding comes from the widened generic `bullet-count-cross` semantic
exploration lane. On `ecldata5.ecl`, the Stage 5 pattern at `(sub=0,
instruction=11)` originally uses `bullet-count1=40` and `bullet-count2=1`.
Mutating that single opcode site to the exact cross-field pair `(24, 64)`
produces a late-stage scheduler tail extension instead of a hard wedge:

- the first `stage_vm` and `ecl_timeline` drifts both appear at tick `1334`;
- at that point, baseline has already dropped `stage_vm.loaded=False` at
  `game_frame=1333`, while the mutated case keeps advancing with
  `stage_vm.loaded=True`;
- baseline ends its Stage 5 scheduler tail at `game_frame=1333`, but the
  mutated case keeps running until `game_frame=1441`;
- both runs still point at `ecl_timeline.next_time=1442`, so the mutation
  stretches the tail toward the same next scheduler boundary instead of
  redirecting control elsewhere;
- the case also reaches a 640-bullet crest at tick `510` before collapsing
  back down to a thinner 25-bullet tail by tick `1800`.

This is a different failure shape from the existing Stage 5 jump findings:
instead of warping the route or freezing it outright, this one keeps the Stage
5 script alive for 108 extra frames past the retail baseline tail.

Rebuild the exact payload from the local Stage 5 seed and rerun the headless
differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-bullet-count-cross-24-64-tail-extension/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 5 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-bullet-count-cross-24-64-tail-extension/reproduce.py \
  --retail
```

The finding directory also keeps a compact exact-payload reconstruction patch:

- `findings/semantic/stage5-bullet-count-cross-24-64-tail-extension/payload_patch.json`

The reproducer canonicalizes the seed ECL once and then applies that patch, so
the exact payload can be rebuilt on another machine without depending on
ignored artifact output or the current exploration sampler internals.

Current local evidence:

- short cross-field scout sweep:
  `artifacts/semantic-family-sweep/20260822T-bullet-count-cross-scout-a/summary.json`
- long exact-rerun sweep:
  `artifacts/semantic-exact-rerun/20260822T-bullet-count-cross-long-b/report.json`
- long-run source case:
  `artifacts/semantic-exact-rerun/20260822T-bullet-count-cross-long-b/0007-bullet-count-cross-sampled-24-64-s00-i0011/result.json`

Why this one matters:

- it comes from a reusable generic cross-field mutator family rather than a
  Stage 5-only bespoke patch;
- it surfaces a different scheduler pathology from the existing Stage 5
  jump-offset cases;
- it shows that paired bullet-count fields can extend a stage tail beyond the
  retail baseline instead of only causing stalls or explosions.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive a Stage 5 Practice confirmation under Wine.
