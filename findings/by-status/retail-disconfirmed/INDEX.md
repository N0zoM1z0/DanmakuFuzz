# Retail Disconfirmed

These entries were interesting in headless or parser/model space, but the
current Wine/retail oracle did not reproduce the original bug-shaped claim.
They should not be counted as retail true positives unless a stronger oracle or
new evidence changes the status.

## Live retail observations, not crash/stall positives

- Stage 6 `shoot-interval` and `bullet-count` semantic samples:
  `4/4 game-window-live`. They show screenshot drift but no crash, frame-stall,
  or confirmed progress failure.
  Evidence: `artifacts/checks/retail-batch-stage6-bullet-shoot-semantic/results.jsonl`.
- Stage 6 `timeline-opcode` and `adjacent-timeline-time` samples:
  `4/4 game-window-live`, including one headless `timeline-next-time-negative`
  candidate.
  Evidence: `artifacts/checks/retail-batch-stage6-opcode-time-control/results.jsonl`.
- Stage 5 `jump-offset` samples: `4/4 game-window-live` in the expanded batch,
  plus the earlier `jump-offset=-8388609` representative was also live.
  Evidence:
  `artifacts/checks/retail-batch-stage5-jump-offset-more/results.jsonl` and
  `artifacts/checks/retail-batch-weird-state-stage5-crash-families/results.jsonl`.
- Stage 3 `jump-offset=16843009`: `game-window-live`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage3-boss-crash/results.jsonl`.
- Stage 2 `timeline-arg0=31`, Stage 2 adjacent timeline negative, and Stage 3
  boss UI/health drift representatives: `game-window-live` with visual drift
  only.
  Evidence:
  `artifacts/checks/retail-batch-weird-state-stage2-early/results.jsonl` and
  `artifacts/checks/retail-batch-weird-state-stage3-boss-crash/results.jsonl`.

## How to interpret this bucket

`game-window-live` with `baseline-visual-drift` is still useful as a format or
semantic observation, but it is not a Wine-confirmed crash/stall finding. Keep
these cases out of the confirmed bug queue unless the reproducer grows a more
specific expected oracle, such as a verified impossible stage state or a
reliable retail gameplay invariant.
