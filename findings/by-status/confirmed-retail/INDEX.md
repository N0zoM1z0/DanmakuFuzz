# Confirmed Retail

These cases reproduced under the Wine/retail oracle with a clean baseline
comparison. They should be promoted into durable finding directories when they
are minimized and documented.

## ECL timeline arg0 crash/stall family

Durable finding: `findings/semantic/ecl-timeline-arg0-retail-crash-stall-basin`.

- Stage 2 `timeline-arg0=256`: `crash-dialog`, Wine page fault at `004074DC`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage2-early/results.jsonl`.
- Stage 3 `timeline-arg0=-8`: `crash-dialog`, Wine page fault at `00412499`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage3-boss-crash/results.jsonl`.
- Stage 4 `timeline-arg0=-8`: `crash-dialog`, Wine page fault at `004074DC`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage4-crash-families/results.jsonl`.
- Stage 5 `timeline-arg0=-8`: `retail-frame-stall`, target frame `511`,
  observed frame `441`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage5-crash-families/results.jsonl`.
- Stage 5 `timeline-arg0=256`: `retail-frame-stall`, repeat `2/2` with
  `--expect-classification retail-frame-stall --require 2`.
  Evidence: `artifacts/checks/retail-repeat-stage5-timeline-arg0-256-frame-stall/report.json`.
- Stage 5 `timeline-arg0=-1`, `-64`, and `16383`: `crash-dialog`, Wine page
  faults at `004074DC`.
  Evidence: `artifacts/checks/retail-batch-more-stage5-timeline-arg0-values/results.jsonl`.
- Stage 6 `timeline-arg0=-2`: `crash-dialog`, Wine page fault at `004074DC`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage6-timeline-arg0/results.jsonl`.
- Stage 6 `timeline-arg0=255`: `retail-frame-stall`, target frame `510`,
  observed frame `441`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage6-timeline-arg0/results.jsonl`.
- Stage 6 `timeline-arg0=-59`, `-40`, `257`, and `32767`: `crash-dialog`.
  Evidence: `artifacts/checks/retail-batch-more-stage6-timeline-arg0-values/results.jsonl`.

## ECL jump-offset crash family

- Stage 4 `jump-offset=2139062143`: `crash-dialog`, Wine page fault at
  `004074DC`.
  Evidence: `artifacts/checks/retail-batch-weird-state-stage4-crash-families/results.jsonl`.

## ANM Stage 6 background crash basin

Durable finding: `findings/runtime/anm-stage6bg-retail-crash-basin`.

- `stg6bg.anm/first-sprite-offset-zero`: headless
  `anm-set-active-sprite-failure`, Wine `crash-dialog`, repeat `2/2` with
  `--expect-classification crash-dialog --require 2`.
  Evidence: `artifacts/checks/retail-repeat-anm-stage6bg-first-sprite-offset-zero-crash-20260823/report.json`.
- `stg6bg.anm/first-script-id-ffff`: headless `anm-script-drift`, Wine
  `crash-dialog`.
  Evidence: `artifacts/checks/retail-batch-anm-stage6bg-target-hits-20260823/results.jsonl`.
- `stg6bg.anm/first-script-offset-zero`: headless `anm-script-drift`, Wine
  `crash-dialog`.
  Evidence: `artifacts/checks/retail-batch-anm-stage6bg-target-hits-20260823/results.jsonl`.
