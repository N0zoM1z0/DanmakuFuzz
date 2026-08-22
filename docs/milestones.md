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
- [x] Stand up parser harness entrypoints for PBG3, replay, and stage-data
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
signals such as the zero-byte `ecldata6.ecl` `SIGSEGV` case. The parser lane
now also has standalone PBG3, replay, and stage `.std` entrypoints for
independent format validation. Retail handoff now has an isolated preparation
runner that can rebuild `紅魔郷ST.DAT`/`峠杺嫿ST.DAT`, initialize a dedicated
Wine prefix, normalize the retail cfg for Xvfb, restore the local full-unlock
`score.dat`, and drive Reimu A Practice Stage 1--6 from either semantic
`result.json` or minimized `summary.json`. The retail runner now also records
window-census evidence and auto-classifies at least `crash-dialog` versus
`game-window-live`. A thin batch wrapper can now replay multiple semantic or
minimized cases through the same retail path and aggregate classifications into
`results.jsonl` / `summary.json`, with queue shaping such as interesting-only
filtering and one-sample-per-finding prioritization. Retail reports now also
carry compact Wine crash signatures plus a headless-finding-to-retail summary
matrix at the batch level, and the replay queue can consult prior retail
history to skip already confirmed sources or findings. The retail signature key
now also normalizes thread/address jitter in Wine crash lines before grouping.
Milestone 7 remains open until the retail
oracle grows beyond the current window/dialog layer.
