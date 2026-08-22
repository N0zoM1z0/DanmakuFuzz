# Stage 6 cross-field `bullet-count` five-basin early-volley split

Observed on August 22, 2026.

This finding comes from the widened generic `bullet-count-cross` exploration
lane on `ecldata6.ecl`. At `(sub=3, instruction=3)`, opcode `75` originally
uses `bullet-count1=9` and `bullet-count2=1`.

Six exact rebuilt cross-field values were rechecked from the widened generic
grid:

- `(1, 0)`
- `(5, 2049)`
- `(13, 5)`
- `(10715, 29)`
- `(18, 2)`
- `(36, 4)`

All six are interesting, and they fracture into five stable early-volley
basins under the ordinary 600-tick Stage 6 practice baseline:

- shared high basin:
  `(5, 2049)` and `(10715, 29)` both first diverge into a `640`-bullet sink;
- shoulder basin:
  `(36, 4)` first diverges into a `156`-bullet sink;
- shoulder basin:
  `(13, 5)` first diverges into a `77`-bullet sink;
- shoulder basin:
  `(18, 2)` first diverges into a `48`-bullet sink;
- shoulder basin:
  `(1, 0)` first diverges into a `13`-bullet sink.

All five basins first diverge at tick `460`, with the first differing field
being only `bullet_count`. At that split point:

- baseline still has only `21` bullets;
- `score` is still `60`;
- `enemy_count` is still `3`;
- `ecl_timeline.next_time` is still `464`;
- the enemy roster is otherwise unchanged.

So this site is not immediately warping control flow or scheduler progress.
It is a pure early-volley fracture at one reusable paired-count site.

The later differential oracle does not fire at one shared time. Instead, the
headline drift lands in several later shoulders:

- `(1, 0)` first trips `bullet-count-drift` at tick `475`
  (`baseline=39`, `case=13`);
- `(5, 2049)` and `(10715, 29)` first trip it at tick `475`
  (`baseline=39`, `case=299`);
- `(13, 5)` first trips it at tick `490`
  (`baseline=48`, `case=131`);
- `(36, 4)` first trips it at tick `490`
  (`baseline=48`, `case=257`);
- `(18, 2)` first trips it at tick `503`
  (`baseline=60`, `case=133`).

This matters because it is a portable generic paired-count result:

- it comes from the widened generic exploration sampler, not a Stage 6-only
  hand patch;
- one opcode site already supports five reproducible bullet-layout basins;
- very small positive pairs and much larger asymmetrical pairs can still
  collide into one shared high basin;
- the split happens while surrounding stage state still looks aligned, which is
  exactly the kind of semantic pathology we want to carry to TH07/TH08.

Rebuild the exact payloads from the local Stage 6 seed and rerun the headless
differential checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count-cross-five-basin-early-volley-split/reproduce.py
```

To also drive one moderate representative through retail Practice Stage 6 under
Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count-cross-five-basin-early-volley-split/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count_cross_1_0.json`
- `payload_bullet_count_cross_5_2049.json`
- `payload_bullet_count_cross_13_5.json`
- `payload_bullet_count_cross_10715_29.json`
- `payload_bullet_count_cross_18_2.json`
- `payload_bullet_count_cross_36_4.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-core-grid-f/summary.json`
- hotspot summary for that grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/20260822T-core-grid-f/summary.json`
- explicit 600-tick trace grouping for these six representatives:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/20260822T-stage6-bullet-count-cross-s03-i0003-a/summary.json`

Current interpretation:

- headless: clearly interesting and reproducible;
- the important shape is the five-way early-volley split at one generic opcode
  site;
- retail: not rerun yet from this finding directory, but the reproducer is
  ready to do a Wine confirmation on demand.
