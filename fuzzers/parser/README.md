# Parser lane

This lane is the file-format side of DanmakuFuzz. It stays intentionally
separate from headless runtime orchestration so parser behavior can be
attributed to one loader, one archive format, or one decoder at a time.

Core targets:

- `pbg3_archive`
- `replay_parser`
- `stage_std_loader`
- `msg_dat_loader`
- `game_cfg_loader`
- `score_dat_loader`
- `anm_loader`

Parser fuzzing should stay small, sanitizer-friendly where possible, and
directly attributable to a specific loader or decoder.

## Campaign map

Parser CLIs live under `src/danmakufuzz/parser/`:

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

These are lightweight format validators and mutation campaigns, not full native
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
trees. Most parser artifacts are disposable and can be pruned with
`scripts/prune_artifacts.sh` once the reviewed findings have been written down.

PBG3 classifies each case as `parse-error`, `extract-error`, or
`accepted`. Accepted PBG3 cases that are byte-for-byte equivalent after
extraction are now `FORMAT_CHARACTERIZATION` observations rather than
interesting bug candidates; accepted-with-drift and extraction errors remain
review targets. Replay, stage `.std`, message `.dat`, cfg, score, and ANM
lanes classify each case as rejected/fallback/accepted depending on the
format, then flag accepted cases that materially diverge from baseline.

The parser lane should remain binary-first and source-less. TH06 is the proving
ground, not the final scope.
