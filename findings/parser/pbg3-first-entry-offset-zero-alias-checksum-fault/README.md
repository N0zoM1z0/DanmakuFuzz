# PBG3 `first-entry-offset-zero` alias checksum fault

Observed on August 22, 2026.

This finding comes from the PBG3 parser lane. Forcing the first archive entry,
`stg1bg.anm`, to use `data_offset=0` still produces a `131`-entry archive that
parses cleanly, but first entry extraction fails with a deterministic checksum
fault:

- `classification=extract-error`
- `error_type=Pbg3Error`
- `error_message=PBG3 checksum mismatch for stg1bg.anm: 0x1cc != 0x127c1`
- `extracted_before_failure.count=0`

The interesting part is that this is not the same story as
[pbg3-first-entry-checksum-zero](../pbg3-first-entry-checksum-zero/README.md):

- the stored checksum field is unchanged at the retail value `0x127c1`;
- the declared uncompressed size is also unchanged at `2100`;
- only the table's `data_offset` field is changed, from `13` down to `0`.

So the parser still accepts the archive layout, but extraction now reads from
the start of the archive header instead of the original compressed payload
region. That aliasing changes the checksum over consumed bytes to `0x1cc`,
which then trips the checksum guard against the unchanged retail value
`0x127c1`.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-first-entry-offset-zero-alias-checksum-fault/reproduce.py
```

Like the other PBG3 findings, this one stays recipe-backed instead of tracking
the multi-megabyte mutated archive blob in Git.

Current local evidence:

- full campaign summary:
  `artifacts/parser-pbg3/20260822T-full-a/campaign.json`
- per-case result:
  `artifacts/parser-pbg3/20260822T-full-a/0011-first-entry-offset-zero/result.json`
- standalone reproduction summary:
  `artifacts/findings/parser-pbg3-first-entry-offset-zero-alias-checksum-fault/summary.json`

Why this one matters:

- it is a pure table-field aliasing bug shape, not a checksum-field mutation;
- it shows that accepted archive metadata can redirect extraction into the
  header region without being rejected during top-level parse;
- it complements the other first-entry parser findings with a new failure class:
  checksum fault by source aliasing rather than by direct checksum corruption.
