# PBG3 `entry-count-one` truncation acceptance

Observed on August 22, 2026.

This finding comes from the PBG3 parser lane. Forcing the top-level archive
entry count down to `1` still produces an archive the parser accepts cleanly,
but it silently truncates the visible archive down to the first entry:

- archive header still parses successfully;
- entry table now enumerates only `1` entry instead of the retail baseline's
  `131`;
- the surviving first entry, `stg1bg.anm`, still extracts to the same payload
  hash as baseline;
- the remaining `130` retail entries disappear from the parsed archive view.

This is not a crash bug. It is a clean "accepted but materially different"
parser case, which is exactly the kind of thing we want the parser lane to keep
surfacing.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/pbg3-entry-count-one-truncation-acceptance/reproduce.py
```

Like the earlier checksum finding, this one stays recipe-backed instead of
tracking a full mutated archive blob in Git: the mutation is deterministic and
tiny, while storing a byte patch against a multi-megabyte rebuilt archive would
not buy us much.

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-pbg3/20260822T-campaign-b/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-pbg3/20260822T-campaign-b/0004-entry-count-one/result.json`
- standalone reproduction summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/parser-pbg3-entry-count-one-truncation-acceptance/summary.json`

Why this one matters:

- it is accepted by the parser rather than rejected, so downstream code would
  see a plausible-looking but truncated archive;
- it preserves the first extracted file byte-for-byte, which makes the
  truncation less obvious than a hard parse failure;
- it gives the parser lane a second class of finding beyond extraction-time
  checksum/size faults.
