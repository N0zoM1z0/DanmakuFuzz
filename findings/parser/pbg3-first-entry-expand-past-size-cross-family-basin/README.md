# PBG3 `first-entry` expand-past-size cross-family basin

Observed on August 22, 2026.

This finding comes from the PBG3 parser lane. Three different deterministic
mutations already collapse into the same extraction-time failure on the first
archive entry, `stg1bg.anm`:

- `first-entry-size-zero`
- `first-entry-bitflip`
- `first-entry-bitflip-resummed`

All three payloads still parse as `131`-entry archives, but extracting the
first entry fails in the same way:

- `classification=extract-error`
- `error_type=Pbg3Error`
- `error_message=PBG3 entry expands past its declared size: stg1bg.anm`
- `extracted_before_failure.count=0`

The interesting part is that these mutations come from different surfaces:

- `first-entry-size-zero` is a pure table-field mutation that changes the
  declared uncompressed size for `stg1bg.anm` from `2100` to `0`;
- `first-entry-bitflip` flips one bit in the first compressed payload byte;
- `first-entry-bitflip-resummed` keeps the same corrupted compressed payload
  but also recomputes the stored checksum.

Even after the checksum is resummed, the failure stays identical. That means
this basin is strictly pre-checksum: the decompressor overruns the declared
entry size before checksum validation can matter.

Rebuild and re-evaluate the three payloads from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-first-entry-expand-past-size-cross-family-basin/reproduce.py
```

Like the other PBG3 findings, this one stays recipe-backed instead of tracking
multi-megabyte mutated archive blobs in Git.

Current local evidence:

- full campaign summary:
  `artifacts/parser-pbg3/20260822T-full-a/campaign.json`
- standalone reproduction summary:
  `artifacts/findings/parser-pbg3-first-entry-expand-past-size-cross-family-basin/summary.json`

Why this one matters:

- it is a real cross-family basin on the parser side, not one isolated mutant;
- it shows that checksum repair does not rescue this class of corruption,
  because the failure happens earlier;
- it gives the parser lane a more interesting reusable shape than a single
  parse-error or one-off checksum mismatch.
