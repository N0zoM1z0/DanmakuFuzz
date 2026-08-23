# Stage 1 generic arg32-cross item non-finite

Observed on August 23, 2026.

This finding comes from the new source-less coordinated-mutation lane. It does
not rely on a TH06-specific opcode name. Instead, it mutates the first two
32-bit argument slots of one Stage 1 instruction at `(sub=0, instruction=3)`:

- left slot: `-3692`
- right slot: `64`

That is enough to push the runtime into an item-state anomaly rather than just
ordinary gameplay drift.

On TH06 Practice Stage 1, seed `7`, Lunatic, Reimu A:

- the headless oracle reports `non-finite` via `$.entity_metrics.items_non_finite=1`;
- the same run also shows score and enemy-count drift against baseline;
- the first observed non-finite item state is at the terminal trace row
  (`tick=257`, `terminal_reason=physical-hit`).

Why this one matters:

- it exercises the new portable `generic-arg32-cross` family instead of a
  hand-labeled TH06 field;
- it is a real semantic anomaly (`items_non_finite`) rather than only a crash;
- it validates that cross-slot mutation can surface behaviors that single-slot
  scalar mutation may miss.

Reproduce with:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-generic-arg32-cross-item-nonfinite/reproduce.py
```

Original trigger command:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.ecl_campaign \
  --seed-ecl reference/corpus/ecl/original/ecldata1.ecl \
  --profile default \
  --mutation-mode exploration \
  --random-seed 7 \
  --samples-per-site 2 \
  --limit 20 \
  --selection-mode family-site \
  --name-filter generic-opcode- \
  --name-filter generic-arg16- \
  --name-filter generic-arg32-cross- \
  --name-filter timeline-time- \
  --name-filter timeline-arg0- \
  --name-filter adjacent-timeline-time-cross-
```

Tracked payload patch:

- `payload_generic_arg32_cross_neg3692_64.json`

Current local evidence:

- campaign summary:
  `artifacts/semantic/campaign-stage1-seed7-ecldata1/summary.jsonl`
- per-case result:
  `artifacts/semantic/campaign-stage1-seed7-ecldata1/0008-generic-arg32-cross-o0-o1-sampled-neg3692-64-s00-i0003/result.json`
