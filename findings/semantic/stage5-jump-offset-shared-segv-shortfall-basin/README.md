# Stage 5 shared `jump-offset` SIGSEGV shortfall basin

Observed on August 22, 2026.

This finding comes from the widened generic `jump-offset` exploration lane on
`ecldata5.ecl`. At `(sub=0, instruction=14)`, opcode `3` originally uses jump
offset `-224`.

Four exact rebuilt offsets already collapse into one identical crash-shaped
headless basin:

- `jump-offset=-1073742048`
- `jump-offset=252821401`
- `jump-offset=-2147483603`
- `jump-offset=-1441649695`

All four payloads reproduce the same outcome:

- the trace SHA-256 is
  `86e64cd169c20b0274e9916f370ab18c8d770e0c6a1a97730eb0e64cbe8dfa3f`;
- the run ends with `SIGSEGV`;
- the semantic lane reports the same pair of findings:
  `process-signal: SIGSEGV` and
  `trace-shortfall: tick_count=514 baseline_tick_count=600`;
- all four traces stop at tick `514` with
  `score=1220`, `enemy_count=2`, `bullet_count=80`,
  and `ecl_timeline.next_time=690`.

The fun part is where this basin branches.

The crash trace is not immediately weird. It matches the ordinary Stage 5
baseline byte for byte for its full `514` recorded rows, and then stops
exactly before tick `515`.

That matters because the same opcode site already has an older reusable
shared route-warp basin:

- [stage5-jump-offset-shared-route-warp-basin](../stage5-jump-offset-shared-route-warp-basin/README.md)

That earlier route-warp basin also stays aligned through tick `514`, but at
tick `515` it continues with `80` bullets while the ordinary baseline jumps to
`160`. This new finding shows a third branch at the same split point:

- baseline:
  continues past tick `515` and jumps to `160` bullets;
- route-warp basin:
  continues past tick `515` and stays at `80` bullets;
- crash basin:
  terminates before tick `515` and drops into a shared `SIGSEGV`.

So the same generic Stage 5 site now supports at least:

- a stable shared route-warp basin for moderate offsets;
- a stable shared crash basin for extreme offsets.

Rebuild the four triggering payloads from the local Stage 5 seed and rerun the
headless crash-basin checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-jump-offset-shared-segv-shortfall-basin/reproduce.py
```

To also drive one representative through retail Practice Stage 5 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-jump-offset-shared-segv-shortfall-basin/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_jump_offset_neg1073742048.json`
- `payload_jump_offset_252821401.json`
- `payload_jump_offset_neg2147483603.json`
- `payload_jump_offset_neg1441649695.json`

Current local evidence:

- source exploration grid:
  `artifacts/semantic-exploration-grid/20260822T-core-grid-f/summary.json`
- hotspot summary for that grid:
  `artifacts/semantic-hotspots/20260822T-core-grid-f/summary.json`
- related older shared route-warp basin:
  `findings/semantic/stage5-jump-offset-shared-route-warp-basin/README.md`

Current interpretation:

- headless: clearly interesting and reproducible;
- the important shape is the four-value shared crash basin at one generic
  `jump-offset` site;
- retail: not rerun yet from this finding directory, but the reproducer is
  ready to do a Wine confirmation on demand.
