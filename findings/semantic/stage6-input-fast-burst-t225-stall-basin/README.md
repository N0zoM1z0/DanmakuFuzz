# Stage 6 input `down_fast` burst stall basin

Observed on August 23, 2026.

This finding comes from the new input/replay-style semantic lane rather than
from ECL mutation. The payload is only a tiny action-stream edit against the
normal `1800 stay` baseline:

- baseline: `1800 stay`
- mutant: `225 stay`, then `8 down_fast`, then `1567 stay`

On Stage 6 Practice, seed `7`, Lunatic, Reimu A, `--continue-after-hit`, that
8-tick burst is enough to push the late-stage scheduler into a different basin.

Baseline tail at tick `1800`:

- `game_frame=1731`
- `score=1578580`
- `enemy_count=6`
- `stage_vm.loaded=False`
- `stage_vm.script_time=1731`
- `stage_vm.instruction_index=5`
- `ecl_timeline.time=1731`
- `ecl_timeline.next_time=1784`

Mutant tail at tick `1800`:

- `game_frame=1470`
- `score=1062100`
- `enemy_count=4`
- `stage_vm.loaded=False`
- `stage_vm.script_time=1470`
- `stage_vm.instruction_index=4`
- `ecl_timeline.time=1470`
- `ecl_timeline.next_time=1544`

The headless oracle reports:

- `stalled-progress`
- `stalled-frame`
- `stage-script-drift`
- `ecl-timeline-drift`

The strongest stall signature is:

- `frame=1470 window>=240 tick=1710 ... stage_vm.loaded=False ... ecl_timeline.next_time=1544`

This one matters because the trigger is not a malformed resource blob and not a
long scripted route. It is a tiny, portable input perturbation that still
drives TH06 into a distinct late-stage scheduler wedge.

Reproduce with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-input-fast-burst-t225-stall-basin/reproduce.py
```

Trigger command that originally surfaced it:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.input_campaign \
  --stage 6 \
  --seed 7 \
  --actions config/headless_baseline_actions_1800.txt \
  --max-ticks 1800 \
  --continue-after-hit \
  --limit 12 \
  --random-seed 7 \
  --samples-per-site 3 \
  --timeout-seconds 12
```

Tracked payload:

- `payload_actions.txt`

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-input/20260823T020540Z/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-input/20260823T020540Z/0007-fast-burst-down_fast-t225-w8/result.json`

