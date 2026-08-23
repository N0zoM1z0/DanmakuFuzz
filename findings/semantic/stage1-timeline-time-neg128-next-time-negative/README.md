# Stage 1 timeline `time=-128` negative-`next_time` basin

Observed on August 23, 2026.

This finding comes from the new source-less timeline mutation lane rather than
from a TH06-specific opcode mutator. It patches the first timeline
instruction's `time` field to `-128` and leaves the rest of the ECL payload
structurally valid.

On TH06 Practice Stage 1, seed `7`, Lunatic, Reimu A, the result is not just a
crash. The scheduler immediately falls into a broken basin:

- `ecl_timeline.next_time` is already `-128` at tick `1`;
- the stage never recovers that negative `next_time`;
- the run drifts from the baseline route and ends at the `600`-tick limit
  instead of the baseline `physical-hit` tail at tick `311`;
- by the tail, the game is effectively empty: `enemy_count=0`, `score=0`,
  `stage_vm.script_time=600`, `ecl_timeline.next_time=-128`.

The headless oracle reports:

- `timeline-next-time-negative`
- `ecl-timeline-drift`
- `enemy-count-drift`
- `score-drift`
- `terminal-reason-drift`

This matters because it is exactly the kind of portable, source-less semantic
case we want for later TH07/TH08 work: no VM source knowledge, no TH06-specific
opcode semantics, just raw timeline mutation plus a scheduler-side oracle.

Reproduce with:

```sh
PYTHONPATH=src python3 findings/semantic/stage1-timeline-time-neg128-next-time-negative/reproduce.py
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

- `payload_timeline_time_neg128.json`

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic/campaign-stage1-seed7-ecldata1/summary.jsonl`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic/campaign-stage1-seed7-ecldata1/0005-timeline-time-sampled-neg128-raw/result.json`
