# Parser lane

Planned native harness targets:

- `pbg3_archive`
- `replay_parser`
- `stage_std_loader`

The lane is intentionally separate from headless orchestration. Parser fuzzing
should stay small, sanitizer-friendly, and directly attributable to a specific
loader or decoder.

## Current entrypoints

First-pass parser-lane CLIs now exist under `src/danmakufuzz/parser/`:

- `python3 -m danmakufuzz.parser.pbg3_archive --archive ...`
- `python3 -m danmakufuzz.parser.pbg3_campaign --archive ...`
- `python3 -m danmakufuzz.parser.replay --input ...`
- `python3 -m danmakufuzz.parser.stage_std --archive ... --entry stage1.std`

These are lightweight format validators and walkers, not yet native
sanitizer-backed fuzz harnesses.

The current parser-side mutation lane starts with PBG3 archive triage:

```sh
PYTHONPATH=src python3 -m danmakufuzz.parser.pbg3_campaign \
  --archive reference/retail/game/th06/紅魔郷ST.DAT
```

That campaign emits malformed or behavior-changing PBG3 seeds into an ignored
artifact tree and classifies each case as `parse-error`, `extract-error`, or
`accepted`.
