# Stages 1-5 opening `instruction-time=3` route skew

Observed on August 22, 2026.

This finding comes from the widened generic `instruction-time` exploration
lane.

Across `ecldata1.ecl` through `ecldata5.ecl`, the same opening site
`(sub=0, instruction=1)` is opcode `103` with `time=0`, `offset_to_next=24`,
and `skip_for_difficulty=255`.

Changing only that one-byte low-order time field from `0` to `3` produces a
stable cross-stage semantic split:

- Stage 1 stops dying at tick `311` and now survives to tick `600`, but with
  score suppressed to `1280` and enemy routing skewed.
- Stage 2 still dies by physical hit, but earlier, with score, bullet count,
  and enemy count all shifted.
- Stage 3 reaches tick limit, but with lower score and a fatter enemy tail.
- Stage 4 reaches tick limit, but collapses from `450` bullets at baseline
  tail to `0`.
- Stage 5 reaches tick limit, but ends at `score=0` and `bullet_count=0`
  instead of `score=5150` and `bullet_count=328`.

The important part is that this is not a stage-specific opcode gimmick. It is
the same shared early scheduler site across five retail stage scripts.

Stage 6 is the structural negative control: at the same path
`(sub=0, instruction=1)`, the opcode is already `132`, not `103`, so this
shared basin does not carry forward unchanged.

Representative headless outcomes:

| Stage | Baseline tail | Mutant tail | Headless findings |
| --- | --- | --- | --- |
| 1 | tick `311`, `score=2450`, `bullets=6`, terminal `physical-hit` | tick `600`, `score=1280`, `bullets=15`, terminal `tick-limit` | `score-drift`, `enemy-count-drift` |
| 2 | tick `535`, `score=17240`, `bullets=100`, terminal `physical-hit` | tick `513`, `score=12170`, `bullets=78`, terminal `physical-hit` | `score-drift`, `bullet-count-drift`, `enemy-count-drift` |
| 3 | tick `600`, `score=13000`, `bullets=19` | tick `600`, `score=6860`, `bullets=8` | `score-drift`, `enemy-count-drift` |
| 4 | tick `600`, `score=4380`, `bullets=450` | tick `600`, `score=5430`, `bullets=0` | `score-drift`, `enemy-count-drift`, `bullet-count-drift` |
| 5 | tick `600`, `score=5150`, `bullets=328` | tick `600`, `score=0`, `bullets=0` | `score-drift`, `bullet-count-drift` |

Rebuild and rerun the five patched payloads with:

```sh
PYTHONPATH=src python3 findings/semantic/stages1-5-opening-instruction-time-three-route-skew/reproduce.py
```

To rerun only a subset:

```sh
PYTHONPATH=src python3 findings/semantic/stages1-5-opening-instruction-time-three-route-skew/reproduce.py \
  --stage 4 \
  --stage 5
```

Tracked compact payload patches:

- `payload_stage1_instruction_time_3.json`
- `payload_stage2_instruction_time_3.json`
- `payload_stage3_instruction_time_3.json`
- `payload_stage4_instruction_time_3.json`
- `payload_stage5_instruction_time_3.json`

Current local evidence:

- source exploration grid:
  `artifacts/semantic-exploration-grid/20260822T-mutator-broaden-a/summary.json`
- cluster summary:
  `artifacts/semantic-clusters/20260822T222333Z/summary.json`
- local reproduce summary:
  `artifacts/findings/semantic-stages1-5-opening-instruction-time-three-route-skew/summary.json`

Current interpretation:

- headless: clearly interesting and reproducible;
- the basin is generic because the shared opening opcode site is the same
  across Stages 1-5;
- the output is fun because one tiny schedule nudge bends five stages in five
  different ways instead of collapsing into one boring crash shape.
