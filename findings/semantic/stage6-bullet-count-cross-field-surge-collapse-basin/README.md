# Stage 6 cross-field `bullet-count` surge-collapse basin

Observed on August 22, 2026.

This finding upgrades a new Stage 6 core-grid duplicate-trace group into a
strict shared-trace basin. On `ecldata6.ecl`, the bullet pattern at
`(sub=2, instruction=3)` originally uses opcode `75` with
`bullet-count1=6` and `bullet-count2=2`. Two different field mutations already
collapse into one identical headless trace:

- `bullet-count1=4102`
- `bullet-count2=258`

That shared trace is fun because the stage script, score, items, lives, bombs,
power, and enemy count all stay aligned with baseline while the bullet pool
goes visibly wrong:

- trace SHA-256:
  `40ba3f92a18b45aa258b9d62c9e25ed798aff2debe0b32d27e0db9c4bcf93d54`
- at tick `457`, the baseline has only `12` bullets while the basin trace jumps
  to `640`;
- at tick `472`, the baseline still has `30` bullets while the basin trace has
  `0`, which is the sustained differential oracle that trips
  `bullet-count-drift`;
- by tick `600`, score is still identical at `16270`, but the basin trace ends
  with `628` bullets while the baseline has `187`.

Why this one matters:

- it is cross-field at one generic opcode/site, not a single magic-number on
  one field;
- it preserves the same score and stage progression while the bullet pool
  oscillates wildly, which points to a hidden runtime pathology rather than a
  trivial route split;
- it is portable: this is exactly the sort of weird per-pattern count behavior
  we want to carry forward to TH07/TH08.

Rebuild the two triggering payloads from the local baseline corpus and rerun
the shared-trace check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count-cross-field-surge-collapse-basin/reproduce.py
```

To also drive the smaller representative through retail Practice Stage 6 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count-cross-field-surge-collapse-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count1_4102.json`
- `payload_bullet_count2_258.json`

Current local evidence:

- source exploration grid:
  `artifacts/semantic-exploration-grid/20260822T-core-grid-b/summary.json`
- cluster summary for the grid:
  `artifacts/semantic-clusters/20260822T-core-grid-b/summary.json`
- August 22, 2026 retail smoke for the `bullet-count2=258` representative:
  `artifacts/findings/semantic-stage6-bullet-count-cross-field-surge-collapse-basin/retail/report.json`

Current interpretation:

- headless: clearly interesting and reproducible;
- this directory captures a strict shared-trace subgroup where high-level
  counters stay aligned but the bullet pool does not;
- retail: on August 22, 2026, the `bullet-count2=258` smoke reached a live
  game window under Wine, changed `149378 / 786432` pixels during the progress
  probe (`0.1899439493815104`), and did not produce a Wine crash signature;
- that retail result is still a launch/progress smoke, not proof that the exact
  headless surge-collapse trace also manifests in retail.
