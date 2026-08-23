# Headless Pending Retail

These findings have reproducible headless evidence, but they have not yet been
confirmed against a trustworthy retail oracle.

- `findings/semantic/stage6-bullet-count-cross-32774-130-progress-wedge`
- `findings/semantic/stage6-bullet-count1-256-progress-wedge`
- `findings/semantic/stage6-jump-offset-large-forward-headless-wedge`
- Replay Stage 6 state-oracle smoke: `8` generated mutants, `6`
  interesting stable state drifts. The oracle now reports first divergence by
  `game_frame`, trace line, VM/timeline/entity fields, and ignores replay seed
  metadata-only differences.
  Evidence: `artifacts/checks/replay-desync-stage6-state-oracle-smoke-v2-20260823/campaign.json`.
- `findings/semantic/replay-native-first-bookmark-cut-tail-input-error-basin`:
  3 public replay cases reproduce as deterministic `input-error` /
  returncode `1`, including the new `gensokyo-th6-804` Stage 6
  `bookmark-cut-tail-i001-t56` case.
- Existing semantic/replay finding directories without `finding.json` remain in
  this bucket by default until they are rebuilt and assigned a concrete
  `triage_status`.

Promotion requirement: rerun the exact rebuilt payload through
`danmakufuzz.retail.confirm_case` with `--compare-clean-baseline` and, where
possible, `--expect-classification`, `--repeat`, and `--require`.
