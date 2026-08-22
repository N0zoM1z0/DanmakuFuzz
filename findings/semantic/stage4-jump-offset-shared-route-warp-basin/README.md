# Stage 4 shared `jump-offset` route-warp basin

Observed on August 22, 2026.

This finding upgrades a new Stage 4 exploration-grid cluster into a strict
shared-trace basin. On `ecldata4.ecl`, the `jump-offset` site at
`(sub=1, instruction=14)` originally uses opcode `3` with jump offset `-312`.
Four exact reconstructed offsets already collapse into one identical mid-stage
route warp:

- `jump-offset=-78`
- `jump-offset=-320`
- `jump-offset=624`
- `jump-offset=3784`

Under headless replay, those four payloads reproduce the same trace byte for
byte:

- trace SHA-256:
  `9feff7b8a44928b0b874afeab9a2b1f2cb0fa71e0c2258b5308c29ff1527f23c`
- the normalized route split first appears at tick `551` on the enemy roster;
- by tick `600`, the baseline still has `11` enemies and `450` bullets, while
  the basin trace has only `9` enemies and `48` bullets;
- the same basin also lifts score from `4380` to `8620` by tick `600`.

This is fun for two reasons:

- a tiny local perturbation (`-312 -> -320`) is already enough to enter the
  basin;
- large offsets with completely different magnitudes still collapse into the
  same exact Stage 4 route warp.

Rebuild the four triggering payloads from the local baseline corpus and rerun
the shared-trace check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage4-jump-offset-shared-route-warp-basin/reproduce.py
```

To also drive the closest representative through retail Practice Stage 4 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage4-jump-offset-shared-route-warp-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_jump_offset_neg78.json`
- `payload_jump_offset_neg320.json`
- `payload_jump_offset_624.json`
- `payload_jump_offset_3784.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-core-grid-a/summary.json`
- cluster summary for the grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-clusters/20260822T-core-grid-a/summary.json`
- dedicated trace-basin proof for these four exact values:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/20260822T181419Z/summary.json`
- August 22, 2026 retail smoke for the `jump-offset=-320` representative:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage4-jump-offset-shared-route-warp-basin/retail/report.json`

Why this one matters:

- it comes from the generic exploration lane rather than a hand-picked one-off
  mutation;
- it is a real cross-value basin, not just one lucky sampled offset;
- it warps visible mid-stage route composition, bullet density, and score
  progression without needing a crash oracle.

Current interpretation:

- headless: clearly interesting and reproducible;
- this directory captures the strict shared-trace subgroup of the Stage 4 site;
- retail: on August 22, 2026, the `jump-offset=-320` smoke reached a live game
  window under Wine, changed `57565 / 786432` pixels during the progress probe
  (`0.0731976826985677`), and did not produce a Wine crash signature;
- that retail result is still only a launch/progress smoke, not proof that the
  exact headless route-warp trace also manifests in retail.
