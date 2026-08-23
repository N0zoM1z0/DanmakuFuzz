# Stage 2 `bullet-count2` `time=1212` wedge basin

Observed on August 22, 2026.

This finding upgrades the narrower sampled Stage 2 `bullet-count2=-12208722`
result into a cross-value basin. On `ecldata2.ecl`, the bullet pattern at
`(sub=2, instruction=9)` originally uses `bullet-count1=10` and
`bullet-count2=2`. Multiple exact reconstructed `bullet-count2` values now
reproduce the same frozen Stage 2 scheduler state:

- `bullet-count2=1`
- `bullet-count2=0`
- `bullet-count2=-12208722`
- `bullet-count2=2147483596`

Under headless replay, those four payloads collapse into one identical trace:

- trace SHA-256:
  `83372232558f688fb187bcfe49f09e7fb51bba9ae24f4bdbc4d5040f47e74c5b`
- `game_frame` freezes at `1212` from tick `1212` through tick `1800`;
- the first `stage_vm` and `ecl_timeline` drift both appear at tick `1213`;
- all four runs end with `stage_vm.loaded=False`,
  `stage_vm.script_time=1212`, and `ecl_timeline.next_time=1214`.

Follow-up exact-value mapping on August 22, 2026 showed that this site is
broader than one strict replay-equivalent basin:

- at least `11` tested values converge on the shared `1212` trace recorded in
  this directory;
- additional nearby values such as `5` and `8` still land in the same
  `game_frame=1212` / `script_time=1212` scheduler wedge, but with different
  strict traces and different resource tails;
- other values such as `3`, `16`, `32`, `127`, `255`, and `1024` fall into
  neighboring wedges with their own frozen script times.

This directory intentionally tracks only the strict shared-trace subgroup, not
every value that reaches the broader `1212` scheduler wedge.

Rebuild the four triggering payloads from the local baseline corpus and rerun
the shared-wedge check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-bullet-count2-time-1212-wedge-basin/reproduce.py
```

To also drive the closest representative through retail Practice Stage 2 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-bullet-count2-time-1212-wedge-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count2_one.json`
- `payload_bullet_count2_zero.json`
- `payload_bullet_count2_neg12208722.json`
- `payload_bullet_count2_2147483596.json`

Current local evidence:

- widened `bullet-count2` family sweep:
  `artifacts/semantic-family-sweep/20260822T-bullet-count2-explore-a/summary.json`
- sampled source case:
  `artifacts/semantic-family-sweep/20260822T-bullet-count2-explore-a/ecldata2/0009-bullet-count2-sampled-neg12208722-s02-i0009/result.json`
- exact-value basin probe:
  `artifacts/tmp-stage2-bullet-count2-basin-probe-a/probe-summary.json`
- standardized site-basin mapper summary:
  `artifacts/semantic-site-basins/stage2-bullet-count2-s02-i0009-a/summary.json`

Why this one matters:

- it shows a one-step decrement from the retail value (`2 -> 1`) is already
  enough to wedge Stage 2;
- the same site also accepts negative and huge positive values that collapse
  into the exact same frozen trace;
- it reveals a more interesting structure than a one-off magic number: this
  Stage 2 site splits into several neighboring scheduler wedges.

Current interpretation:

- headless: clearly interesting and reproducible;
- this directory captures the shared `time=1212` basin, not the whole site;
- retail: not rerun yet from this exact finding directory, but the reproducer
  is ready to drive the `bullet-count2=1` representative through Practice
  Stage 2.
