# Stage 5 shared `jump-offset` route-warp basin

Observed on August 22, 2026.

This finding upgrades a new Stage 5 core-grid cluster into a strict
shared-trace basin. On `ecldata5.ecl`, the `jump-offset` site at
`(sub=0, instruction=14)` originally uses opcode `3` with jump offset `-224`.
Three exact reconstructed offsets already collapse into one identical mid-stage
route warp:

- `jump-offset=-222`
- `jump-offset=-1248`
- `jump-offset=1792`

Under headless replay, those three payloads reproduce the same trace byte for
byte:

- trace SHA-256:
  `1914a4b2e1f4967d97613d72b5330949f8e96d24b7177dd496a0f3d6783b09d9`
- the normalized route split first appears at tick `520` on the enemy roster;
- by tick `530`, the baseline still has `400` bullets, while the basin trace
  has only `80`;
- by tick `600`, the baseline still carries `328` bullets, while the basin
  trace has only `56`, and score drops from `5150` to `5020`.

Why this one matters:

- a tiny local perturbation (`-224 -> -222`) is already enough to enter the
  basin;
- very different signed offsets still collapse into the same exact Stage 5
  route warp;
- it comes from the portable `core` exploration lane rather than a bespoke
  Stage 5-only patch.

Rebuild the three triggering payloads from the local baseline corpus and rerun
the shared-trace check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-jump-offset-shared-route-warp-basin/reproduce.py
```

To also drive the closest representative through retail Practice Stage 5 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-jump-offset-shared-route-warp-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_jump_offset_neg222.json`
- `payload_jump_offset_neg1248.json`
- `payload_jump_offset_1792.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-core-grid-b/summary.json`
- cluster summary for the grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-clusters/20260822T-core-grid-b/summary.json`
- dedicated trace-basin proof for these three exact values:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/20260822T-stage5-jump-offset-shared-route-warp-basin/summary.json`
- August 22, 2026 retail smoke for the `jump-offset=-222` representative:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage5-jump-offset-shared-route-warp-basin/retail/report.json`

Current interpretation:

- headless: clearly interesting and reproducible;
- this directory captures the strict shared-trace subgroup of the Stage 5 site;
- retail: on August 22, 2026, the `jump-offset=-222` smoke reached a live game
  window under Wine, changed `126639 / 786432` pixels during the progress probe
  (`0.16102981567382812`), and did not produce a Wine crash signature;
- that retail result is still a launch/progress smoke, not proof that the exact
  headless route-warp trace also manifests in retail.
