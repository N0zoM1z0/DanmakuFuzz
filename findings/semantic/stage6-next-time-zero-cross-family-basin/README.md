# Stage 6 cross-family `next_time=0` basin

Observed on August 22, 2026.

This finding upgrades one quiet Stage 6 scheduler drift into a full
cross-family basin. After fixing the semantic harness so the active override is
staged through one stable runtime path, the boss-oriented generic sweep on
`ecldata6.ecl` revealed a sharp result:

- Stage 2 boss profile: `0 / 32` interesting
- Stage 4 boss profile: `0 / 32` interesting
- Stage 6 boss profile: `32 / 32` interesting

Those 32 interesting Stage 6 cases are not merely similar. Across four
different mutator families, they all collapse into one exact headless trace:

- shared trace SHA-256:
  `3cc327cbf73a4fb653bd5441add8e71ebc07ca8d9972ac245711fb720690fa53`
- first normalized divergence tick: `1733`
- first normalized divergence keys: `["ecl_timeline"]`
- shared sink signature:
  `ac73ed0fdf15cb866a9da4fa3fc262b12900567dd4e40ed409c403a9d6af52a1`
- by tick `1800`, the baseline still reports `ecl_timeline.next_time=1784`,
  while the basin trace reports `ecl_timeline.next_time=0`

The four tracked representative families are:

- `boss-life-count`: `(sub=8, instruction=8)` mutates `0 -> 72`
- `timer-callback-threshold`: `(sub=9, instruction=13)` mutates `1020 -> 4080`
- `life-callback-threshold`: `(sub=9, instruction=20)` mutates `750 -> 2798`
- `boss-timer`: `(sub=14, instruction=4)` mutates `0 -> 64`

The broader fixed-staging grid counts behind this basin are:

- `boss-life-count`: `8` exact cases
- `timer-callback-threshold`: `4` exact cases
- `life-callback-threshold`: `16` exact cases
- `boss-timer`: `4` exact cases

Rebuild the four representative payloads from the local baseline corpus and
rerun the shared-basin check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-next-time-zero-cross-family-basin/reproduce.py
```

To also drive the `boss-life-count-72` representative through retail Practice
Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-next-time-zero-cross-family-basin/reproduce.py \
  --retail
```

Tracked compact payload reconstruction patches:

- `payload_boss_life_count_72.json`
- `payload_timer_callback_threshold_4080.json`
- `payload_life_callback_threshold_2798.json`
- `payload_boss_timer_64.json`

Current local evidence:

- fixed-staging boss exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-boss-grid-b/summary.json`
- single-family Stage 6 representative finding:
  `/home/yann/yann/touhou/DanmakuFuzz/findings/semantic/stage6-life-callback-threshold-next-time-zero-tail/README.md`
- dedicated cross-family reproducer rerun:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage6-next-time-zero-cross-family-basin/summary.json`
- August 22, 2026 retail smoke for `boss-life-count-72`:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage6-next-time-zero-cross-family-basin/retail/report.json`

Why this one matters:

- it is fully generic-lane evidence rather than a hand-mined one-off patch;
- it shows a broad Stage 6 boss scheduler weakness instead of a single family
  quirk;
- it is a quiet semantic corruption case: score, enemy count, items, bullets,
  and late script state all stay aligned while the timeline tail silently
  collapses from `1784` to `0`;
- it gives one strict shared-trace sink that later TH07/08 boss-lane ports can
  try to rediscover directly.

Current interpretation:

- headless: clearly interesting and reproducible;
- this is a true cross-family basin, not just a `life-callback-threshold`
  artifact;
- the earlier path-sensitive `next_time=32679` observation was useful for
  diagnosing the harness, but the stable semantic result tracked here is the
  shared `next_time=0` sink;
- retail: on August 22, 2026, the `boss-life-count-72` smoke reached
  `game-window-live`, changed `149340 / 786432` pixels during the progress
  probe (`0.1898956298828125`), and did not produce a Wine crash signature;
- the main proof is still the exact shared headless trace rather than the
  retail smoke.
