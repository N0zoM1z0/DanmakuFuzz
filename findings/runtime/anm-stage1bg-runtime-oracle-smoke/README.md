# Stage 1 background ANM runtime-oracle smoke

Observed on August 23, 2026.

This finding is not about one single malformed ANM. It is the first compact
proof that the new ANM runtime oracle is actually seeing downstream runtime
weirdness, not just parser drift.

We take the retail `stg1bg.anm` seed from `紅魔郷ST.DAT`, generate several
source-less accepted mutants, run them through Stage 1 headless gameplay, and
score the resulting traces against one baseline run.

Current stable runtime hits:

- `name-offset-zero` → `anm-texture-load-failure`, then early terminal drift;
- `width-neg1` / `height-neg1` → `anm-texture-size-mismatch` plus texture-load
  failure;
- `first-sprite-offset-zero` → `anm-set-active-sprite-failure`,
  `anm-suspicious-sprite`, and `anm-load-drift`;
- `first-script-id-ffff` → `anm-script-drift`;
- `first-script-offset-zero` → `anm-script-drift` plus `anm-non-finite`;
- `first-instr-argsize-zero` → `anm-script-drift`.

This matters because it is exactly the portability shape we wanted:

- the mutations are archive-entry-local and source-less;
- the runtime oracle is not TH06-ECL-specific;
- the same lane structure is usable later for titles where we only know the
  container/parser shape but not the VM source.

Reproduce it with:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage1bg-runtime-oracle-smoke/reproduce.py
```

Payload selection is recorded in:

- [payload_recipe.json](findings/runtime/anm-stage1bg-runtime-oracle-smoke/payload_recipe.json)

Current local evidence:

- pilot artifact summary:
  `artifacts/tmp-anm-runtime-pilot-stg1bg/summary.json`
- standalone reproduction summary:
  `artifacts/findings/runtime-anm-stage1bg-runtime-oracle-smoke/summary.json`
