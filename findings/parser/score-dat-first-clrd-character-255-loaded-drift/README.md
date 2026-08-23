# `score.dat` `first-clrd-character-255` loaded-drift

Observed on August 23, 2026.

This finding comes from the `score.dat` parser lane over the retail
`reference/retail/game/th06/score.dat` seed.

The mutation keeps the outer `score.dat` envelope valid:

- checksum still matches;
- `data_offset` and `file_len` stay sane;
- the loader still classifies the file as `loaded`, not fallback.

But the first `CLRD` record has its `characterShotType` forced to `255`, so the
semantic record walk drifts:

- baseline: `valid_clrd_records=4`, `invalid_clrd_records=0`
- mutated: `valid_clrd_records=3`, `invalid_clrd_records=1`

Everything else in the top-level walk stays intact:

- `record_count=74`
- histogram still stays `TH6K=1`, `CLRD=4`, `CATK=64`, `PSCR=5`
- `walk_stop_reason=end-of-file`

So this is not “the whole score file is rejected”. It is a cleaner case:
`score.dat` still loads, the wrapper checksum is still valid, but one semantic
record silently drops out of the accepted `CLRD` set.

Reproduce it with:

```sh
PYTHONPATH=src python3 findings/parser/score-dat-first-clrd-character-255-loaded-drift/reproduce.py
```

Payload portability is kept as a deterministic recipe rather than a committed
binary blob:

- [payload_recipe.json](/home/yann/yann/touhou/DanmakuFuzz/findings/parser/score-dat-first-clrd-character-255-loaded-drift/payload_recipe.json)

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-score-dat/20260823T022534Z/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-score-dat/20260823T022534Z/0009-first-clrd-character-255/result.json`
- standalone reproduction summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/parser-score-dat-first-clrd-character-255-loaded-drift/summary.json`

Why this one matters:

- it is a binary-first case and does not require source to discover;
- it survives the outer file checksum, so naive corruption checks do not stop it;
- it shows the exact class of finding we want for later source-less titles:
  accepted container, wrong semantic state.
