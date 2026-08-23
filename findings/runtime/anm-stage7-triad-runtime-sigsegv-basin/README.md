# Stage 7 ANM triad SIGSEGV basin

Observed on August 23, 2026.

This finding comes from the coordinated resource lane. Instead of mutating one
ANM entry in isolation, it applies the same accepted source-less ANM mutant to
the Stage 7 runtime triad at once:

- `stg7bg.anm`
- `stg7enm.anm`
- `stg7enm2.anm`

Under fixed Stage 7 Practice playback, four coordinated triad mutants all land
in the same coarse sink family:

- headless exits with `SIGSEGV`;
- a partial trace is still emitted;
- the trace stops at `440` lines instead of the baseline `582`;
- `trace-shortfall` and `terminal-reason-drift` always appear.

Stable basin members:

- `first-sprite-offset-zero`
- `first-script-id-ffff`
- `first-script-offset-zero`
- `first-instr-opcode-255`

The basin is not one exact-trace equivalence class. It is a coordinated sink
family with richer preludes:

- `first-sprite-offset-zero` is the loudest variant:
  it also yields `anm-set-active-sprite-failure`, `anm-suspicious-sprite`, and
  `anm-load-drift`;
- `first-script-id-ffff` and `first-script-offset-zero` both add
  `anm-script-drift`;
- `first-instr-opcode-255` is the cleanest `SIGSEGV + 440-line shortfall`
  sibling.

Why this matters:

- the trigger is generic stage-resource coordination, not a TH06-only boss
  script trick;
- the same accepted ANM mutant gets stronger when the whole stage bundle moves
  together;
- the `anm-ecl` sub-lane already reaches the same sink shape with mixed
  `ANM + ECL` payloads, so this is a real multi-resource basin, not just one
  isolated ANM parser accident.

Reproduce with:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage7-triad-runtime-sigsegv-basin/reproduce.py
```

Trigger command that originally surfaced it:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.resource_coordination_campaign \
  --stage 7 \
  --mode all \
  --limit 6
```

Payload selection is recorded in:

- [payload_recipe.json](findings/runtime/anm-stage7-triad-runtime-sigsegv-basin/payload_recipe.json)

Current local evidence:

- campaign summary:
  `artifacts/tmp-resource-coordination-smoke/campaign.json`
- triad case summary:
  `artifacts/tmp-resource-coordination-smoke/0001-anm-triad-first-sprite-offset-zero/result.json`
- single-entry Stage 7 sibling:
  `findings/runtime/anm-stage7enm-runtime-sigsegv-basin/README.md`
