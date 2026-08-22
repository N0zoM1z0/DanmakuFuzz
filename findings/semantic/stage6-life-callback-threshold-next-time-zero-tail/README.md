# Stage 6 `life-callback-threshold=8389708` late `next_time=0` tail

Observed on August 22, 2026.

This finding tracks a stable late Stage 6 scheduler corruption that came out of
the boss-oriented semantic lane after tightening override-path hygiene.
On `ecldata6.ecl`, the `life-callback-threshold` site at
`(sub=9, instruction=38)` originally uses opcode `113` with value `1100`.
Rebuilding that exact payload with value `8389708` now produces one clean,
repeatable tail drift:

- the baseline finishes the `1800`-tick headless run with
  `ecl_timeline.next_time=1784`;
- the rebuilt payload finishes the same run with `ecl_timeline.next_time=0`;
- the first raw timeline divergence appears at tick `1733`;
- the current semantic oracle reports the drift as
  `tick 1748 ecl_timeline.next_time baseline=1784 case=0`.

Importantly, this README is not claiming the older `next_time=32679` artifact
as a stable result. That earlier observation turned out to depend on the
override directory path itself. After switching runtime execution to a fixed
active override staging root, the stable replay-equivalent result is the
`next_time=0` tail captured here.

Rebuild the exact payload from the local baseline corpus and rerun the stable
headless check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-life-callback-threshold-next-time-zero-tail/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-life-callback-threshold-next-time-zero-tail/reproduce.py \
  --retail
```

Tracked compact payload reconstruction patch:

- `payload_patch.json`

Current local evidence:

- source boss exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-boss-grid-a/summary.json`
- original source case that first exposed this site:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-boss-grid-a/tasks/0009-ecldata6-rs0/0007-life-callback-threshold-sampled-8389708-s09-i0038/result.json`
- site-level exact-value sweep before the override-path hygiene fix:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-site-basins/20260822T-stage6-lifecb-a/summary.json`
- dedicated finding rerun with the fixed active-override staging path:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage6-life-callback-threshold-next-time-zero-tail/summary.json`

Why this one matters:

- it preserves a real boss-profile case instead of losing it after discovering
  the original artifact-path sensitivity;
- it is a pure scheduler/timeline corruption, not a crash-only oracle;
- the exact rebuilt payload now reproduces one byte-identical trace across
  different worker roots under the fixed active-override staging path.

Current interpretation:

- headless: clearly interesting and reproducible under the current stable
  override staging path;
- the visible gameplay state at tick `1800` is unchanged except for the
  timeline tail, which makes this a good “quiet corruption” representative;
- retail: optional only for now; the headless reproducer is the main proof;
- note: the interesting claim here is specifically the stable `next_time=0`
  tail. The older `next_time=32679` artifact was useful for diagnosing the
  harness, but it is no longer treated as a trustworthy semantic finding.
