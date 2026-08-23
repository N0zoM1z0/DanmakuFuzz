# Blocked Retail Oracle

These cases are not confirmed false positives. They are blocked because the
current retail setup does not yet provide the controls needed to make the
oracle meaningful.

- `findings/semantic/stage1-bullet-count2-257-progress-wedge`: headless
  progress wedge, but long Stage 1 Wine probes are not trustworthy without a
  gameplay/control policy. Recent Stage 1 retail probes ended as
  `stage-progress-unverified` or `retail-baseline-oracle-drift`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage1-stalls-longprobe/results.jsonl`.

Needed before promotion: deterministic retail gameplay controls for early
stages, plus a progress oracle that proves the clean baseline and mutant are
being compared in the same stage state.
