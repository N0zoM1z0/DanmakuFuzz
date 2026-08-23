# Stage 6 `bullet-count2-zero` item flood

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane after moving long-trace stall
handling to a baseline-aware differential check. A `bullet-count2-zero` mutation
on `ecldata6.ecl` turns one Stage 6 bullet pattern into a late item flood with
persistent progression skew:

- the mutated run crosses the `item-explosion` threshold for 21 consecutive
  frames and peaks at `355` active items, while the baseline Stage 6 peak is
  only `41`;
- bullet, score, power, life, enemy, and point-item state all diverge;
- by tick `1747`, the baseline has already unloaded the stage VM, while the
  mutated run is still advancing with `stage_vm.loaded=True`.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count2-zero-item-flood/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count2-zero-item-flood/reproduce.py \
  --retail
```

Current local evidence:

- source semantic case:
  `artifacts/semantic-family-sweep/20260822T-bullet-count-long-all/ecldata6/0002-bullet-count2-zero-s01-i0003/result.json`
- family sweep summary:
  `artifacts/semantic-family-sweep/20260822T-bullet-count-long-all/summary.json`
- retail confirmation smoke:
  `artifacts/findings/semantic-stage6-bullet-count2-zero-item-flood-retail-smoke/retail/report.json`

Why this one matters:

- it comes from a reusable core mutator family, not a stage-script-specific
  bespoke patch;
- it produces a visible resource flood instead of only a parser/VM crash;
- it perturbs both item economy and late-stage script progression in one run.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: the August 22, 2026 smoke reached `game-window-live`, and the progress
  probe observed visible frame changes instead of a static screen.
