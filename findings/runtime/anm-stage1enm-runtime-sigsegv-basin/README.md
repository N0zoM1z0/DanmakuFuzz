# Stage 1 enemy ANM SIGSEGV basin

Observed on August 23, 2026.

This finding is the first compact proof that the Stage 1 enemy ANM lane has a
real crash basin, not just soft runtime drift.

The retail `stg1enm.anm` seed contains at least four source-less accepted
mutants that all collapse into the same deterministic outcome under fixed
Stage 1 Practice playback:

- headless exits with `SIGSEGV`;
- a partial trace is still emitted;
- the trace stops at `128` lines instead of the baseline `311`;
- the run hits `trace-shortfall` and `terminal-reason-drift`.

Stable crash-basin members:

- `first-sprite-offset-zero`
- `first-script-id-ffff`
- `first-script-offset-zero`
- `first-instr-opcode-255`

`first-sprite-offset-zero` is slightly richer than the other three: before the
crash, it also shows `anm-load-drift` and `anm-suspicious-sprite`. The other
three are cleaner VM/parser-to-runtime crash transitions.

Why this matters:

- it is a portable, source-less ANM finding;
- it is not tied to TH06 ECL opcode semantics;
- it shows that the ANM lane can preserve enough trace to classify pre-crash
  drift instead of only reporting a hard process failure.

Current basin clustering:

- `first-script-id-ffff`, `first-script-offset-zero`, and
  `first-instr-opcode-255` are one clean crash sub-basin:
  they produce the same trace hash, the same `128`-line partial trace, and no
  observable divergence before the crash cutoff itself;
- `first-sprite-offset-zero` is a sibling sub-basin:
  it diverges immediately because ANM load state already drifts, but it still
  lands in the same `SIGSEGV + 128-line partial trace` sink.

That narrows the apparent root cause from “four unrelated weird mutants” down
to a smaller statement:

- one likely script-dispatch / first-script corruption sink;
- one sprite-table corruption path that still converges into that same sink.

Reproduce it with:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage1enm-runtime-sigsegv-basin/reproduce.py
```

Cluster the reproduced cases with:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage1enm-runtime-sigsegv-basin/analyze_clusters.py
```

Payload selection is recorded in:

- [payload_recipe.json](/home/yann/yann/touhou/DanmakuFuzz/findings/runtime/anm-stage1enm-runtime-sigsegv-basin/payload_recipe.json)

Current local evidence:

- focused runtime campaign:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-anm-runtime-entry-campaign-default/stg1enm.anm/summary.jsonl`
- accepted `enm` sweep:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-anm-runtime-enm-accepted/campaign.json`
