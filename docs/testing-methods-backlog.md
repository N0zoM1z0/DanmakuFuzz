# Testing Methods Backlog

This project already has grammar-aware mutation, parser campaigns, headless
semantic oracles, Wine retail confirmation, replay state-drift oracles, and
metamorphic equivalence checks. The next useful methods should add either
stronger oracles or better candidate reduction.

## High-value next methods

1. Delta-debugging reducers
   - Goal: minimize ECL/ANM/replay payloads while preserving a concrete oracle
     such as `crash-dialog`, `input-error`, or `replay-stable-state-drift`.
   - First target: replay `bookmark-cut-tail`, ECL timeline-arg0 retail
     positives, and the ANM Stage 6 background crash basin.
   - Status: shared sequence reducer and monotonic bisection helpers live in
     `src/danmakufuzz/reduction.py`; replay cut-tail now has a model-backed
     reducer in `src/danmakufuzz/semantic/replay_cut_tail_analysis.py`.
     Confirmed ECL/ANM findings now have closure summaries from
     `src/danmakufuzz/findings/closure_analysis.py`: every promoted ECL and
     ANM payload reduces to one semantic cell and rebuilds to the recorded
     payload SHA256.

2. Metamorphic composition testing
   - Goal: compose several known-equivalent transforms, then inject one
     non-equivalent transform. If the oracle changes, the reducer can isolate
     which invariant boundary was crossed.
   - First target: replay action-stream equivalence plus bookmark cut-tail;
     STD metadata equivalence plus object/quad offset mutation.
   - Status: replay cut-tail composition is implemented in both orders:
     `delta -> equivalent-wrapper` and `equivalent-wrapper -> delta`.
     The cut-tail oracle is length-sensitive, so the composition check now
     treats input-exhaustion point drift as a violation even when bounded action
     values still match.

3. Differential implementation testing
   - Goal: compare independent views of the same payload: local parser,
     headless loader trace, and retail confirmer. Disagreements become
     first-class findings.
   - First target: ANM and STD parser summaries versus runtime load metrics.
   - Status: intentionally skipped in the current pass.

4. Property-based invariant fuzzing
   - Goal: generate structured valid objects, serialize, parse, normalize, and
     assert invariant families. This should produce regression tests for parser
     contracts rather than bug candidates directly.
   - First target: replay bookmark streams and PBG3 archive entry maps.

5. Coverage-guided parser fuzzing
   - Goal: use AFL/libFuzzer-style harnesses for fast parser-only exploration,
     then replay interesting corpus entries through existing semantic oracles.
   - First target: PBG3 decompression and replay deobfuscation/checksum/parser.
   - Status: a dependency-free structural coverage smoke runner now exists at
     `src/danmakufuzz/parser/coverage_smoke.py`. It covers PBG3, replay, ANM,
     and Stage STD by keeping cases that introduce new parser classification,
     error, count, and stop-reason signatures.

6. Stateful model-based testing
   - Goal: define legal state transitions for VM/timeline/replay input, then
     generate sequences that target boundary transitions rather than random
     bytes.
   - First target: ECL timeline VM, replay stage input exhaustion, and ANM
     script table lookup.
   - Status: replay input exhaustion has a first model:
     `expected_terminal_tick = cut_frame + 2` for the promoted cut-tail basin.
     The ECL/ANM closure pass also records the target VM/resource table cell
     and the temporal divergence marker that carries each confirmed case into
     retail.

7. Oracle amplification by negative controls
   - Goal: run candidate mutations under known-equivalent wrappers. A real
     finding should survive these wrappers; an oracle artifact often will not.
   - First target: wrap replay candidates in header-key reobfuscation and
     canonical bookmark re-encoding.

8. Cross-route/cross-difficulty metamorphic sampling
   - Goal: treat route/difficulty as controlled environment changes, not random
     noise, and classify whether a finding is invariant, route-specific, or
     difficulty-specific.
   - First target: replay cut-tail and Stage 6 ANM retail crash basin.

9. Temporal bisection oracles
   - Goal: when state drift is detected, binary-search the earliest tick/site
     that still reproduces it. This turns long trace drift into actionable
     root-cause windows.
   - First target: replay stable state drift at frames 443/467/479 and ECL
     timeline stalls.
   - Status: generic prefix-divergence and first-true bisection helpers are in
     `src/danmakufuzz/reduction.py`; replay cut-tail analysis records both the
     first action divergence frame and the bisection history for the modeled
     terminal tick. Finding closure records ECL trace-length shortfalls and
     ANM metric/drift tick markers beside the minimized semantic delta.

10. Crash signature bucketing with reducer-aware keys
    - Goal: bucket by normalized crash signature plus payload site metadata,
      not just return code or raw trace hash.
    - First target: Wine `crash-dialog` reports for ECL timeline-arg0 and ANM
      Stage 6 background crashes.

## Near-term recommendation

The TH06 confirmed set has enough closure for a release checkpoint. Future
method work should prioritize new surfaces rather than more blind expansion:
replay state models, coverage-guided parser harnesses, and cross-route
metamorphic checks are the best next places to look when the project moves past
this TH06 pass.
