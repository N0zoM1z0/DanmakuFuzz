# PBG3 `first-entry-size-inflate` mismatch

Observed on August 22, 2026.

This finding comes from the PBG3 parser lane. Inflating the declared
uncompressed size of the first archive entry, `stg1bg.anm`, from `2100` to
`3124` still produces a `131`-entry archive that parses cleanly, but first
entry extraction fails with a deterministic late size check:

- `classification=extract-error`
- `error_type=Pbg3Error`
- `error_message=PBG3 size mismatch for stg1bg.anm: 2100 != 3124`
- `extracted_before_failure.count=0`

This is distinct from the nearby
[pbg3-first-entry-expand-past-size-cross-family-basin](../pbg3-first-entry-expand-past-size-cross-family-basin/README.md):

- that basin fails earlier, while writing output, because extraction expands
  past the declared size;
- this finding gets through decompression and fails only at the final
  `len(output) == declared_size` check.

So these two findings split the same first-entry surface into two different
parser-side failure classes:

- early write-time overflow against a too-small declared size;
- late post-decompression size mismatch against a too-large declared size.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-first-entry-size-inflate-mismatch/reproduce.py
```

Like the other PBG3 findings, this one stays recipe-backed instead of tracking
the multi-megabyte mutated archive blob in Git.

Current local evidence:

- full campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-pbg3/20260822T-full-a/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-pbg3/20260822T-full-a/0010-first-entry-size-inflate/result.json`
- standalone reproduction summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/parser-pbg3-first-entry-size-inflate-mismatch/summary.json`

Why this one matters:

- it is a pure table-field mutation that preserves top-level parsing;
- it gives the parser lane a distinct extract-time invariant violation, not
  just another checksum failure;
- paired with the expand-past-size basin, it makes the first-entry size surface
  much clearer.
