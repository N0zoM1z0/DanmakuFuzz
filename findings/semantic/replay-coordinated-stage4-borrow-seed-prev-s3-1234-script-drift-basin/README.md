# Replay-coordinated Stage 4 `borrow-seed-prev-s3-s1234` script-drift basin

This finding upgrades the first real replay-native coordinated basin: keep the
run on Stage 4, replace its stage payload with the same replay's Stage 3
payload, and then force the borrowed payload's RNG seed to `0x1234`.

That two-field replay mutation is stronger than either lane alone:

- plain `stage-seed-1234` mostly gives deterministic trace drift;
- plain `stage-payload-borrow-prev-s3` already showed a 2-case script-drift
  basin;
- `coordinated-borrow-seed-prev-s3-s1234` pushes that Stage 4 scheduler basin
  to 4/4 across the current public main-route corpus.

## Basin summary

- mutant: `coordinated-borrow-seed-prev-s3-s1234`
- source lane: `replay-coordinated`
- stage: `4`
- pattern cluster kind: `mutation-pattern`
- primary finding kind: `stage-script-drift`
- pattern cluster cases: `4`

Affected public replays:

- `fairysvoice-th6-001.rpy`
- `gensokyo-th6-801.rpy`
- `gensokyo-th6-802.rpy`
- `gensokyo-th6-804.rpy`

Shared late behavior:

- `terminal_reason = tick-limit`
- `stage_vm.loaded = false`
- `stage_vm.instruction_index = 7`
- `replay_random_seed = 4660`
- `ecl-timeline-drift` also fires in all four cases

The exact late script/timeline time shifts differ per replay, but the basin
shape is the same: Stage 4 stays alive until tick 1800 while the script VM
quietly falls behind and deactivates.

## Harvest command

Focused coordinated sweep:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-001.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-801.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-802.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-804.rpy \
  --stage-filter 4 \
  --max-ticks 1800 \
  --mutant-profile coordinated \
  --name-filter coordinated-borrow \
  --limit 8 \
  --continue-after-hit \
  --trace-compact-counts \
  --artifact-dir artifacts/replay-coordinated-stage4-borrow-focus-v1
```

The representative cluster lives in:

- `artifacts/replay-coordinated-stage4-borrow-focus-v1/clusters.json`

Look for:

- `mutant_name = coordinated-borrow-seed-prev-s3-s1234`
- `primary_finding_kind = stage-script-drift`
- `cases = 4`

## Stable reproduction

Run:

```sh
PYTHONPATH=src python3 findings/semantic/replay-coordinated-stage4-borrow-seed-prev-s3-1234-script-drift-basin/reproduce.py
```

That script:

- fetches any missing public `.rpy` inputs;
- reruns only `coordinated-borrow-seed-prev-s3-s1234`;
- verifies `stage-script-drift`, `ecl-timeline-drift`, and
  `replay-stable-trace-drift`;
- checks the exact trace sha256 for all four cases;
- rebuilds a local replay cluster summary and confirms the four cases collapse
  into one `mutation-pattern` basin.
