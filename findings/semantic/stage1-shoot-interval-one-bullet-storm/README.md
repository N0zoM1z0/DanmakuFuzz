# Stage 1 `shoot-interval-one` bullet storm

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane after fixing baseline stall
false-positives in long headless runs. A `shoot-interval-one` mutation on
`ecldata1.ecl` creates an early bullet storm and persistent progression skew:

- by tick `300`, the mutated run reaches `605` bullets while the baseline is at
  `6`;
- score jumps to `11450` while the baseline is at `1950`;
- power reaches `9` by tick `513` while the baseline is at `1`;
- baseline Stage 1 has already fallen into its normal post-stage freeze by tick
  `1044`, but the mutated run is still advancing with `stage_vm.loaded=True`.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-shoot-interval-one-bullet-storm/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 1 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-shoot-interval-one-bullet-storm/reproduce.py \
  --retail
```

Current local evidence:

- source semantic case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-interesting-core-18b/ecldata1/0008-shoot-interval-one-s00-i0007/result.json`
- family sweep summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-interesting-core-18b/summary.json`
- retail confirmation smoke:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage1-shoot-interval-one-bullet-storm-retail-smoke/retail/report.json`

Why this one matters:

- it is generic and comes from the core mutator families, not a stage-specific
  boss mutator;
- it creates a visible danmaku blow-up early enough to be fun, not just a late
  parser/process failure;
- it also perturbs score, items, life, power, enemy population, stage script,
  and ECL timeline state in one run.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: the August 22, 2026 smoke reached `game-window-live`, and the progress
  probe observed visible frame changes instead of a static screen.
