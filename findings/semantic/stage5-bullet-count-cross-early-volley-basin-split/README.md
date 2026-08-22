# Stage 5 cross-field `bullet-count` early-volley basin split

Observed on August 22, 2026.

This finding comes from the generic `bullet-count-cross` exploration lane on
`ecldata5.ecl`. At `(sub=0, instruction=11)`, opcode `69` originally uses
`bullet-count1=40` and `bullet-count2=1`.

Six exact rebuilt cross-field values were rechecked from the widened generic
grid:

- `(-80, -2)`
- `(-24, -63)`
- `(1, 16)`
- `(80, 2)`
- `(104, 65)`
- `(320, 8)`

All six are interesting, but they do not collapse into one “weird value =>
same weird behavior” basin. Instead, under the ordinary 600-tick Stage 5
practice baseline, the site fractures into four stable early-volley sinks at
the same first divergence point:

- low shared basin:
  `(-80, -2)` and `(-24, -63)` both land on a 2-bullet sink;
- high shared basin:
  `(104, 65)` and `(320, 8)` both land on a 640-bullet sink;
- one shoulder:
  `(1, 16)` lands on a 32-bullet sink;
- another shoulder:
  `(80, 2)` lands on a 320-bullet sink.

All four basins first diverge at tick `510`, with the first differing field
being only `bullet_count`. At that sink:

- `enemy_count` is still `2`;
- `score` is still `1130`;
- `ecl_timeline.next_time` is still `690`;
- the enemy roster is otherwise the same.

So this site is not immediately warping control flow or freezing the stage.
It is splitting one live volley scheduler site into multiple reproducible
bullet-layout basins while the surrounding stage state still looks aligned.

This matters because the same Stage 5 site already has another documented
failure shape:

- [stage5-bullet-count-cross-24-64-tail-extension](../stage5-bullet-count-cross-24-64-tail-extension/README.md)

That older finding shows the same opcode site stretching the late Stage 5 tail
past the retail baseline. This new finding shows that before that tail story,
the site already has at least four distinct early-volley semantic basins.

Rebuild the exact payloads from the local Stage 5 seed and rerun the headless
differential checks with:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-bullet-count-cross-early-volley-basin-split/reproduce.py
```

To also drive one shared-basin representative through retail Practice Stage 5
under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage5-bullet-count-cross-early-volley-basin-split/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count_cross_neg80_neg2.json`
- `payload_bullet_count_cross_neg24_neg63.json`
- `payload_bullet_count_cross_1_16.json`
- `payload_bullet_count_cross_80_2.json`
- `payload_bullet_count_cross_104_65.json`
- `payload_bullet_count_cross_320_8.json`

Current local evidence:

- source exploration grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exploration-grid/20260822T-core-grid-e/summary.json`
- hotspot summary for that grid:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/20260822T-core-grid-e/summary.json`
- explicit 600-tick trace grouping for these six representatives:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-trace-basins/20260822T-stage5-bullet-count-cross-grid-e-600-b/summary.json`
- longer exact rerun sweep:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-exact-rerun/20260822T-stage5-bullet-count-cross-grid-e-a/report.json`

Why this one matters:

- it is a generic paired-count result, not a Stage 5-only hand patch;
- two negative pairs, two large positive pairs, and two shoulders do not all
  collapse into one outcome;
- the split happens before the stage timeline itself visibly drifts, which is
  exactly the kind of “interesting semantics first, crash later if ever” case
  we want;
- this style of basin analysis should transfer cleanly to TH07/TH08.

Current interpretation:

- headless: clearly interesting and reproducible;
- the important shape is the four-way split at one reusable opcode site;
- retail: not rerun yet from this finding directory, but the reproducer is
  ready to do a Wine confirmation on demand.
