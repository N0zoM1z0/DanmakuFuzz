# Parser lane

Planned native harness targets:

- `pbg3_archive`
- `replay_parser`
- `stage_std_loader`
- `msg_dat_loader`
- `game_cfg_loader`
- `score_dat_loader`
- `anm_loader`

The lane is intentionally separate from headless orchestration. Parser fuzzing
should stay small, sanitizer-friendly, and directly attributable to a specific
loader or decoder.

## Current entrypoints

First-pass parser-lane CLIs now exist under `src/danmakufuzz/parser/`:

- `python3 -m danmakufuzz.parser.pbg3_archive --archive ...`
- `python3 -m danmakufuzz.parser.pbg3_campaign --archive ...`
- `python3 -m danmakufuzz.parser.replay --input ...`
- `python3 -m danmakufuzz.parser.replay_campaign`
- `python3 -m danmakufuzz.parser.stage_std --archive ... --entry stage1.std`
- `python3 -m danmakufuzz.parser.stage_std_campaign --archive ... --entry stage1.std`
- `python3 -m danmakufuzz.parser.msg_dat --archive ... --entry msg1.dat`
- `python3 -m danmakufuzz.parser.msg_dat_campaign --archive ... --entry msg1.dat`
- `python3 -m danmakufuzz.parser.game_cfg_campaign`
- `python3 -m danmakufuzz.parser.score_dat_campaign`
- `python3 -m danmakufuzz.parser.anm_campaign --archive ... --entry stg1bg.anm`

These are lightweight format validators and walkers, not yet native
sanitizer-backed fuzz harnesses.

Current parser-side mutation lanes:

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.pbg3_campaign \
  --archive reference/retail/game/th06/紅魔郷ST.DAT
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.replay_campaign
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.stage_std_campaign \
  --archive reference/retail/game/th06/紅魔郷ST.DAT \
  --entry stage1.std
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.msg_dat_campaign \
  --archive reference/retail/game/th06/紅魔郷ST.DAT \
  --entry msg1.dat
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.game_cfg_campaign
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.score_dat_campaign
```

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.anm_campaign \
  --archive reference/retail/game/th06/紅魔郷ST.DAT \
  --entry stg1bg.anm
```

These campaigns emit malformed or behavior-changing seeds into ignored artifact
trees. PBG3 classifies each case as `parse-error`, `extract-error`, or
`accepted`; replay, stage `.std`, message `.dat`, cfg, score, and ANM lanes
classify each case as rejected/fallback/accepted depending on the format, then
flag accepted cases that materially diverge from baseline.

The parser lane should remain binary-first and source-less. The current TH06
formats are the proving ground, not the final scope.
