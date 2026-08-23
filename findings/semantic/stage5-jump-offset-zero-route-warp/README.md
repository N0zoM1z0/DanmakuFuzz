# Stage 5 `jump-offset-zero` route warp

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane after long-trace baseline-aware
differential scoring. A `jump-offset-zero` mutation on `ecldata5.ecl` creates a
stable Stage 5 route warp with heavy mid-stage danmaku collapse and persistent
script progression skew:

- by tick `530`, the mutated run has only `80` bullets while the baseline has
  `400`;
- score, item count, power, life, enemy count, and point-item progression all
  diverge;
- by tick `1349`, the baseline Stage 5 script has already gone inactive with
  `stage_vm.loaded=False`, while the mutated run is still advancing with
  `stage_vm.loaded=True`;
- by tick `1702` in the dedicated rerun, the mutated run is still live at
  `ecl_timeline.time=1702`, while the baseline remains frozen at
  `ecl_timeline.time=1333`.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-jump-offset-zero-route-warp/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 5 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-jump-offset-zero-route-warp/reproduce.py \
  --retail
```

Current local evidence:

- source semantic case:
  `artifacts/semantic-family-sweep/20260822T-jump-call-long-all/ecldata5/0001-jump-offset-zero-s00-i0014/result.json`
- family sweep summary:
  `artifacts/semantic-family-sweep/20260822T-jump-call-long-all/summary.json`
- retail confirmation smoke:
  `artifacts/findings/semantic-stage5-jump-offset-zero-route-warp-retail-smoke/retail/report.json`

Why this one matters:

- it comes from a reusable core mutator family and not a Stage 5-specific
  bespoke patch;
- it changes visible bullet density very early, instead of only producing a
  late parser/runtime failure;
- it also warps long-horizon route progression, not just short-lived resource
  counts.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: the August 22, 2026 smoke reached `game-window-live`, and the progress
  probe observed visible frame changes instead of a static screen.
