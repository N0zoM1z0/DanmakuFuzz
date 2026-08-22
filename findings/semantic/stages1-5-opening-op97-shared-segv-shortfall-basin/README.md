# Stages 1-5 opening opcode97 shared `SIGSEGV` shortfall basin

Observed on August 22, 2026.

This finding comes from the widened generic exploration lane after adding
shared instruction-field and difficulty-mask mutators.

Across `ecldata1.ecl` through `ecldata5.ecl`, the opening site
`(sub=0, instruction=0)` is the same opcode `97` with:

- `time = 0`
- `skip_for_difficulty = 255`

Three exact mutations at that one site collapse into the same crash trace for
each stage:

- `instruction_time = 4096`
- `instruction_time = 2147483602`
- `difficulty_mask = 96`

The collapse is exact, not just “same finding kind”.

For each stage, all three payloads reproduce:

- the same `SIGSEGV`;
- the same `trace-shortfall` count relative to the stage baseline;
- the same trace SHA-256;
- the same zeroed tail state.

Stage-specific crash shapes:

| Stage | Trace rows | Trace SHA-256 | Primary findings |
| --- | --- | --- | --- |
| 1 | `128` | `f99d5e6907442befae0ab216de3b618520ada9301e83e4b8c8d444e790cd544f` | `SIGSEGV`, `tick_count=128 baseline_tick_count=311` |
| 2 | `330` | `b210dca3f323e9a64fb370bfdbed09a99a4cca3d3c34c0c36864faff86eacca9` | `SIGSEGV`, `tick_count=330 baseline_tick_count=535` |
| 3 | `400` | `7104c804159e5cbd0544a2a06fede5fcfa0e30c5e25171629407a68f4fb596ae` | `SIGSEGV`, `tick_count=400 baseline_tick_count=600` |
| 4 | `440` | `3de055d51bb31e444f3f163cb2085e0b3bec862ac04365c037de8be0d2bb308f` | `SIGSEGV`, `tick_count=440 baseline_tick_count=600` |
| 5 | `440` | `301951ec3664ad353b027a9b2fd39c48feeef7cef7b369df815b19c1a6d66ae7` | `SIGSEGV`, `tick_count=440 baseline_tick_count=600` |

The tail is especially clean: every positive case ends with zero enemies,
items, and bullets still recorded in the trace, while the VM stays loaded and
the timeline time equals the crash tick.

That makes this more interesting than a one-off bad value. Three different
field families at the same opening opcode all collapse into one deterministic
stage-local crash basin.

There is also a useful negative control. Stage 6 still has opcode `97` at the
same path `(sub=0, instruction=0)`, but these three exact edits do not become
interesting there under the same headless setup.

Rebuild and rerun all fifteen positive payloads, plus the Stage 6 negative
controls, with:

```sh
PYTHONPATH=src python3 findings/semantic/stages1-5-opening-op97-shared-segv-shortfall-basin/reproduce.py
```

To rerun only a subset of positive stages:

```sh
PYTHONPATH=src python3 findings/semantic/stages1-5-opening-op97-shared-segv-shortfall-basin/reproduce.py \
  --stage 4 \
  --stage 5
```

Tracked compact payload patches:

- `payload_stage1_instruction_time_4096.json`
- `payload_stage1_instruction_time_2147483602.json`
- `payload_stage1_difficulty_mask_96.json`
- `payload_stage2_instruction_time_4096.json`
- `payload_stage2_instruction_time_2147483602.json`
- `payload_stage2_difficulty_mask_96.json`
- `payload_stage3_instruction_time_4096.json`
- `payload_stage3_instruction_time_2147483602.json`
- `payload_stage3_difficulty_mask_96.json`
- `payload_stage4_instruction_time_4096.json`
- `payload_stage4_instruction_time_2147483602.json`
- `payload_stage4_difficulty_mask_96.json`
- `payload_stage5_instruction_time_4096.json`
- `payload_stage5_instruction_time_2147483602.json`
- `payload_stage5_difficulty_mask_96.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-mutator-broaden-a/summary.json`
- cluster summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-clusters/20260822T222333Z/summary.json`
- local reproduce summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stages1-5-opening-op97-shared-segv-shortfall-basin/summary.json`

Current interpretation:

- headless: clearly interesting and reproducible;
- the fun part is the cross-family convergence: two exact time edits and one
  exact difficulty-mask edit all land in the same opening crash basin;
- Stage 6 staying clean under the same edits suggests this is a real
  stage-clustered structural weakness, not a universal “mutate anything and
  crash” story.
