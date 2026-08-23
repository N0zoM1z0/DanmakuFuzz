# Stage 2 second-site cross-value `shoot-interval` tail fork

Observed on August 23, 2026.

This finding captures a second generic Stage 2 `shoot-interval` site with a
different value landscape from the earlier `stage2-shoot-interval-cross-value-tail-split`
finding. On `ecldata2.ecl`, opcode `77` at `(sub=1, instruction=9)` originally
uses `shoot-interval=180`. Exact rebuilt values split into two late-tail basins:

- `shoot-interval=181` lands in a `1212 / 1214` tail wedge.
- `shoot-interval=1812277` collapses into the same `1212` basin as `181`.
- `shoot-interval=1` forks into a neighboring `1214` basin with a much larger
  bullet surge and score jump.

The shared `1212` basin matters because it is reached by both:

- a one-tick increment from retail (`180 -> 181`);
- a huge positive value (`1812277`).

By tick `1800`, the two basin shapes look like this:

- `181` / `1812277` tail:
  - `game_frame=1212`
  - `score=481910`
  - `bullet_count=23`
  - `ecl_timeline.next_time=1214`
- `1` tail:
  - `game_frame=1214`
  - `score=605220`
  - `bullet_count=281`
  - `ecl_timeline.next_time=1214`

Rebuild the exact payloads from the local baseline corpus and rerun the
headless confirmation with:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-shoot-interval-second-site-cross-value-tail-fork/reproduce.py
```

To also drive the more visible `shoot-interval=1` representative through retail
Practice Stage 2 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-shoot-interval-second-site-cross-value-tail-fork/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_shoot_interval_1.json`
- `payload_shoot_interval_181.json`
- `payload_shoot_interval_1812277.json`

Current local evidence:

- exact basin harvest:
  `artifacts/semantic-basin-harvest/20260823T-stage2-shoot-interval-site-a/stage2-ecldata2-shoot-interval-s01-i0009/summary.json`
- harvest driver summary:
  `artifacts/semantic-basin-harvest/20260823T-stage2-shoot-interval-site-a/summary.json`
- retail launch/progress smoke for the `shoot-interval=1` representative:
  `artifacts/findings/semantic-stage2-shoot-interval-second-site-cross-value-tail-fork/retail/report.json`
- earlier sibling finding on another Stage 2 `shoot-interval` site:
  `findings/semantic/stage2-shoot-interval-cross-value-tail-split/README.md`

Why this one matters:

- it is a second generic Stage 2 `shoot-interval` site, so the Stage 2 timing
  landscape is broader than a single hotspot;
- `180 -> 181` is already enough to fall into the `1212` tail basin;
- a huge positive value (`1812277`) collapses back onto that same basin, which
  is exactly the kind of weird old-VM equivalence class we want;
- `shoot-interval=1` does not join that basin and instead forks into a nearby
  `1214` tail with `281` bullets still active at tick `1800`.

Current interpretation:

- headless: clearly interesting and reproducible;
- this is not just another bullet-flood result: it is a cross-value basin fork
  on a different generic Stage 2 timing site;
- retail: on August 23, 2026, the `shoot-interval=1` smoke reached a live game
  window under Wine, did not hit a Wine crash signature, and then stayed
  pixel-static for the 2-second progress probe (`0 / 786432` pixels changed),
  so the retail oracle classified it as `game-window-static`.
