# Stage 6 ANM metamorphic runtime equivalence

Observed on August 23, 2026.

This runtime observation checks metamorphic invariants for the Stage 6 ANM
resources `stg6bg.anm`, `stg6enm.anm`, and `stg6enm2.anm`.

The campaign mutates:

- header `unk1`;
- header `unk2`;
- script table row order, including first-row swap and full reverse order.

All 12 generated cases completed under `th06-headless` and produced the same
1200-line trace hash as the clean baseline:

- baseline trace SHA-256:
  `76807eba84ec4d20745dfe91fd5dd02d44f33ee4a253612f2d44df44dc440c19`;
- `relation_counts`: `{"holds": 12}`;
- `classification_counts`: `{"equivalent": 12}`;
- `violation_counts`: `{}`.

The script-table cases are the most useful part: the parser sees structural
changes to script entries/order, but the runtime trace remains byte-for-byte
equivalent for this Stage 6 baseline. That gives the ANM lane a stronger
negative control when deciding whether a future mutation is material runtime
drift or just loader-tolerated metadata churn.

This is not a retail-confirmed bug and is intentionally indexed as
`format-observation`.

## Reproduce

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage6-metamorphic-runtime-equivalence/reproduce.py
```

Current local evidence:

- `artifacts/checks/anm-metamorphic-runtime-stage6-20260823/campaign.json`
- `artifacts/checks/anm-metamorphic-runtime-stage6-20260823/summary.jsonl`
