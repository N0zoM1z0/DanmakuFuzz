# Retail Confirmation

Headless traces are where DanmakuFuzz hunts. Retail Wine is where a finding
earns its name.

For TH06 that distinction matters. A fast headless run can expose impossible
timeline state, replay exhaustion, or resource-loader drift, but the shipped
game still owns the final oracle for crash and stall claims. Retail
confirmation is the gate between "interesting danmaku physics" and "this
breaks the real Scarlet Devil Mansion."

## Contract

A retail-positive finding needs:

- an exact payload recipe or payload hash;
- an isolated Wine prefix and copied game directory;
- a clean baseline run for the same route/stage controls;
- an expected classification such as `crash-dialog` or `retail-frame-stall`;
- repeat/require gates when the claim is promoted as deterministic;
- normalized Wine signatures so thread IDs and addresses do not split one
  crash family into noise.

Use `retail-error-dialog` and `game-window-blank-static` as control failures,
not findings. They usually mean the local Wine/Xvfb path failed before TH06
reached a trustworthy game state.

## Single Case

`danmakufuzz.retail.confirm_case` takes a semantic `result.json`, patches the
payload into an isolated copy of the owned TH06 tree, drives Practice mode, and
writes `report.json`.

Promotion-style run:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.confirm_case \
  --result artifacts/some-campaign/case/result.json \
  --practice-stage 6 \
  --difficulty 3 \
  --timeout-seconds 28 \
  --compare-clean-baseline \
  --expect-classification crash-dialog \
  --repeat 3 \
  --require 3
```

Each repeat gets its own child artifact directory, game copy, Wine prefix, and
display. If fewer than `--require` repeats match, the command exits non-zero.

Useful diagnostic knobs:

- `--startup-normalization {auto,gdb,off}` controls the TH06 startup helper.
- `--xvfb-screen-size WIDTHxHEIGHTxDEPTH` changes the virtual display.
- `--color-mode-16bit {0,1,255,preserve}` changes the TH06 cfg color byte.

Record these knobs in evidence when they matter. Do not mix them silently into
a promoted claim.

## Batch Queue

`danmakufuzz.retail.batch_confirm` wraps the same single-case runner across a
queue of campaign/minimizer outputs:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.batch_confirm \
  --from-minimized \
  --practice-stage 6 \
  --difficulty 3 \
  --timeout-seconds 28 \
  --compare-clean-baseline \
  --stop-on-classification crash-dialog
```

Preview a queue without launching Wine:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.batch_confirm \
  --from-minimized \
  --interesting-only \
  --max-per-finding 1 \
  --list-only
```

Use history when rerunning a large queue:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.batch_confirm \
  --history artifacts/checks/previous-retail-batch/summary.json \
  --skip-known-signature \
  --from-minimized \
  --interesting-only \
  --list-only
```

The batch output is queue metadata plus one `results.jsonl` row per case. The
important grouping fields are `classification`, `retail_signature_key`, and the
headless finding key that led the case into the queue.

## Classifications

Treat these as promotable when they beat a clean baseline:

- `crash-dialog`: Wine exposes a program-error/debugger window after stage
  entry.
- `wine-crash-log`: `wine.log` contains an unhandled exception/page-fault
  signature even when window census is weak.
- `retail-frame-stall`: Practice mode starts, but the frame-progress oracle
  fails while the clean baseline advances.
- `abnormal-exit`: the process exits non-zero without a stronger crash-window
  signature. This needs review before promotion.

Treat these as non-promoting outcomes:

- `game-window-live`: the game stayed live.
- `game-window-static`: the window stayed live but progress was not proven.
- `game-window-blank-static`: local renderer/control failure.
- `retail-error-dialog`: usually Direct3D/startup failure unless the clean
  baseline differs.
- `retail-baseline-equivalent`: mutant and clean control share the same oracle
  and screenshots within the equivalence threshold.

## Evidence Shape

A strong finding directory should carry:

- `finding.json` with `expected_oracle`, `payload_sha256`, run counts, and
  triage status;
- `cases.json` or another compact recipe that can rebuild the payload without
  old search artifacts;
- `reproduce.py` that calls `confirm_case` with `--compare-clean-baseline`,
  `--expect-classification`, and repeat/require gates where appropriate;
- optional ignored artifact paths for audit history, never as the only way to
  recreate the payload.

This is why confirmed TH06 findings now rebuild ECL timeline-arg0 and ANM
Stage 6 payloads from local owned corpus data before invoking retail.
