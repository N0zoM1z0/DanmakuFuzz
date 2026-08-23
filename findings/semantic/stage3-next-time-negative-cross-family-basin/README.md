# Stage 3 cross-family `next_time=-9163` basin

Observed on August 22, 2026.

This finding captures a Stage 3 semantic sink that is no longer understood as a
single-mutator quirk. Under TH06 Practice Stage 3, multiple reusable ECL
mutator families can drive the game into the same impossible timeline state.
The generic representatives tracked here are:

- `bullet-count1`: `(sub=0, instruction=3)` mutates `bullet-count1` from `1` to `4`;
- `bullet-count2`: `(sub=1, instruction=3)` mutates `bullet-count2` from `1` to `8`;
- `shoot-interval`: `(sub=0, instruction=6)` mutates the interval from `60` to `64`.

Separately, the dedicated `call-sub-zero` finding has already shown that a
fourth family, `call-sub`, can reach the same sink signature under its own
stable reproducer.

Taken together, the basin is now at least four-family: `call-sub`,
`bullet-count1`, `bullet-count2`, and `shoot-interval`.

Even though those mutations touch different opcodes and fields, the three
generic runs in this directory already collapse into the same normalized sink
snapshot:

- sink signature:
  `83214f07b8e735a3dc4dc894c562c44385e3cc9680ca4a7983f10539b8e5a6f1`
- sink tick: `1347`
- sink time: `1345`
- sink `ecl_timeline.next_time`: `-9163`

Rebuild the three generic triggering payloads from the local baseline corpus and
rerun the shared-basin check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage3-next-time-negative-cross-family-basin/reproduce.py
```

This reproducer runs the three generic representatives against one shared Stage 3
baseline trace, then verifies that the resulting traces land in the same sink
signature instead of only checking for a crash or a single negative field.
Because this Stage 3 basin has shown path/layout sensitivity in headless mode,
the reproducer retries each representative with fresh isolated worker copies
until it reaches the expected sink or exhausts the configured attempt budget.
When `--artifact-dir` is omitted, it also rotates across a short list of known
stable artifact roots before giving up. Passing an explicit `--artifact-dir`
disables that root-level fallback and can still expose the old layout-sensitive
path behavior.

Tracked compact payload patches:

- `payload_bullet_count1_four.json`
- `payload_bullet_count2_eight.json`
- `payload_shoot_interval_sixtyfour.json`

Current local evidence:

- broader portable core exploration sweep:
  `artifacts/semantic-family-sweep/20260822T-portable-core-explore-c/summary.json`
- broader portable core hotspot summary:
  `artifacts/semantic-hotspots/portable-core-explore-c/summary.json`
- broader portable core trace basin summary:
  `artifacts/semantic-trace-basins/portable-core-explore-c/summary.json`
- widened portable core exploration sweep after site-level exploration reorder:
  `artifacts/semantic-family-sweep/20260822T-portable-core-explore-d/summary.json`
- widened portable core hotspot summary:
  `artifacts/semantic-hotspots/portable-core-explore-d/summary.json`
- widened portable core trace basin summary:
  `artifacts/semantic-trace-basins/portable-core-explore-d/summary.json`
- dedicated call-sub representative finding:
  `findings/semantic/stage3-call-sub-zero-in-range-next-time-negative/README.md`

Why this one matters:

- it upgrades the earlier Stage 3 `call-sub` result into a family-agnostic basin
  description;
- it shows that small, in-range, semantically plausible mutations can converge
  on the same scheduler corruption;
- it gives one stable reproducer for the generic part of a structural Stage 3
  weakness instead of leaving the evidence split across unrelated case dirs.

Current interpretation:

- headless: clearly interesting and reproducible;
- the basin is cross-family inside Stage 3, not `call-sub`-only;
- the widened August 22, 2026 reproducer now includes `bullet-count2` directly,
  so the generic proof no longer depends on artifact-only evidence for that
  family;
- note: the headless path is somewhat layout-sensitive, so the reproducer uses
  isolated worker copies and a bounded retry loop instead of assuming one-shot
  determinism;
- this still looks Stage 3-specific rather than TH06-wide, since the portable
  core sweep did not show the same sink on stages `1`, `2`, `4`, `5`, or `6`.
