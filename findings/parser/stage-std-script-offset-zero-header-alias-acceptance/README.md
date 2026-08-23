# Stage `.std` `script-offset-zero` header-alias acceptance

Observed on August 23, 2026.

This finding comes from the stage `.std` parser lane on the retail
`stage1.std` seed inside `紅魔郷ST.DAT`.

Forcing the top-level `scriptOffset` field down to `0` does not cause the
parser/walker to reject the payload. It still accepts the stage and walks the
object table normally, but it silently repoints the script walker at the file
header:

- baseline `script_offset=12696`
- mutated `script_offset=0`

Under the baseline walk:

- `script_instructions=1`
- `script_stop_reason=size-overrun@0x31a4:17505`

Under the mutated walk:

- `script_instructions=0`
- `script_stop_reason=size-too-small@0x0:0`

The object side stays intact:

- `nb_objects=13`
- `quad_count_walked=343`
- all object summaries remain identical to baseline

So this is not a generic “the whole file is broken” case. It is a clean header
alias case: the stage still parses, the object walk still succeeds, but the
script region is silently redirected to the header and collapses immediately.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/stage-std-script-offset-zero-header-alias-acceptance/reproduce.py
```

Like the existing PBG3 parser findings, this one stays recipe-backed instead of
tracking a full mutated `.std` blob in Git: the mutation is deterministic and
tiny, and the reproduction script is enough to regenerate the exact case from
the retail seed.

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-stage-std/20260823T-stage1-campaign-a/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-stage-std/20260823T-stage1-campaign-a/0006-script-offset-zero/result.json`
- standalone reproduction summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/parser-stage-std-script-offset-zero-header-alias-acceptance/summary.json`

Why this one matters:

- it is accepted, not rejected, so downstream loader code would see a
  plausible-looking stage payload with a dead script region;
- the object walk remains identical, which makes the bug shape more subtle
  than a whole-file parse failure;
- it gives the parser lane a stage-data counterpart to the accepted-but-wrong
  PBG3 cases, rather than only adding another hard reject.
