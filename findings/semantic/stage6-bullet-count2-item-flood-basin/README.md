# Stage 6 `bullet-count2` item-flood basin

Observed on August 22, 2026.

This finding upgrades the older single-value Stage 6 `bullet-count2-zero` item
flood into a cross-value basin. On `ecldata6.ecl`, the bullet pattern at
`(sub=1, instruction=3)` originally uses `bullet-count1=6` and
`bullet-count2=2`. At least two exact reconstructed `bullet-count2` values now
reproduce the same Stage 6 runaway item economy and the same full headless
trace:

- `bullet-count2=0`
- `bullet-count2=2147483596`

Those two payloads are byte-distinct, but their headless traces collapse to one
identical outcome:

- the trace SHA-256 is
  `11a4e3bc29984ec19daf33ac357d1aef17b4c15a7091a30d62b1d3801a8fe7ef`
  for both representatives;
- the mutated run crosses the `item-explosion` threshold for `21` consecutive
  ticks, from tick `1177` through tick `1197`;
- the run peaks at `355` active items, while the shared baseline tail ends with
  only `14`;
- score first diverges at tick `659`;
- by tick `1732`, the baseline has already ended the section with
  `stage_vm.loaded=False`, while the mutant is still advancing with
  `stage_vm.loaded=True`.

Rebuild the two triggering payloads from the local baseline corpus and rerun
the shared-basin check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count2-item-flood-basin/reproduce.py
```

To also drive the smaller representative through retail Practice Stage 6 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count2-item-flood-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count2_zero.json`
- `payload_bullet_count2_2147483596.json`

Current local evidence:

- earlier single-value predecessor:
  `/home/yann/yann/touhou/DanmakuFuzz/findings/semantic/stage6-bullet-count2-zero-item-flood/README.md`
- older long-run source case for `bullet-count2=0`:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-bullet-count-long-all/ecldata6/0002-bullet-count2-zero-s01-i0003/result.json`
- widened `bullet-count2` family sweep containing `2147483596`:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-bullet-count2-explore-a/summary.json`
- widened `bullet-count2` hotspot summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/bullet-count2-explore-a/summary.json`
- widened `bullet-count2` trace basin summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/bullet-count2-explore-a/summary.json`

Why this one matters:

- it proves the Stage 6 item flood is not `bullet-count2=0`-only;
- two very different 32-bit values already collapse into the same runtime
  behavior and the same full trace;
- it preserves a portable generic `bullet-count2` site that can be checked
  again when we port the lane to TH07/TH08.

Current interpretation:

- headless: clearly interesting and reproducible;
- the basin is cross-value at one generic `bullet-count2` site, not a one-off
  zero special case;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive the `bullet-count2=0` representative through Practice
  Stage 6.
