# Stage 3 cross-value `shoot-interval` tail extension

Observed on August 22, 2026.

This finding captures a prolonged late-stage scheduler tail on one generic
Stage 3 timing site. On `ecldata3.ecl`, opcode `77` at `(sub=0,
instruction=7)` originally uses `shoot-interval=200`. Two exact rebuilt values
already push the same site into the same extended terminal shape:

- `shoot-interval=192` is only `8` ticks below the retail value, but it still
  keeps Stage 3 alive until `game_frame=1680` / `ecl_timeline.time=1680`;
- `shoot-interval=2248` is far away numerically, but it lands in the same tail
  shape with the same `ecl_timeline.next_time=1730`.

The two traces are not byte-identical, but they share the same overall Stage 3
extension pattern:

- the baseline unloads at `game_frame=1345`, while both mutations continue for
  another `335` frames;
- both mutations first trip `stage-script-drift` and `ecl-timeline-drift` at
  tick `1361`;
- both end at `game_frame=1680` with the stage VM already unloaded and the
  scheduler parked on `next_time=1730`.

Rebuild the two exact payloads from the local baseline corpus and rerun the
headless differential checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage3-shoot-interval-cross-value-tail-extension/reproduce.py
```

To also drive the smaller `shoot-interval=192` representative through retail
Practice Stage 3 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage3-shoot-interval-cross-value-tail-extension/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_shoot_interval_192.json`
- `payload_shoot_interval_2248.json`

Current local evidence:

- source exploration grid:
  `artifacts/semantic-exploration-grid/20260822T-core-grid-c/summary.json`
- exact 1800-tick confirmation rerun:
  `artifacts/semantic-exact-rerun/20260822T-stage23-recheck-a/summary.jsonl`
- retail launch/progress smoke for the `shoot-interval=192` representative:
  `artifacts/findings/semantic-stage3-shoot-interval-cross-value-tail-extension-retail-a/retail/report.json`
- related Stage 3 structural findings:
  `findings/semantic/stage3-call-sub-zero-in-range-next-time-negative/README.md`
  and
  `findings/semantic/stage3-jump-offset-zero-route-warp/README.md`

Why this one matters:

- the smaller representative is near-baseline (`200 -> 192`), so the tail
  extension is not limited to absurd timer values;
- the same generic timing site already has a cross-value “shared tail shape,”
  even though the detailed score and late enemy state differ;
- it gives the portable lane a Stage 3 timing failure mode that is distinct
  from the negative-`next_time` sink.

Current interpretation:

- headless: clearly interesting and reproducible;
- the shared part is the late tail extension to `1680 / 1730`, not one
  identical full trace;
- retail: on August 22, 2026, the `shoot-interval=192` smoke reached a live
  game window under Wine, changed `139599 / 786432` pixels during the progress
  probe (`0.17750930786132812`), and did not produce a Wine crash signature;
- that retail result is still only a launch/progress smoke, not proof that the
  exact late `1680 / 1730` headless tail also manifests in retail.
