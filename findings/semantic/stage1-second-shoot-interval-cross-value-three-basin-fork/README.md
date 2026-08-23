# Stage 1 second-site cross-value `shoot-interval` three-basin fork

Observed on August 23, 2026.

This finding captures a second generic Stage 1 `shoot-interval` site with a
much richer value landscape than the earlier delayed-freeze basin on
`(sub=0, instruction=7)`. On `ecldata1.ecl`, opcode `77` at
`(sub=1, instruction=7)` originally uses `shoot-interval=120`. Exact rebuilt
values split into three distinct basins:

- `-119 / -1 / 0` collapse into a late script-revival basin.
- `1 / 2 / 256` stay on the baseline tail time but fork into an early
  score-and-bullet lobe.
- `1144` lands in a separate intermediate tail around `game_frame=1201`.

Representative tails at tick `1800`:

- `shoot-interval=-1`
  - `game_frame=1391`
  - `score=268250`
  - `enemy_count=14`
  - `bullet_count=78`
  - `ecl_timeline.next_time=1400`
- `shoot-interval=1`
  - `game_frame=1028`
  - `score=238110`
  - `enemy_count=5`
  - `bullet_count=60`
  - `ecl_timeline.next_time=1040`
- `shoot-interval=1144`
  - `game_frame=1201`
  - `score=265690`
  - `enemy_count=7`
  - `bullet_count=143`
  - `ecl_timeline.next_time=1220`

The fun part is that this is not just a “more bullets / fewer bullets” site.
The `-1` and `1144` representatives both re-activate stage-script progress
after the retail baseline has already gone idle:

- baseline at tick `1044`: `stage_vm.loaded=False`, `ecl_timeline.time=1028`
- `-1` / `1144` at tick `1044`: `stage_vm.loaded=True`,
  `ecl_timeline.time=1044`

Rebuild the exact payloads from the local baseline corpus and rerun the
headless confirmation with:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-second-shoot-interval-cross-value-three-basin-fork/reproduce.py
```

To also drive the `shoot-interval=-1` representative through retail Practice
Stage 1 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-second-shoot-interval-cross-value-three-basin-fork/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_shoot_interval_neg1.json`
- `payload_shoot_interval_1.json`
- `payload_shoot_interval_1144.json`

Current local evidence:

- exact basin harvest:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-basin-harvest/20260823T-stage1-second-shoot-interval-site-a/stage1-ecldata1-shoot-interval-s01-i0007/summary.json`
- harvest driver summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-basin-harvest/20260823T-stage1-second-shoot-interval-site-a/summary.json`
- headless reproduce summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage1-second-shoot-interval-cross-value-three-basin-fork/summary.json`
- retail smoke for the `shoot-interval=-1` representative:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage1-second-shoot-interval-cross-value-three-basin-fork/retail/report.json`

Why this one matters:

- it is a second generic Stage 1 `shoot-interval` site, so the Stage 1 timing
  landscape is broader than a single hotspot;
- the same site now clearly has at least three value basins, not one weird
  outlier;
- both a negative edge value (`-1`) and a moderate positive value (`1144`)
  trigger stage-script revival after the baseline tail has already gone inert;
- this is generic timing behavior, not a boss-only corner case, so it should
  transfer well to TH07/TH08-style exploration.

Current interpretation:

- headless: clearly interesting and reproducible;
- the most structural behavior is the `-1 / 1144` family, which revives stage
  script processing after the baseline tail is already idle;
- retail: on August 23, 2026, the `shoot-interval=-1` smoke reached a live
  game window under Wine, did not hit a Wine crash signature, and then stayed
  pixel-static for the 2-second progress probe (`0 / 786432` pixels changed),
  so the retail oracle classified it as `game-window-static`.
