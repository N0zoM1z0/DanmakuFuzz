# First milestone plan

- [x] Extract seven retail stage ECL payloads into an ignored immutable
  baseline corpus.
- [x] Produce a deterministic headless baseline trace from fixed seed, stage,
  and actions.
- [x] Add a fuzz-only resource override path for headless execution so ECL
  mutations do not require rebuilding a DAT archive for each run.
- [x] Parse ECL into a first-pass IR, serialize back to bytes, and generate
  targeted edge-case mutants.
- [x] Score traces for crashes, hangs, NaN/Inf propagation, stalled progress,
  and pathological entity growth.
- [ ] Stand up parser harness entrypoints for PBG3, replay, and stage-data
  loaders.
- [ ] Replay minimized interesting cases against retail Wine in isolated
  workers.

Current repository work covers scaffolding plus the first-pass extraction,
baseline orchestration, headless resource override, IR, mutation, and semantic
scoring utilities. The current deterministic headless baseline is Stage 6,
Lunatic, Reimu A, seed 7, 600 ticks, fixed action file, with identical trace
hashes across two runs. All seven retail ECL seeds now parse and reserialize,
the current IR mutator set expands to 6,061 targeted mutants across the retail
corpus, and the semantic campaign lane can automatically surface process
signals such as the zero-byte `ecldata6.ecl` `SIGSEGV` case.
