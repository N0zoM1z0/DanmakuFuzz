# Stage 6 cross-value `shoot-interval` volley split

Observed on August 22, 2026.

This finding captures a generic timing site that splits into two stable bullet
layouts instead of one monotonic “more weird value, more weird output” story.
On `ecldata6.ecl`, opcode `77` at `(sub=1, instruction=8)` originally uses
`shoot-interval=30`.

Four exact rebuilt values were rechecked from the generic `core` exploration
lane:

- `shoot-interval=-60`
- `shoot-interval=46`
- `shoot-interval=32798`
- `shoot-interval=65566`

Three of them collapse into one exact 600-tick trace:

- `-60`
- `32798`
- `65566`

Those three values reproduce the same trace byte for byte:

- trace SHA-256:
  `31b6ada04316b5a95ff41b5c53c3bfbed1674ec71d4e939e8863743b873d346e`
- first raw bullet-count split at tick `464` (`baseline=33`, `case=21`);
- oracle hit at tick `479` (`baseline=39`, `case=6`);
- by tick `600`, baseline still has `187` bullets while the shared basin has
  `151`.

The fourth value, `shoot-interval=46`, does not join that basin. It lands on a
nearby shoulder trace instead:

- shoulder trace SHA-256:
  `66bc46e9d6556decbd0aacfc58ea0cc87c58933593cd078f99229d6a0d4df4c3`
- first raw bullet-count split at tick `442` (`baseline=0`, `case=12`);
- oracle hit at tick `460` (`baseline=21`, `case=0`);
- by tick `600`, it still keeps `183` bullets, much closer to the baseline
  tail than the shared basin’s `151`.

So the same Stage 6 timing site already has a clear split:

- one cross-value basin that thins the later volley down to `151` bullets;
- one nearby shoulder that perturbs the volley earlier but keeps the tail much
  closer to baseline.

An extra August 22, 2026 long rerun out to `1800` ticks on the two closest
representatives (`-60` and `46`) shows that the split persists beyond the
first local volley:

- `-60` picks up a negative score drift at tick `659`
  (`baseline=24940`, `case=24440`) and ends at a `physical-hit` on tick `709`;
- `46` instead picks up a positive score drift at tick `639`
  (`baseline=20950`, `case=21450`) and survives until tick `749`.

Rebuild the four exact payloads from the local baseline corpus and rerun the
headless differential checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-shoot-interval-cross-value-volley-split/reproduce.py
```

To also drive the shared-basin representative `shoot-interval=-60` through
retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-shoot-interval-cross-value-volley-split/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_shoot_interval_neg60.json`
- `payload_shoot_interval_46.json`
- `payload_shoot_interval_32798.json`
- `payload_shoot_interval_65566.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-core-grid-d/summary.json`
- hotspot summary for the grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/20260822T-core-grid-d/summary.json`
- 600-tick exact rerun for the four representatives:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exact-rerun/20260822T-stage6-shoot-interval-grid-d-a/report.json`
- explicit trace grouping against the shared Stage 6 baseline:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/20260822T-stage6-shoot-interval-grid-d-a/summary.json`
- 1800-tick follow-up on the `-60` / `46` pair:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exact-rerun/20260822T-stage6-shoot-interval-grid-d-1800-a/report.json`
- August 22, 2026 retail smoke for the `shoot-interval=-60` representative:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage6-shoot-interval-cross-value-volley-split/retail/report.json`

Why this one matters:

- it is a generic `shoot-interval` timing result, not a Stage 6-specific
  hand patch;
- the shared basin is genuinely cross-value: one negative value and two large
  wrapped values land on the same exact trace;
- the nearby `46` shoulder proves the site is not just “all strange values do
  the same thing”;
- this is the kind of reusable scheduler behavior we want to carry forward to
  TH07/TH08.

Current interpretation:

- headless: clearly interesting and reproducible;
- the fun part is the split itself: three values collapse into one later-volley
  thinning basin, while `46` hits a different shoulder;
- the longer follow-up suggests the shoulder and the basin also diverge on
  later score flow, not just on one local bullet snapshot;
- retail: on August 22, 2026, the `shoot-interval=-60` smoke reached a live
  game window under Wine, changed `149378 / 786432` pixels during the progress
  probe (`0.1899439493815104`), and did not produce a Wine crash signature;
- that retail result is still only a launch/progress smoke, not proof that the
  exact shared-basin headless volley split also manifests in retail.
