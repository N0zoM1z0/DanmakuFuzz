# Capability snapshot

This file is not a changelog. It is the current project-state summary.

## Ready now

- immutable TH06 ECL seed extraction from owned retail data
- deterministic headless baselines and fuzz-only resource overrides
- structure-aware ECL mutation plus source-less/raw mutation families
- semantic exploration, family sweeps, boss sweeps, and exact reruns
- replay-derived semantic/desync fuzzing, including replay-native and
  replay-coordinated lanes
- generic input/action semantic fuzzing
- ANM runtime-entry campaigns
- parser campaigns for PBG3, replay, stage `.std`, message `.dat`, `cfg`,
  `score.dat`, and ANM
- clustering and minimization before retail replay
- isolated retail Wine preparation, replay, and batch confirmation
- findings tracked as self-contained `reproduce.py` entrypoints plus compact
  payload metadata

## Confirmed design direction

- headless search first, retail confirmation second
- semantic findings are treated as first-class outputs, not just crashes
- replay mutation is now broad enough to cover input-stream, replay-native, and
  coordinated multi-site lanes
- source-less portability remains a real requirement, not a future cleanup task

## Still incomplete

- stronger retail confirmation than the current window/dialog/screenshot layer
- actual TH07/TH08 game profiles and seed corpora
- broader render/resource-aware ANM runtime oracles
- more coordinated multi-resource campaigns beyond the current TH06-first set

## Current priority

As of August 23, 2026, the project is past the pure scaffolding phase. The main
work is now:

- improving the quality of interesting-case harvest, especially replay and
  semantic basin review;
- keeping findings reproducible without large retained artifact trees;
- preserving cross-game portability while the TH06 lane continues to deepen.
