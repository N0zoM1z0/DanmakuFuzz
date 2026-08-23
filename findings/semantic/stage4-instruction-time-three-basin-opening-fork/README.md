# Stage 4 `instruction-time` three-basin opening fork

Observed on August 23, 2026.

This finding comes from the generic `instruction-time` exploration lane on
`ecldata4.ecl`. The target is the Stage 4 opening site `(sub=0, instruction=2)`
at opcode `45`, whose original `instruction.time` is `0`.

Exact reruns show that `0` is a real separator, not just the baseline value.
Around this site, the scheduler forks into three stable local outcomes:

- `instruction.time=-1` and `instruction.time=513` collapse into the same
  suppressive basin;
- `instruction.time=1` stays on a denser late-volley shoulder;
- `instruction.time=87` lands on a third score-shift shoulder.

At tick `600`, the baseline tail is:

- `score=4380`
- `enemy_count=11`
- `item_count=1`
- `bullet_count=450`

The shared suppressive basin (`-1` and `513`) reproduces one exact trace:

- trace SHA-256:
  `2c8d0f0ee98c93168ae6365e36e21a64ff80605a79e0157b0de9318d02fcf6e7`
- oracle hits:
  - `score-drift: tick 502 baseline=290 case=0`
  - `enemy-count-drift: tick 525 baseline=8 case=6`
  - `bullet-count-drift: tick 554 baseline=96 case=0`
- tail at tick `600`:
  - `score=5430`
  - `enemy_count=4`
  - `item_count=2`
  - `bullet_count=0`

The `instruction.time=1` shoulder keeps most of the volley alive:

- trace SHA-256:
  `17923bc599b06c4b10aefc25cfb70bc725ca7318c8d16843dbd67e1eb1ddc633`
- oracle hit:
  - `score-drift: tick 596 baseline=4360 case=6430`
- tail at tick `600`:
  - `score=6450`
  - `enemy_count=10`
  - `item_count=2`
  - `bullet_count=442`

The `instruction.time=87` shoulder is the subtle one:

- trace SHA-256:
  `a3cd34bf22d64b4d36483be2befd47d20478c053fa8f0e79c2dbd7dd3e02257e`
- it hits the same coarse oracle triplet as the shared suppressive basin;
- but it does **not** share the exact trace, and its tail score is higher:
  - `score=5890`
  - `enemy_count=4`
  - `item_count=2`
  - `bullet_count=0`

So this site is useful for two reasons at once:

- it has a clean cross-value alias basin (`-1` and `513`);
- it also shows why exact trace basin mapping matters, because `87` would look
  deceptively “the same” if we only clustered on coarse score/bullet oracles.

Rebuild the tracked payloads from the local corpus seed and rerun the headless
confirmation with:

```sh
PYTHONPATH=src python3 findings/semantic/stage4-instruction-time-three-basin-opening-fork/reproduce.py
```

To also drive the shared-basin `instruction.time=-1` representative through
retail Practice Stage 4 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage4-instruction-time-three-basin-opening-fork/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_instruction_time_neg1.json`
- `payload_instruction_time_1.json`
- `payload_instruction_time_87.json`
- `payload_instruction_time_513.json`

Current local evidence:

- multiseed family sweep:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260823T-instruction-time-multiseed-scout-a/summary.json`
- exact basin harvest:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/_smoke/20260823-instruction-time-stage4-basin-a/summary.json`
- dedicated finding rerun:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage4-instruction-time-three-basin-opening-fork/summary.json`
- retail smoke for `instruction.time=-1`:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage4-instruction-time-three-basin-opening-fork/retail/report.json`

Why this one matters:

- it comes from the generic `instruction-time` family, which is portable to
  TH07/TH08;
- it is not just “negative is weird”: one wrapped positive value (`513`) joins
  the same exact basin as `-1`;
- a nearby positive value (`87`) escapes that basin while still matching the
  same coarse drift oracles, which makes it a good validation target for exact
  trace-based clustering;
- it is semantic and visible: late enemy/bullet population changes sharply
  without needing a crash.

Current interpretation:

- headless: clearly interesting and reproducible;
- locally, `0` is the separator, `-1/513` share a suppressive basin, `1`
  preserves a dense late volley, and `87` forms a third score-shift shoulder;
- retail: on August 23, 2026, the `instruction.time=-1` smoke reached a live
  game window under Wine, showed no Wine crash signature, and then stayed
  pixel-static for the 2.0-second progress probe, so the current retail oracle
  classified it as `game-window-static`.
