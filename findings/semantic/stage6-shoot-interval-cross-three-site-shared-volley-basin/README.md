# Stage 6 `shoot-interval-cross` three-site shared volley basin

Observed on August 22, 2026.

This finding captures a reusable Stage 6 scheduler basin where three adjacent
`shoot-interval-cross` sites all collapse into the same exact 600-tick trace.
The sites are all opcode `77` (`shoot-interval-delayed`) in `ecldata6.ecl`:

- `(sub=2, instruction=6)` originally `(time=0, shoot-interval=80)`
- `(sub=2, instruction=7)` originally `(time=0, shoot-interval=50)`
- `(sub=2, instruction=8)` originally `(time=0, shoot-interval=30)`

The three exact rebuilt cross-pair representatives are:

- `shoot-interval-cross-16-62`
- `shoot-interval-cross-neg1-neg4750`
- `shoot-interval-cross-30-0`

All three reproduce the same full trace byte for byte:

- trace SHA-256:
  `0cc1e8684ef13cf8709091eaac872d1b8c0f4d6b963ab746e5bccce815171aa6`
- shared oracle hits:
  - `score-drift: tick 528 baseline=4760 case=3570`
  - `enemy-count-drift: tick 563 baseline=7 case=10`
  - `bullet-count-drift: tick 567 baseline=176 case=108`

The basin diverges from the retail Stage 6 baseline earlier than those
interestingness thresholds:

- first raw bullet-count split at tick `457` (`baseline=12`, `case=0`)
- first raw item-count split at tick `494` (`baseline=2`, `case=1`)
- first raw enemy-count split at tick `495` (`baseline=5`, `case=6`)

By tick `600`, the shared basin is still materially different from baseline:

- baseline tail:
  - `score=16270`
  - `enemy_count=6`
  - `item_count=14`
  - `bullet_count=187`
- shared basin tail:
  - `score=12740`
  - `enemy_count=9`
  - `item_count=11`
  - `bullet_count=112`

So this is not one bad value on one isolated instruction. It is a real
adjacent-site basin inside the same Stage 6 timing cluster: three different
cross-pair edits land on the same reduced-score, extra-enemy, thinner-volley
trace.

Rebuild the three exact payloads from the local baseline corpus and rerun the
headless differential checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-shoot-interval-cross-three-site-shared-volley-basin/reproduce.py
```

To also drive the simplest representative, `shoot-interval-cross-30-0`, through
retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-shoot-interval-cross-three-site-shared-volley-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_shoot_interval_cross_16_62.json`
- `payload_shoot_interval_cross_neg1_neg4750.json`
- `payload_shoot_interval_cross_30_0.json`

Current local evidence:

- source family sweep:
  `artifacts/semantic-family-sweep/20260822T-time-cross-scout-a/summary.json`
- cluster summary for the scout:
  `artifacts/semantic-clusters/20260822T-time-cross-scout-a/summary.json`
- August 22, 2026 retail smoke for `shoot-interval-cross-30-0`:
  `artifacts/findings/semantic-stage6-shoot-interval-cross-three-site-shared-volley-basin/retail/report.json`

Why this one matters:

- it comes from the generic `shoot-interval-cross` exploration family rather
  than a one-off hand patch;
- the three representatives hit three adjacent Stage 6 timing sites, so the
  basin is structural, not a single offset accident;
- all three land on the exact same full trace, which makes the basin unusually
  clean and easy to replay;
- this is the kind of portable scheduler behavior we want before carrying the
  mutator family forward to TH07/TH08.

Current interpretation:

- headless: clearly interesting and reproducible;
- the fun part is the collapse: three different cross-pair edits on adjacent
  delayed-shot instructions converge to one thinner-volley shared trace;
- retail: on August 22, 2026, the `shoot-interval-cross-30-0` smoke reached a
  live game window under Wine but then stayed completely static over the 2.0 s
  progress probe (`0 / 786432` changed pixels, ratio `0.0`), so the current
  retail oracle classifies it as `game-window-static`;
- that is stronger than “launches fine” and weaker than “fully confirmed stage
  behavior”: it says the representative reaches the retail window, does not
  present a Wine crash signature, and then appears to stall or freeze under the
  current practice automation.
