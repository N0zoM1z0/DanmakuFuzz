# First milestone plan

- [x] Extract seven retail stage ECL payloads into an ignored immutable
  baseline corpus.
- [x] Produce a deterministic headless baseline trace from fixed seed, stage,
  and actions.
- [x] Add a fuzz-only resource override path for headless execution so ECL
  mutations do not require rebuilding a DAT archive for each run.
- [ ] Parse ECL into a first-pass IR, serialize back to bytes, and generate
  targeted edge-case mutants.
- [ ] Score traces for crashes, hangs, NaN/Inf propagation, stalled progress,
  and pathological entity growth.
- [ ] Stand up parser harness entrypoints for PBG3, replay, and stage-data
  loaders.
- [ ] Replay minimized interesting cases against retail Wine in isolated
  workers.

Current repository work covers scaffolding plus the first-pass extraction,
baseline orchestration, headless resource override, IR, mutation, and semantic
scoring utilities. The current deterministic headless baseline is Stage 6,
Lunatic, Reimu A, seed 7, 600 ticks, fixed action file, with identical trace
hashes across two runs.
