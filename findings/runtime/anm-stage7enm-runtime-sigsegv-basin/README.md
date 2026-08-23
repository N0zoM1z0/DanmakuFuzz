# Stage 7 enemy ANM SIGSEGV basin

Observed on August 23, 2026.

This finding shows that the `stg7enm.anm` lane has the same compact crash-basin
shape already seen on `stg1enm.anm`, but much later in the run.

The retail `stg7enm.anm` seed contains at least four source-less accepted
mutants that all collapse into the same deterministic outcome under fixed
Stage 7 Practice playback:

- headless exits with `SIGSEGV`;
- a partial trace is still emitted;
- the trace stops at `440` lines instead of the baseline `582`;
- the run hits `trace-shortfall` and `terminal-reason-drift`.

Stable crash-basin members:

- `first-sprite-offset-zero`
- `first-script-id-ffff`
- `first-script-offset-zero`
- `first-instr-opcode-255`

`first-sprite-offset-zero` is again the richer sibling: before the crash, it
also shows `anm-load-drift` and `anm-suspicious-sprite`. The other three are
cleaner script/VM-to-runtime crash transitions.

Current basin clustering:

- `first-script-id-ffff`, `first-script-offset-zero`, and
  `first-instr-opcode-255` are one clean crash sub-basin:
  they produce the same trace hash, the same `440`-line partial trace, and no
  observable divergence before the cutoff itself;
- `first-sprite-offset-zero` is the sibling sub-basin:
  it diverges immediately because ANM load state already drifts, but it still
  lands in the same `SIGSEGV + 440-line partial trace` sink.

Cross-stage comparison against `stg1enm`:

| Property | `stg1enm.anm` | `stg7enm.anm` |
| --- | --- | --- |
| Baseline trace length | `311` | `582` |
| Crash trace length | `128` | `440` |
| Stable crash mutants | 4 | 4 |
| Clean script sub-basin | `script-id-ffff`, `script-offset-zero`, `instr-opcode-255` | same 3 mutants |
| Clean sub-basin first diff | `129` | `441` |
| Sprite sibling first diff | `1` | `1` |
| Process sink | `SIGSEGV` | `SIGSEGV` |

The evidence says this is very likely the same sink family, not an unrelated
Stage 7-only accident:

- the stable mutant set is identical;
- the basin partitions into the same `3 clean script + 1 sprite-prelude`
  structure;
- the clean trio stays baseline-identical until the final emitted line, then
  dies with the same signal kind;
- the sprite mutant diverges at line 1 but still converges into the same crash
  shape.

What is not proven yet:

- the exact crashing instruction pointer;
- whether `stg1enm` and `stg7enm` hit the same concrete code site or just the
  same bug class.

So the defensible statement is: this is a strong cross-stage sink-shape match,
and likely the Stage 7 instance of the same first-script / first-opcode crash
family.

Reproduce it with:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage7enm-runtime-sigsegv-basin/reproduce.py
```

Cluster the reproduced cases with:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage7enm-runtime-sigsegv-basin/analyze_clusters.py
```

Payload selection is recorded in:

- [payload_recipe.json](findings/runtime/anm-stage7enm-runtime-sigsegv-basin/payload_recipe.json)

Current local evidence:

- focused runtime smoke:
  `artifacts/tmp-anm-runtime-next-layer-smoke/stg7enm.anm/summary.jsonl`
- accepted `stg7enm` sweep:
  `artifacts/tmp-anm-runtime-stage7enm-accepted/campaign.json`
- Stage 1 sibling finding:
  `findings/runtime/anm-stage1enm-runtime-sigsegv-basin/README.md`
