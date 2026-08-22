# Stage 2 cross-value `shoot-interval` tail split

Observed on August 22, 2026.

This finding captures a forked value landscape on one generic Stage 2 timing
site. On `ecldata2.ecl`, opcode `77` at `(sub=0, instruction=11)` originally
uses `shoot-interval=180`. Two exact rebuilt values already steer the same
site into two different long-tail outcomes:

- `shoot-interval=179` is only a one-tick decrement from the retail value, but
  it still wedges the tail down to `game_frame=1212` / `ecl_timeline.time=1212`
  by tick `1800`, while also drifting score, power, life, items, and
  point-items;
- `shoot-interval=45` is much farther away numerically, but it lands in a
  shallower tail skew at `game_frame=1225` / `ecl_timeline.time=1225` and keeps
  the rest of the state closer to baseline.

Both mutations are generic `shoot-interval` edits on the same opcode site, but
their tails diverge:

- `179` ends at score `571570` with `19` bullets still active;
- `45` ends at score `485330` with `30` bullets still active;
- the Stage 2 baseline ends at `game_frame=1226`, `score=483910`, and
  `ecl_timeline.next_time=1230`.

Rebuild the two exact payloads from the local baseline corpus and rerun the
headless differential checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-shoot-interval-cross-value-tail-split/reproduce.py
```

To also drive the stronger `shoot-interval=179` representative through retail
Practice Stage 2 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-shoot-interval-cross-value-tail-split/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_shoot_interval_45.json`
- `payload_shoot_interval_179.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-core-grid-c/summary.json`
- exact 1800-tick confirmation rerun:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exact-rerun/20260822T-stage23-recheck-a/summary.jsonl`
- earlier single-value predecessor on the same site family:
  `/home/yann/yann/touhou/DanmakuFuzz/findings/semantic/stage2-shoot-interval-one-bullet-flood/README.md`

Why this one matters:

- one representative is only `180 -> 179`, so this is not a “huge sentinel
  constant only” quirk;
- the same reusable Stage 2 timing site already branches into two different
  long-tail scheduler states instead of one monotonic bullet-flood story;
- it is a portable generic family/site result that should transfer cleanly to
  TH07/TH08 timing exploration.

Current interpretation:

- headless: clearly interesting and reproducible;
- the fun part is the split itself: one near-baseline value creates the deeper
  `1212` tail wedge, while a farther-away value creates a milder `1225` skew;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive the `shoot-interval=179` representative through Practice
  Stage 2.
