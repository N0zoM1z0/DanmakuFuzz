# Stage `.std` `first-quad-type-neg1` chain truncation acceptance

Observed on August 23, 2026.

This finding comes from the stage `.std` parser lane on the retail
`stage1.std` seed inside `紅魔郷ST.DAT`.

Forcing the first quad header's `type` field negative does not make the
parser/walker reject the stage. Instead, it treats the very first quad in
object `0` as the chain terminator and silently truncates that object's quad
list to zero.

Baseline walk:

- `nb_objects=13`
- object `0` has `quad_count=56`
- `quad_count_walked=343`
- `script_instructions=1`
- `script_stop_reason=size-overrun@0x31a4:17505`

Mutated walk:

- `nb_objects=13`
- object `0` has `quad_count=0`
- `quad_count_walked=287`
- `script_instructions=1`
- `script_stop_reason=size-overrun@0x31a4:17505`

So the mutation does not break the whole stage file. The script walker stays
unchanged, the other objects stay intact, and only the first quad chain is
silently discarded.

This makes it a useful accepted parser case:

- not a hard reject;
- not a header-pointer alias;
- a local structural collapse in the object/quad walk that downstream code
  could plausibly interpret as “valid but missing geometry”.

Rebuild and re-evaluate the payload from the local retail archive with:

```sh
PYTHONPATH=src python3 findings/parser/stage-std-first-quad-type-neg1-chain-truncation-acceptance/reproduce.py
```

Like the other parser findings, this one stays recipe-backed instead of
tracking the mutated `.std` payload in Git: the mutation is deterministic and
small, and the reproduction script is enough to regenerate the exact case from
the retail seed.

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-stage-std/20260823T-stage1-campaign-a/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-stage-std/20260823T-stage1-campaign-a/0011-first-quad-type-neg1/result.json`
- standalone reproduction summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/parser-stage-std-first-quad-type-neg1-chain-truncation-acceptance/summary.json`

Why this one matters:

- it is accepted rather than rejected, so a downstream loader would see a
  plausible stage with locally missing geometry rather than a parse failure;
- it isolates a purely object/quad-side structural fault while keeping the
  script walker unchanged;
- it broadens the stage parser lane beyond one header-alias example.
