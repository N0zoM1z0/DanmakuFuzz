# Stage 6 `bullet-count2` consecutive stall ladder

Observed on August 22, 2026.

This finding captures a Stage 6 value landscape instead of a single shared
basin. On `ecldata6.ecl`, the bullet pattern at `(sub=4, instruction=3)`
originally uses `bullet-count1=9` and `bullet-count2=1`. Four consecutive exact
`bullet-count2` values already fracture into four different stalled-progress
wedges:

- `bullet-count2=6` freezes at `game_frame=1480`
- `bullet-count2=7` freezes at `game_frame=1534`
- `bullet-count2=8` freezes at `game_frame=1555`
- `bullet-count2=9` freezes at `game_frame=1492`

All four runs:

- are generic `bullet-count2` mutations on the same site;
- trip `stalled-progress` / `stalled-frame`;
- end with `stage_vm.loaded=False` while the baseline is still advancing;
- diverge into different late-stage scheduler wedges rather than one shared
  trace or one shared frozen frame.

This is not a cross-value basin in the earlier Stage 1 / Stage 2 sense. It is a
local value ladder: four consecutive integers, four different Stage 6 wedges.

Rebuild the four triggering payloads from the local baseline corpus and rerun
the ladder check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count2-consecutive-stall-ladder/reproduce.py
```

To also drive the `bullet-count2=8` representative through retail Practice
Stage 6 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage6-bullet-count2-consecutive-stall-ladder/reproduce.py \
  --retail
```

Tracked compact payload patches:

- `payload_bullet_count2_six.json`
- `payload_bullet_count2_seven.json`
- `payload_bullet_count2_eight.json`
- `payload_bullet_count2_nine.json`

Current local evidence:

- broader Stage 6 site scan:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-site-basins/stage6-bullet-count2-s04-i0003-a/summary.json`
- focused consecutive-value scan:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-site-basins/stage6-bullet-count2-s04-i0003-b/summary.json`
- August 22, 2026 retail smoke for the `bullet-count2=8` representative:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage6-bullet-count2-consecutive-stall-ladder/retail/report.json`
- related Stage 6 `bullet-count2` item-flood basin on a different site:
  `/home/yann/yann/touhou/DanmakuFuzz/findings/semantic/stage6-bullet-count2-item-flood-basin/README.md`

Why this one matters:

- it shows that one generic Stage 6 `bullet-count2` site has a fractured local
  landscape rather than one dominant basin;
- consecutive small values already alter late-stage scheduler state in visibly
  different ways;
- the new generic mapper makes this kind of “value terrain” practical to study,
  which should transfer well to TH07/08.

Current interpretation:

- headless: clearly interesting and reproducible;
- the fun part is the ladder itself, not one isolated magic value;
- nearby values `4`, `5`, `12`, and `14` still keep the baseline scheduler
  state, so this site mixes normal drift and hard wedges inside a narrow local
  interval;
- retail: on August 22, 2026, the `bullet-count2=8` smoke reached a live game
  window under Wine, changed `149340 / 786432` pixels during the progress
  probe (`0.1898956298828125`), and did not produce a Wine crash signature;
- that retail result is still only a launch/progress smoke, not proof that the
  exact headless stall wedge also manifests in retail.
