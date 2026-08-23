# Replay action-stream metamorphic equivalence

Observed on August 23, 2026.

This observation checks replay payload encodings that should expand to the same
bounded action mask stream:

- canonical bookmark re-encoding;
- zero-duration same-frame shadow bookmarks;
- same-mask run splits;
- records after the replay stage sentinel;
- input-row and stage-prefix padding changes;
- header display metadata changes;
- header key re-obfuscation.

The current evidence covers:

- synthetic Stage 6: `9/9` equivalent;
- `fairysvoice-th6-001.rpy` Stage 4: `13/13` equivalent;
- `gensokyo-th6-804.rpy` Stage 6: `13/13` equivalent.

Total: `35/35` relation holds, with no runtime trace/state drift.

One important oracle detail came out of this: replay action streams may end
before the requested bound, and the bounded-equivalence oracle must compare
after zero-padding the shorter stream. Without that normalization, canonical
bookmark re-encoding can look like a false action-length drift when the omitted
tail is all zero input.

## Reproduce

Quick synthetic check:

```sh
PYTHONPATH=src python3 findings/semantic/replay-action-stream-metamorphic-equivalence/reproduce.py
```

Current local evidence:

- `artifacts/checks/replay-metamorphic-stage6-20260823/campaign.json`
- `artifacts/checks/replay-metamorphic-public-fairysvoice001-stage4-20260823/campaign.json`
- `artifacts/checks/replay-metamorphic-public-gensokyo804-stage6-20260823/campaign.json`
