# PBG3 `first-entry-empty-payload` acceptance

Observed on August 22, 2026.

This finding comes from the PBG3 parser lane. Rebuilding the archive with the
first entry payload replaced by empty bytes still produces a `131`-entry
archive the parser accepts cleanly, but one retail payload is silently zeroed:

- `classification=accepted`
- `entry_count=131`
- there are no missing or extra parsed entries;
- exactly one changed entry remains: `stg1bg.anm`;
- its extracted size becomes `0`;
- its extracted SHA-256 becomes the empty-payload digest
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
- the next entry, `stg1bg.png`, still extracts byte-for-byte equal to
  baseline.

This is distinct from the nearby accepted PBG3 findings:

- [pbg3-entry-count-one-truncation-acceptance](../pbg3-entry-count-one-truncation-acceptance/README.md)
  removes `130` entries from the visible archive;
- [pbg3-append-garbage-equivalent-acceptance](../pbg3-append-garbage-equivalent-acceptance/README.md)
  leaves the archive fully equivalent;
- this finding preserves the full archive view but zeroes one concrete payload.

So this gives the parser lane another accepted-but-materially-changed shape:

- accepted archive metadata;
- accepted extraction of the whole archive surface;
- one silently replaced entry payload.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-first-entry-empty-payload-acceptance/reproduce.py
```

Like the other PBG3 findings, this one stays recipe-backed instead of tracking
the multi-megabyte mutated archive blob in Git.

Current local evidence:

- full campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-pbg3/20260822T-full-a/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-pbg3/20260822T-full-a/0014-first-entry-empty-payload/result.json`
- standalone reproduction summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/parser-pbg3-first-entry-empty-payload-acceptance/summary.json`

Why this one matters:

- it is accepted rather than rejected, so downstream consumers would see a
  plausible-looking archive layout;
- unlike the truncation case, it preserves the full `131`-entry view while
  changing one concrete asset payload;
- it rounds out the PBG3 accepted-case family with a “single-entry zeroed”
  shape.
