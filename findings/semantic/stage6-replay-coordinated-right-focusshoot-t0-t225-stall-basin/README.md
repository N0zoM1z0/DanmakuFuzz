# Stage 6 replay coordinated `right+focus+shoot` stall basin

Observed on August 23, 2026.

This finding comes from the replay semantic/desync lane, not from ECL mutation
and not from the older single-site input burst lane.

The payload is a tiny replay-equivalent raw-mask action stream:

- `8 mask:0x0085`
- `217 mask:0x0005`
- `8 mask:0x0000`
- `1567 mask:0x0005`

That means:

- an 8-tick opening `right + focus + shoot` window;
- then the baseline `focus + shoot` path resumes;
- another 8-tick change lands at tick `225`;
- then the normal route resumes again.

Under Stage 6 Practice, seed `7`, Lunatic, Reimu A, `--continue-after-hit`,
that two-site replay mutation is enough to push TH06 into a stable late-stage
scheduler wedge.

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

- `game_frame=1489`
- `score=1576650`
- `enemy_count=4`
- `stage_vm.loaded=False`
- `stage_vm.script_time=1489`
- `stage_vm.instruction_index=4`
- `ecl_timeline.time=1489`
- `ecl_timeline.next_time=1544`

The headless oracle reports:

- `stalled-progress`
- `stalled-frame`
- `stage-script-drift`
- `ecl-timeline-drift`

The strongest stall signature is:

- `frame=1489 window>=240 tick=1729 ... stage_vm.loaded=False ... ecl_timeline.next_time=1544`

Why this one matters:

- it needs coordinated multi-site mutation, not one local burst;
- it survives replay-style normalization into raw input masks;
- it is deterministic across repeated runs;
- it wedges the stage script and ECL timeline without needing malformed binary
  resources.

Reproduce with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-replay-coordinated-right-focusshoot-t0-t225-stall-basin/reproduce.py
```

Trigger command that originally surfaced it:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_desync_campaign \
  --stage 6 \
  --difficulty 3 \
  --character 0 \
  --shot-type 0 \
  --actions config/headless_baseline_actions_1800.txt \
  --max-ticks 1800 \
  --continue-after-hit \
  --limit 12 \
  --trace-compact-counts
```

Tracked payloads:

- `payload_actions.txt`
- `payload_recipe.json`

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-replay-desync-long-smoke/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-replay-desync-long-smoke/0007-coordinated-right-focusshoot-t0-t225-w8/result.json`
- nearby single-site sibling:
  `/home/yann/yann/touhou/DanmakuFuzz/findings/semantic/stage6-input-fast-burst-t225-stall-basin/README.md`
