# Replay-native Stage 4 `stage-payload-borrow-prev-s3` script-drift basin

This finding captures a replay-specific Stage 4 basin from the native replay
lane: replace the Stage 4 replay payload with the same replay's Stage 3 payload
(`stage-payload-borrow-prev-s3`), and the run stays stable enough to reach tick
1800 but the stage scheduler no longer looks healthy.

Across two public full-game replays, the borrowed payload does the same
qualitative thing:

- `stage_vm.loaded` flips from `True` in baseline to `False` late in the run;
- `stage_vm.script_time` and `ecl_timeline.time` fall behind the baseline;
- `ecl_timeline.next_time` converges to the same late target `1878`;
- the replay stays deterministic (`replay-stable-trace-drift`) instead of
  crashing or desyncing between repeat runs.

This is the kind of replay-layer weirdness worth keeping: the `.rpy` structure
is still valid enough to run, but cross-stage payload reuse pushes the Stage 4
script/timeline state machine into a clearly different basin.

## Basin summary

- mutant: `stage-payload-borrow-prev-s3`
- source lane: `replay-native`
- stage: `4`
- pattern cluster kind: `mutation-pattern`
- primary finding kind: `stage-script-drift`
- pattern cluster cases: `2`

Reproducible cases:

- `fairysvoice-th6-001.rpy` → trace
  `2b1361ba562daa589215daa7ba440197d6b03bf9f9a5cadb26e10e62a6e45568`
- `gensokyo-th6-802.rpy` → trace
  `6d677060a7024b13b3e2f1a6d654c13bec4ee45f650cbc1c5827cb31912a8268`

Both end at tick 1800 with:

- `terminal_reason = tick-limit`
- `stage_vm.loaded = false`
- `stage_vm.instruction_index = 7`
- `ecl_timeline.next_time = 1878`

## Corpus / cluster commands

Focused public corpus sweep used to harvest this basin:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-001.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-801.rpy \
  --input artifacts/replay-corpus-public/th06/gensokyo-th6-802.rpy \
  --stage-filter 1 \
  --stage-filter 2 \
  --stage-filter 3 \
  --stage-filter 4 \
  --stage-filter 5 \
  --stage-filter 6 \
  --max-ticks 1800 \
  --mutant-profile native \
  --name-filter stage-payload-borrow \
  --limit 4 \
  --continue-after-hit \
  --trace-compact-counts \
  --artifact-dir artifacts/replay-payload-borrow-focus-v1
```

Re-cluster that sweep with the replay-specific pattern view:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_cluster \
  --result artifacts/replay-payload-borrow-focus-v1/campaign.json \
  --artifact-dir artifacts/replay-payload-borrow-focus-v1/recluster-v2
```

The representative pattern cluster is in:

- `artifacts/replay-payload-borrow-focus-v1/recluster-v2/summary.json`

Look for:

- `mutant_name = stage-payload-borrow-prev-s3`
- `primary_finding_kind = stage-script-drift`
- `cases = 2`

## Stable reproduction

Run:

```sh
PYTHONPATH=src python3 findings/semantic/replay-native-stage4-payload-borrow-prev-s3-script-drift-basin/reproduce.py
```

That script:

- fetches the required public `.rpy` files if they are missing;
- reruns only `stage-payload-borrow-prev-s3` against the two tracked replays;
- checks `stage-script-drift`, `ecl-timeline-drift`, and
  `replay-stable-trace-drift`;
- verifies the exact trace sha256 and the late Stage 4 tail state;
- rebuilds the local replay cluster summary from the reproduced results and
  confirms that both cases land in one `mutation-pattern` cluster.
