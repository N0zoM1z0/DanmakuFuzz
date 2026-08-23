# Stage 1 cross-value `shoot-interval` delayed-freeze basin

Observed on August 23, 2026.

This finding captures a surprising cross-value collapse on one generic Stage 1
timing site. On `ecldata1.ecl`, opcode `77` at `(sub=0, instruction=7)`
originally uses `shoot-interval=120`. Three exact rebuilt values all land in
the same late scheduler basin:

- `shoot-interval=-1`
- `shoot-interval=0`
- `shoot-interval=2147483602`

By tick `1800`, all three runs end in the same delayed-freeze shape:

- `game_frame=1403`
- `stage_vm.script_time=1403`
- `ecl_timeline.next_time=1600`
- `terminal_reason=tick-limit`

The strangest part is that `shoot-interval=-1` and
`shoot-interval=2147483602` are not merely similar. In the August 23, 2026
1800-tick rerun, they produced the exact same trace SHA-256:

- `78e82f5d2b706a0cc9972a81761a5e5a61692859832983b12509c0e6574a9247`

The `shoot-interval=0` representative lands in the same scheduler basin with a
different exact trace SHA, but the same freeze point and the same
interestingness findings.

This case first surfaced in the shorter August 22, 2026 time-cross scout:
`shoot-interval=2147483602` was initially missed because the 600-tick oracle
did not treat `physical-hit -> tick-limit` as interesting. After adding
`terminal-reason-drift`, the longer exact basin map showed that this huge
positive value simply collapses into the already-bad `0 / -1` delayed-freeze
family.

Rebuild the exact payloads from the local baseline corpus and rerun the
headless confirmation with:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-shoot-interval-cross-value-delayed-freeze-basin/reproduce.py
```

To also drive the weirdest representative through retail Practice Stage 1 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-shoot-interval-cross-value-delayed-freeze-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_shoot_interval_neg1.json`
- `payload_shoot_interval_0.json`
- `payload_shoot_interval_2147483602.json`

Current local evidence:

- short scout result that first exposed the missed case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-time-cross-scout-a/ecldata1/0001-shoot-interval-sampled-2147483602-s00-i0007/result.json`
- exact 1800-tick basin map:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/20260823T-stage1-site-s00-i0007-a/summary.json`
- retail launch/progress smoke for the `shoot-interval=2147483602`
  representative:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage1-shoot-interval-cross-value-delayed-freeze-basin/retail/report.json`
- earlier sibling finding on the same site but a different basin:
  `/home/yann/yann/touhou/DanmakuFuzz/findings/semantic/stage1-shoot-interval-one-bullet-storm/README.md`

Why this one matters:

- a huge positive sentinel-like value collapses onto the same bad behavior as
  `-1`, which is exactly the kind of old-VM edge behavior we want to find;
- the same generic Stage 1 timing site now clearly has multiple semantic
  basins: an early bullet-storm basin (`1 / 8`) and this delayed-freeze basin
  (`0 / -1 / 2147483602`);
- it is a generic `shoot-interval` timing result, not a stage-specific boss
  special case, so it should transfer well to TH07/TH08-style exploration.

Current interpretation:

- headless: clearly interesting and reproducible;
- the fun part is the collapse itself: `2147483602` is not a unique outlier, it
  rejoins the `-1` delayed-freeze trace family exactly;
- retail: on August 23, 2026, the `shoot-interval=2147483602` smoke reached a
  live game window under Wine, did not hit a Wine crash signature, and then
  stayed pixel-static for the 2-second progress probe (`0 / 786432` pixels
  changed), so the retail oracle classified it as `game-window-static`.
