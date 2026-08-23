# Stage 6 `shoot-interval` three-site sign basin cluster

Observed on August 23, 2026.

This finding captures a clean sign-sensitive timing cluster in Stage 6
`ecldata6.ecl`. Three adjacent opcode `77` (`shoot-interval-delayed`) sites
all start from the same original interval value `30`:

- `(sub=1, instruction=8)`
- `(sub=2, instruction=8)`
- `(sub=3, instruction=8)`

The interesting part is not “some weird huge value works.” After exact basin
reruns, all three sites show the same local structure:

- `shoot-interval = 0` stays in a near-baseline separator basin.
- `shoot-interval = -1` falls into a reduced-volley basin.
- `shoot-interval = 1` flips into an explosive over-volley basin.

The sampler first found three odd-looking representatives:

- `(sub=1, instruction=8)`: `-115`
- `(sub=2, instruction=8)`: `28494`
- `(sub=3, instruction=8)`: `94`

But exact reruns show those are not isolated magic numbers. They are aliases
for the same local sign basins around the simple sentinels `-1 / 0 / 1`.

At tick `600`, the retail baseline tail is:

- `score=16270`
- `enemy_count=6`
- `item_count=14`
- `bullet_count=187`

The three exact `-1` tails suppress the volley:

- `(sub=1, instruction=8)`: `bullet_count=151`
- `(sub=2, instruction=8)`: `bullet_count=124`
- `(sub=3, instruction=8)`: `bullet_count=143`

The three exact `1` tails instead explode the volley:

- `(sub=1, instruction=8)`: `bullet_count=639`
- `(sub=2, instruction=8)`: `bullet_count=635`
- `(sub=3, instruction=8)`: `bullet_count=632`

And the three exact `0` tails stay much closer to baseline:

- `(sub=1, instruction=8)`: `bullet_count=153`
- `(sub=2, instruction=8)`: `bullet_count=145`
- `(sub=3, instruction=8)`: `bullet_count=170`

Representative first oracle hits:

- `(sub=1, instruction=8), -1`: `bullet-count-drift: tick 479 baseline=39 case=6`
- `(sub=1, instruction=8), 1`: `bullet-count-drift: tick 456 baseline=0 case=180`
- `(sub=2, instruction=8), -1`: `bullet-count-drift: tick 484 baseline=48 case=16`
- `(sub=2, instruction=8), 1`: `bullet-count-drift: tick 472 baseline=30 case=210`
- `(sub=3, instruction=8), -1`: `bullet-count-drift: tick 475 baseline=39 case=12`
- `(sub=3, instruction=8), 1`: `bullet-count-drift: tick 464 baseline=33 case=147`

Rebuild the tracked interesting payloads, regenerate the exact `0` separator
cases, and rerun the headless confirmation with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-shoot-interval-three-site-sign-basin-cluster/reproduce.py
```

To also drive the central `sub=2, instruction=8, shoot-interval=-1`
representative through retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-shoot-interval-three-site-sign-basin-cluster/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_s01_i0008_neg1.json`
- `payload_s01_i0008_1.json`
- `payload_s02_i0008_neg1.json`
- `payload_s02_i0008_1.json`
- `payload_s03_i0008_neg1.json`
- `payload_s03_i0008_1.json`

Current local evidence:

- source smoke campaign:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/_smoke/20260823-stage6-shoot-interval-new-sampler/campaign.json`
- hotspot summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/20260823T010443Z/summary.json`
- exact basin harvest:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/_smoke/20260823-stage6-shoot-interval-new-sampler-basin/summary.json`
- retail smoke for `sub=2, instruction=8, shoot-interval=-1`:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage6-shoot-interval-three-site-sign-basin-cluster/retail/report.json`

Why this one matters:

- it comes from the generic scalar `shoot-interval` family, not from a
  stage-specific hand patch;
- the same sign structure repeats across three adjacent Stage 6 timing sites,
  so this is cluster behavior, not one accidental outlier;
- the sampler’s weird large values collapse onto simple exact sentinels, which
  is exactly the kind of basin reduction we want for reusable findings;
- it is a good example of “interesting” semantic fuzzing without needing a
  crash: the script keeps running, but the volley topology changes sharply.

Current interpretation:

- headless: clearly interesting and reproducible;
- the local basin split is sign-sensitive: `0` is the separator, `-1`
  suppresses, `1` explodes;
- the three sites are structurally related enough that they likely come from a
  repeated or mirrored Stage 6 delayed-shot script pattern;
- this is a good transfer target for TH07/TH08 because it is generic timing
  behavior on a common opcode, not a one-off boss-only mechanism;
- retail: on August 23, 2026, the `sub=2, instruction=8, shoot-interval=-1`
  smoke reached the live Stage 6 game window under Wine, showed no Wine crash
  signature, and then stayed pixel-static for the 2.0-second progress probe
  (`0 / 786432` changed pixels), so the current retail oracle classified it as
  `game-window-static`.
