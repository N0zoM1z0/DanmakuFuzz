# Replay-native first-bookmark cut-tail input-error basin

Observed on August 23, 2026.

This finding comes from the replay-native semantic lane rather than from ECL or
raw action mutation alone. The trigger is the same replay-native mutator across
two very different public TH06 replays:

- mutant: `bookmark-cut-tail-i001-t1`
- effect: keep the initial replay bookmark, cut the tail at the first
  non-initial bookmark, then terminate the compressed replay stream

On both:

- `fairysvoice-th6-001.rpy` Stage 1
- `fairysvoice-th6-002.rpy` Stage 7 / Extra

the mutated replay collapses into the same tiny basin:

- headless action stream exhausts at tick `2`
- final trace tick is `3`
- terminal reason becomes `input-error`
- process exits with code `1`

This matters because it is a replay-structure finding, not just “change the
expanded action stream and something different happens.” A tiny edit to the
compressed replay bookmark stream is enough to turn two unrelated replay seeds
into the same degenerate early-termination basin.

Reproduce with:

```sh
PYTHONPATH=src python3 findings/semantic/replay-native-first-bookmark-cut-tail-input-error-basin/reproduce.py
```

If the public replays are not already present under
`artifacts/replay-corpus-public/th06/`, the reproducer will fetch the tracked
public corpus entries from:

- `reference/corpus/replay/public/th06/manifest.json`

Original trigger commands:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_desync_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-001.rpy \
  --stage 1 \
  --max-ticks 1800 \
  --continue-after-hit \
  --trace-compact-counts \
  --mutant-profile native \
  --limit 6
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_desync_campaign \
  --input artifacts/replay-corpus-public/th06/fairysvoice-th6-002.rpy \
  --stage 7 \
  --max-ticks 1800 \
  --continue-after-hit \
  --trace-compact-counts \
  --mutant-profile native \
  --limit 6
```

Tracked reconstruction metadata:

- `cases.json`

Current local evidence:

- Stage 1 campaign:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-replay-native-stage1-v2/campaign.json`
- Stage 7 campaign:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-replay-native-stage7-v2/campaign.json`
