# Stage 2 `shoot-interval-one` bullet flood

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane after switching long-trace stall
handling to a baseline-aware differential check. A `shoot-interval-one` mutation
on `ecldata2.ecl` creates a stable mid-stage bullet flood and broad state drift:

- by tick `346`, the mutated run has `300` bullets while the baseline has `0`;
- by tick `514`, score reaches `25190` while the baseline is at `15190`;
- power, item count, life count, enemy count, and point-item progression all
  diverge;
- by tick `1230`, the mutated stage script is still at `script_time=1214` while
  the baseline is already at `1226`.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-shoot-interval-one-bullet-flood/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 2 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-shoot-interval-one-bullet-flood/reproduce.py \
  --retail
```

Current local evidence:

- source semantic case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-shoot-interval-long-all/ecldata2/0002-shoot-interval-one-s00-i0011/result.json`
- family sweep summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-shoot-interval-long-all/summary.json`
- retail confirmation smoke:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage2-shoot-interval-one-bullet-flood-retail-smoke/retail/report.json`

Why this one matters:

- it is generic and comes from the same reusable mutator family as the Stage 1
  bullet-storm case;
- it is stable across reruns, unlike weaker late-stage anomalies;
- it perturbs both visible danmaku density and long-horizon stage progression.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: the August 22, 2026 smoke reached `game-window-live`, and the progress
  probe observed visible frame changes instead of a static screen.
