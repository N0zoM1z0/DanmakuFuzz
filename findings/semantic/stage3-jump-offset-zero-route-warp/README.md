# Stage 3 `jump-offset-zero` route warp

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane after long-trace baseline-aware
differential scoring. A `jump-offset-zero` mutation on `ecldata3.ecl` creates a
stable Stage 3 route warp with a large bullet-density collapse and prolonged
script progression:

- by tick `1197`, the mutated run has `42` bullets while the baseline has `122`;
- by tick `1302`, score reaches only `32520` while the baseline is already at
  `51520`;
- by tick `1361`, the baseline Stage 3 script has already gone inactive with
  `stage_vm.loaded=False`, while the mutated run is still advancing with
  `stage_vm.loaded=True`;
- by tick `1473` in repeated headless smokes, the mutated run can also surface
  an impossible `ecl_timeline.next_time=-27740`.

The core of the finding is still the route warp and progression skew. The
negative `next_time` state is an extra late-phase anomaly that reappeared in
the August 22, 2026 smoke reruns.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage3-jump-offset-zero-route-warp/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 3 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage3-jump-offset-zero-route-warp/reproduce.py \
  --retail
```

Current local evidence:

- source semantic case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-jump-call-long-all/ecldata3/0001-jump-offset-zero-s04-i0019/result.json`
- dedicated rerun result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-rerun-stage3-jump-zero/0001-jump-offset-zero-s04-i0019/result.json`
- family sweep summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-jump-call-long-all/summary.json`
- retail confirmation smoke:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage3-jump-offset-zero-route-warp-retail-smoke/retail/report.json`

Why this one matters:

- it comes from a reusable core mutator family, not a Stage 3-specific bespoke
  patch;
- it changes visible danmaku density early enough to be obviously different in
  play, instead of only producing a late parser/runtime failure;
- it also warps long-horizon stage progression, not just one local resource
  counter.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: the August 22, 2026 smoke reached `game-window-live`, and the progress
  probe observed visible frame changes instead of a static screen.
