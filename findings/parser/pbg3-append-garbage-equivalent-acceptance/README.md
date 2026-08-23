# PBG3 `append-garbage-256` equivalent acceptance

Observed on August 22, 2026.

This format observation comes from the PBG3 parser lane. Appending `256` bytes
of trailing garbage to the retail `紅魔郷ST.DAT` archive still produces an
archive the parser accepts as fully equivalent to baseline:

- archive header still parses successfully;
- entry table still enumerates all `131` entries;
- there are no missing or extra parsed entries;
- every extracted entry payload hash still matches the retail baseline;
- the extra `256` trailing bytes are ignored by the parser view.

This is not a crash bug and is no longer counted as an interesting bug
candidate by the PBG3 campaign. It is a clean "accepted and equivalent despite
extra junk" parser case, which is useful for understanding what the parser
treats as canonical versus ignorable.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-append-garbage-equivalent-acceptance/reproduce.py
```

Like the other PBG3 findings, this one stays recipe-backed instead of tracking
the full mutated archive blob in Git: the mutation is deterministic and tiny,
while the rebuilt archive is multi-megabyte.

Current local evidence:

- smoke campaign summary:
  `artifacts/parser-pbg3/20260822T-smoke-a/campaign.json`
- per-case result:
  `artifacts/parser-pbg3/20260822T-smoke-a/0003-append-garbage-256/result.json`
- standalone reproduction summary:
  `artifacts/findings/parser-pbg3-append-garbage-equivalent-acceptance/summary.json`

Why this one matters:

- it is accepted rather than rejected, so downstream code would see a normal
  looking archive;
- the parser treats the mutated archive as fully equivalent, which means
  trailing bytes are outside the parser's semantic model;
- it gives the parser lane a format-characterization observation separate from
  truncation-accept and extraction-time checksum fault bug candidates.
