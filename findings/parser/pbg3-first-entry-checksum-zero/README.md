# PBG3 `first-entry-checksum-zero`

Observed on August 22, 2026.

This finding comes from the PBG3 parser lane. Zeroing the checksum field for the
first archive entry preserves top-level parsing but forces a deterministic
failure on first extraction:

- archive header still parses successfully;
- entry table still enumerates all `131` entries in `紅魔郷ST.DAT`;
- extracting the first entry fails with a checksum mismatch.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-first-entry-checksum-zero/reproduce.py
```

This finding stays recipe-backed instead of tracking an exact mutated archive
blob or archive patch in Git: the deterministic mutation is small and stable,
while a byte-exact patch against the rebuilt archive would be close to a whole
archive replacement.

Current local evidence:

- campaign summary:
  `artifacts/tmp-pbg3-campaign-deep-smoke/campaign.json`
- per-case result:
  `artifacts/tmp-pbg3-campaign-deep-smoke/0002-first-entry-checksum-zero/result.json`

Why this one matters:

- it reaches past header validation into entry extraction;
- it is a clean parser-side failure that does not depend on headless/runtime
  orchestration;
- it is easy to rebuild from the retail archive without storing the mutated
  archive blob in Git.
