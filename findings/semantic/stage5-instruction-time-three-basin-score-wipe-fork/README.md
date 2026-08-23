# Stage 5 `instruction-time` three-basin score-wipe fork

Observed on August 23, 2026.

This finding comes from the generic `instruction-time` exploration lane on
`ecldata5.ecl`. The target is the Stage 5 opening site `(sub=0, instruction=3)`
at opcode `48`, whose original `instruction.time` is `40`.

This site is stronger than a simple “zero is special” story. Exact reruns split
it into three stable local basins:

- `instruction.time=-1` joins a shared wrapped-value basin;
- `instruction.time=0` lands on a zeroed-score basin;
- `instruction.time=1` lands on a sibling basin with the same coarse tail and
  the same coarse oracles as `0`, but on a different exact trace.

At tick `600`, the baseline tail is:

- `score=5150`
- `enemy_count=1`
- `item_count=1`
- `bullet_count=328`

The shared wrapped-value basin contains at least these exact values:

- `-1`
- `1064`
- `3059`
- `1937177359`
- `-2139062144`

Those values collapse into one exact trace:

- trace SHA-256:
  `b9ed7f3fcfffd8c6cf983b54ecd84568a1267cdf614b2b2803ac359f6adff742`
- oracle hits:
  - `bullet-count-drift: tick 525 baseline=320 case=0`
  - `score-drift: tick 534 baseline=1670 case=1870`
- tail at tick `600`:
  - `score=7260`
  - `enemy_count=0`
  - `item_count=2`
  - `bullet_count=0`

The `instruction.time=0` and `instruction.time=1` pair is the more subtle part.
They do **not** join that shared wrapped basin, but they also do not separate
cleanly under coarse scoring alone:

- both hit the same coarse oracle pair:
  - `score-drift: tick 487 baseline=490 case=0`
  - `bullet-count-drift: tick 540 baseline=560 case=240`
- both end with the same tail summary at tick `600`:
  - `score=0`
  - `enemy_count=2`
  - `item_count=0`
  - `bullet_count=0`

But they are still different exact traces:

- `instruction.time=0` trace SHA-256:
  `3ddafa4399243549193456a6da2f2de909b3188e3b112bf860c8634e4811af6d`
- `instruction.time=1` trace SHA-256:
  `120ca1ebf1ef2aa153026cf90fe76e4c99fa27fcfe52c47dbd1d7e34ff10ead4`

Their first exact split appears by tick `441`. At that point the usual counters
still match, but the spawned enemy state already differs in subpixel Y:

- `instruction.time=0`: enemy `y=-46.0666656`
- `instruction.time=1`: enemy `y=-46`

So this site shows two independent fuzzing lessons:

- a small sentinel value (`-1`) aliases with large wrapped positives into one
  shared basin;
- two neighboring exact values (`0` and `1`) can look identical to coarse
  score/bullet oracles and even to the final tail summary, while still being
  different runtime traces.

Rebuild the tracked payloads from the local corpus seed and rerun the headless
confirmation with:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-instruction-time-three-basin-score-wipe-fork/reproduce.py
```

To also drive the shared-basin `instruction.time=-1` representative through
retail Practice Stage 5 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-instruction-time-three-basin-score-wipe-fork/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_instruction_time_neg1.json`
- `payload_instruction_time_0.json`
- `payload_instruction_time_1.json`
- `payload_instruction_time_1064.json`

Current local evidence:

- multiseed family sweep:
  `artifacts/semantic-family-sweep/20260823T-instruction-time-multiseed-scout-a/summary.json`
- exact basin harvest:
  `artifacts/_smoke/20260823-instruction-time-stage5-basin-a/summary.json`
- dedicated finding rerun:
  `artifacts/findings/semantic-stage5-instruction-time-three-basin-score-wipe-fork/summary.json`
- retail smoke for `instruction.time=-1`:
  `artifacts/findings/semantic-stage5-instruction-time-three-basin-score-wipe-fork/retail/report.json`

Why this one matters:

- it comes from the generic `instruction-time` family, not a stage-specific
  hand patch;
- the shared basin crosses sign and magnitude, so it is not just “negative
  values are weird”;
- the `0`/`1` pair is a strong proof that exact trace clustering adds signal
  beyond coarse score/bullet oracles and beyond tail summaries;
- it is semantic and visible: score, enemy population, item count, and bullet
  population all diverge without needing a crash.

Current interpretation:

- headless: clearly interesting and reproducible;
- locally, the site splits into one shared wrapped-value basin and two
  neighboring exact micro-basins for `0` and `1`;
- the `0`/`1` split first shows up as a subpixel enemy-position difference,
  which suggests a sensitive scheduler or spawn-timing float boundary;
- retail: on August 23, 2026, the `instruction.time=-1` smoke reached a live
  game window under Wine, showed no Wine crash signature, and then stayed
  pixel-static for the 2.0-second progress probe, so the current retail oracle
  classified it as `game-window-static`.
