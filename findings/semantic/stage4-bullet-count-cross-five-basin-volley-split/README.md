# Stage 4 cross-field `bullet-count` five-basin volley split

Observed on August 22, 2026.

This finding comes from the widened generic `bullet-count-cross` exploration
lane on `ecldata4.ecl`. At `(sub=1, instruction=12)`, opcode `70` originally
uses `bullet-count1=16` and `bullet-count2=1`.

Six exact rebuilt cross-field values were rechecked from the widened generic
grid:

- `(64, 4)`
- `(-155, 2)`
- `(511, 511)`
- `(32784, 5)`
- `(128, 8)`
- `(4, 0)`

All six are interesting, and unlike the older Stage 5 split, these six values
fracture into five stable basins under the ordinary 600-tick Stage 4 practice
baseline:

- shared high basin:
  `(511, 511)` and `(128, 8)` both first diverge into a `640`-bullet sink;
- shoulder basin:
  `(64, 4)` first diverges into a `512`-bullet sink;
- shoulder basin:
  `(32784, 5)` first diverges into a `10`-bullet sink;
- shoulder basin:
  `(-155, 2)` first diverges into a `4`-bullet sink;
- shoulder basin:
  `(4, 0)` first diverges into an `8`-bullet sink.

All five basins first diverge at tick `539`, with the first differing field
being only `bullet_count`. At that first split point:

- `score` is still `1230`;
- `enemy_count` is still `8`;
- `ecl_timeline.next_time` is still `1004`;
- the enemy roster is otherwise unchanged.

So this is not a control-flow warp first. It is a pure live-volley scheduler
fracture at one reusable paired-count site.

The later differential oracle does not fire until tick `554`, where the Stage 4
baseline has `96` bullets and the exact cases spread into later observed counts
of `640`, `640`, `640`, `30`, `24`, and `12`. The important shape is that the
first semantic split happens earlier and cleaner than the later headline drift.

This matters because it is a generic, portable mutation family result:

- it comes from the widened generic exploration sampler, not a hand-picked
  Stage 4 edit;
- one opcode site already supports five reproducible bullet-layout basins;
- the split happens while surrounding stage state still looks aligned, which is
  exactly the “interesting semantics first” signal we want;
- this analysis style should transfer directly to TH07 and TH08.

Rebuild the exact payloads from the local Stage 4 seed and rerun the headless
differential checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage4-bullet-count-cross-five-basin-volley-split/reproduce.py
```

To also drive one representative through retail Practice Stage 4 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage4-bullet-count-cross-five-basin-volley-split/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count_cross_64_4.json`
- `payload_bullet_count_cross_neg155_2.json`
- `payload_bullet_count_cross_511_511.json`
- `payload_bullet_count_cross_32784_5.json`
- `payload_bullet_count_cross_128_8.json`
- `payload_bullet_count_cross_4_0.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-core-grid-f/summary.json`
- hotspot summary for that grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/20260822T-core-grid-f/summary.json`
- explicit 600-tick trace grouping for these six representatives:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/20260822T-stage4-bullet-count-cross-grid-f-a/summary.json`

Current interpretation:

- headless: clearly interesting and reproducible;
- the important shape is the five-way split at one generic opcode site;
- retail: not rerun yet from this finding directory, but the reproducer is
  ready to do a Wine confirmation on demand.
