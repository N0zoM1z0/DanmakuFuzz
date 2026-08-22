# Stage 3 `call-sub-zero` in-range `next_time` corruption

Observed on August 22, 2026.

This finding comes from the TH06 semantic exploration lane after switching ECL
mutation from fixed templates to seeded value-basin sampling. On
`ecldata3.ecl`, the `call` instruction at `(sub=9, instruction=15)` originally
targets subroutine `10`. Mutating that target to subroutine `0` still stays
within the Stage 3 file's valid subroutine range (`0..34`), but the run later
enters an impossible timeline state:

- the mutated run surfaces `ecl_timeline.next_time=-9163` at tick `1347`;
- by tick `1362`, the baseline still reports `ecl_timeline.next_time=1470`,
  while the mutated run remains at `-9163`;
- the trigger is not an obviously out-of-range subroutine index: the mutated
  value `0` is in range for the file's `35` subroutines.

This exact reproducer is also now backed by a broader Stage 3 family sweep: on
August 22, 2026, a dedicated `call-sub` exploration sweep over TH06 stages
`1..6` found `11/12` interesting Stage 3 call-site/value pairs collapsing into
the same `ecl_timeline.next_time=-9163` sink, while stages `1`, `2`, `4`, `5`,
and `6` stayed at `0/12`.

Rebuild the triggering payload from the local baseline corpus and rerun the
headless differential check with:

```sh
PYTHONPATH=src python3 findings/semantic/stage3-call-sub-zero-in-range-next-time-negative/reproduce.py
```

The finding directory also keeps a compact exact-payload reconstruction patch:

- `findings/semantic/stage3-call-sub-zero-in-range-next-time-negative/payload_patch.json`

The reproducer canonicalizes the seed ECL once and then applies that patch, so
the exact payload can be rebuilt on another machine without depending on ignored
artifact output.

The reproducer prepares its own isolated headless worker copy under the finding
artifact directory instead of running against the shared source game tree.
Today, on August 22, 2026, this case also showed path-sensitive heap-layout
behavior in headless mode, so the script defaults to the known-good artifact
root `artifacts/findings/semantic-stage3-call-sub-zero-a`.

To also drive the rebuilt payload through retail Practice Stage 3 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage3-call-sub-zero-in-range-next-time-negative/reproduce.py \
  --retail
```

Current local evidence:

- hotspot basin summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/stage3-jump-call-exploration/summary.json`
- source exploration case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-exploration-stage3-jump-call/0016-call-sub-sampled-0-s09-i0015/result.json`
- dedicated finding rerun:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage3-call-sub-zero-a/summary.json`
- retail confirmation smoke:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/semantic-stage3-call-sub-zero-a/retail/report.json`
- dedicated Stage 3 `call-sub` family sweep:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-family-sweep/20260822T-call-sub-portable-explore-a/summary.json`
- Stage 3 `call-sub` hotspot basin summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-hotspots/stage3-call-sub-portable-explore-a/summary.json`

Why this one matters:

- it came out of the new exploration lane rather than the old fixed `-1 /
  past-end / max-i32` template set;
- it demonstrates that a valid in-range call target can still corrupt timeline
  scheduler state;
- it serves as one stable concrete reproducer for a much wider Stage 3
  `call-sub` basin, instead of a one-off magic constant;
- it is a useful bridge case between “obviously malformed call target” and
  “plausible-but-weird stage script control flow.”

Current interpretation:

- headless: clearly interesting and reproducible.
- retail: the August 22, 2026 smoke reached `game-window-live`, and the progress
  probe observed visible frame changes instead of a static screen.
- note: the current retail probe confirms that the rebuilt payload loads and
  advances in Practice Stage 3 under Wine, but it does not yet introspect the
  later negative `ecl_timeline.next_time` state directly.
- note: the newer family sweep suggests this reproducer is a representative of a
  Stage 3-specific `call-sub` structural weakness, not a TH06-wide `call-sub`
  behavior.
