# ANM `first-sprite-offset-zero` structural acceptance

Observed on August 23, 2026.

This finding comes from the ANM parser lane on the retail `stg1enm.anm` seed
inside `紅魔郷ST.DAT`.

The mutation forces the first sprite-table entry down to offset `0`.

The parser still accepts the file:

- classification stays `accepted`;
- script table and script walk stay intact;
- `total_instructions=50` and `invalid_jump_targets=0` do not change.

But the first sprite is no longer decoded from the sprite region. It aliases
the file header and turns into garbage-y sprite data:

- baseline first sprite offset: `288`
- mutated first sprite offset: `0`
- mutated first sprite id: `24`
- mutated first sprite coordinates/sizes become tiny header-derived floats

So this is a clean “accepted structural alias” case: the ANM still looks
loadable at the container level, but one sprite entry is silently rebound to
the header and decoded as nonsense.

Reproduce it with:

```sh
PYTHONPATH=src python3 findings/parser/anm-first-sprite-offset-zero-structural-acceptance/reproduce.py
```

Payload portability is kept as a deterministic recipe:

- [payload_recipe.json](findings/parser/anm-first-sprite-offset-zero-structural-acceptance/payload_recipe.json)

Current local evidence:

- campaign summary:
  `artifacts/parser-anm/20260823T022546Z/campaign.json`
- per-case result:
  `artifacts/parser-anm/20260823T022546Z/0010-first-sprite-offset-zero/result.json`
- standalone reproduction summary:
  `artifacts/findings/parser-anm-first-sprite-offset-zero-structural-acceptance/summary.json`

Why this one matters:

- it is source-less and archive-entry-local: exactly the style we need for
  later titles like TH08;
- it is accepted, not rejected, so downstream runtime code would see a
  plausible ANM with one silently poisoned sprite;
- it points at the ANM table/offset layer as a likely place for later runtime
  resource-override fuzzing.
