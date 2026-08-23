# Stage 1 `bullet-count2` progress-wedge basin

Observed on August 22, 2026.

This finding upgrades the narrower Stage 1 `bullet-count2=257` wedge into a
cross-value basin. On `ecldata1.ecl`, the bullet pattern at
`(sub=1, instruction=5)` originally uses `bullet-count1=1` and
`bullet-count2=1`. At least two exact reconstructed values now reproduce the
same Stage 1 progress wedge:

- `bullet-count2=116`
- `bullet-count2=257`

Even though those two payloads leave different bullet totals and score at the
end of the run, they collapse into the same stage-progress state:

- `game_frame` freezes at `951` from tick `951` through tick `1800`;
- the first `stage_vm` and `ecl_timeline` drift both appear at tick `952`;
- both runs end with `stage_vm.loaded=False`,
  `stage_vm.script_time=951`, and `ecl_timeline.next_time=960`.

Rebuild the two triggering payloads from the local baseline corpus and rerun
the shared-wedge check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-bullet-count2-progress-wedge-basin/reproduce.py
```

To also drive the smaller representative through retail Practice Stage 1 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-bullet-count2-progress-wedge-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count2_116.json`
- `payload_bullet_count2_257.json`

Current local evidence:

- widened `bullet-count2` family sweep:
  `artifacts/semantic-family-sweep/20260822T-bullet-count2-explore-a/summary.json`
- widened `bullet-count2` hotspot summary:
  `artifacts/semantic-hotspots/bullet-count2-explore-a/summary.json`
- widened `bullet-count2` trace basin summary:
  `artifacts/semantic-trace-basins/bullet-count2-explore-a/summary.json`
- narrower single-value predecessor:
  `findings/semantic/stage1-bullet-count2-257-progress-wedge/README.md`

Why this one matters:

- it shows that the Stage 1 wedge is not a single magic-number accident;
- the smaller value `116` already reaches the same frozen scheduler state;
- it upgrades a one-off Stage 1 curiosity into a reusable site-level basin that
  is worth carrying forward when we port the lane to later games.

Current interpretation:

- headless: clearly interesting and reproducible;
- the wedge basin is cross-value at one generic `bullet-count2` site, not
  `257`-only;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive the smaller `116` representative through Practice Stage 1.
