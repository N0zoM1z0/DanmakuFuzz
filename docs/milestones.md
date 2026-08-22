# First milestone plan

1. Extract seven retail stage ECL payloads into an ignored immutable baseline
   corpus.
2. Produce a deterministic headless baseline trace from fixed seed, stage, and
   actions.
3. Add a fuzz-only resource override path for headless execution so ECL
   mutations do not require rebuilding a DAT archive for each run.
4. Parse ECL into a first-pass IR, serialize back to bytes, and generate
   targeted edge-case mutants.
5. Score traces for crashes, hangs, NaN/Inf propagation, stalled progress, and
   pathological entity growth.
6. Stand up parser harness entrypoints for PBG3, replay, and stage-data
   loaders.
7. Replay minimized interesting cases against retail Wine in isolated workers.

Current repository work covers scaffolding plus the first-pass extraction,
baseline orchestration, IR, mutation, and semantic scoring utilities.
