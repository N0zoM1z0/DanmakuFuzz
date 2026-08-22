# Stage 6 `jump-offset-large-forward` headless wedge

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane after long-trace baseline-aware
differential scoring. A `jump-offset-large-forward` mutation on `ecldata6.ecl`
produces a stable late Stage 6 headless wedge:

- the baseline reaches the configured tick limit of `1800`;
- the mutated run never reaches that limit and instead times out;
- in dedicated reruns with a `20` second headless timeout, the trace stops
  reproducibly at `tick=1393`, `game_frame=1393`,
  `stage_vm.loaded=True`, and `stage_vm.script_time=1393`;
- at the point of the wedge, the mutated run still reports
  `ecl_timeline.next_time=1544`.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-jump-offset-large-forward-headless-wedge/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-jump-offset-large-forward-headless-wedge/reproduce.py \
  --retail
```

Current local evidence:

- source semantic case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-jump-call-long-all/ecldata6/0005-jump-offset-large-forward-s00-i0013/result.json`
- family sweep summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-jump-call-long-all/summary.json`
- retail confirmation smoke:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage6-jump-offset-large-forward-headless-wedge-retail-smoke/retail/report.json`

Why this one matters:

- it comes from a reusable core mutator family and not a Stage 6-specific
  bespoke patch;
- it is not just a weak score drift: it wedges the headless run before the
  campaign tick limit;
- it reproduces at the same late tick across repeated reruns, which makes it a
  good target for later source-level debugging.

Current interpretation:

- headless: clearly interesting and reproducible;
- retail: the August 22, 2026 smoke reached `game-window-live`, and the progress
  probe observed visible frame changes instead of a static screen;
- note: the current retail probe does not wait long enough to prove that the
  late headless wedge also happens inside retail.
