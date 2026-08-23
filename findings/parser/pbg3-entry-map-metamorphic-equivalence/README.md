# PBG3 archive entry-map metamorphic equivalence

Observed on August 23, 2026.

This format observation comes from the PBG3 metamorphic lane. For each unique
retail TH06 `.DAT` archive, the campaign rebuilds archive containers while
preserving the filename-to-extracted-payload map, then checks that parsing and
extraction remain equivalent to the baseline archive.

The checked transforms include:

- literal-only recompression of every entry;
- rebuilding around the original compressed streams;
- reversed and filename-sorted entry order;
- zero and non-zero padding after compressed stream terminators;
- trailing bytes after the archive table;
- fixed mutations of table unknown fields.

The current full run covered 6 unique archives and 66 generated mutants:

- `relation_counts`: `{"holds": 66}`;
- `classification_counts`: `{"accepted": 66}`;
- `violation_counts`: `{}`.

This is intentionally classified as `format-observation`. It documents which
container-level bytes are outside the parser's semantic archive map, and should
not be promoted as a bug unless a later runtime oracle observes a material
behavior difference.

## Reproduce

```sh
PYTHONPATH=src python3 findings/parser/pbg3-entry-map-metamorphic-equivalence/reproduce.py
```

The default reproduction is a representative 11-case run over `*CM.DAT`.
Run the full 66-case archive-family check with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-entry-map-metamorphic-equivalence/reproduce.py --full
```

Current local evidence:

- `artifacts/checks/pbg3-metamorphic-unique-dat-20260823/campaign.json`
