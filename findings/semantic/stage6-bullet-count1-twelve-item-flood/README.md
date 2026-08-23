# Stage 6 `bullet-count1=12` item flood

Observed on August 22, 2026.

This finding comes from the generic TH06 semantic exploration lane after
broadening the sampler beyond fixed templates. On `ecldata6.ecl`, the bullet
pattern at `(sub=2, instruction=3)` originally uses `bullet-count1=6`.
Doubling that to the still-small in-range value `12` produces a late Stage 6
item flood and progression skew:

- the mutated run crosses the `item-explosion` threshold for `28` consecutive
  frames and peaks at `491` active items, while the Stage 6 baseline peaks at
  only `41`;
- bullet, score, item, power, life, enemy, and point-item state all diverge;
- by tick `1747`, the baseline has already unloaded the stage VM, while the
  mutated run still reports `stage_vm.loaded=True`.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count1-twelve-item-flood/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count1-twelve-item-flood/reproduce.py \
  --retail
```

The finding directory also keeps a compact exact-payload reconstruction patch:

- `findings/semantic/stage6-bullet-count1-twelve-item-flood/payload_patch.json`

The reproducer canonicalizes the seed ECL once and then applies that patch, so
the exact payload can be rebuilt on another machine without depending on ignored
artifact output.

Current local evidence:

- source semantic case:
  `artifacts/semantic-family-sweep/20260822T-portable-core-explore-c/ecldata6/0008-bullet-count1-sampled-12-s02-i0003/result.json`
- portable core sweep summary:
  `artifacts/semantic-family-sweep/20260822T-portable-core-explore-c/summary.json`
- hotspot summary:
  `artifacts/semantic-hotspots/portable-core-explore-c/summary.json`
- trace basin summary:
  `artifacts/semantic-trace-basins/portable-core-explore-c/summary.json`

Why this one matters:

- it comes from a reusable core mutator family rather than a stage-script-only
  bespoke patch;
- the trigger value `12` is small and plausible, not a giant sentinel;
- it produces a visible resource flood instead of only a subtle scalar drift;
- it expands the generic exploration lane with a new Stage 6 resource-economy
  failure mode that is distinct from the earlier `bullet-count2-zero` item
  flood.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive a Stage 6 Practice confirmation under Wine.
