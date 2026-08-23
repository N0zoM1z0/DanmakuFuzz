# Source-less / cross-game portability

DanmakuFuzz should not assume TH06 source code exists.

The target shape is:

- extract one or more retail seeds from the game's archives;
- parse only the structural parts we can trust from the binary format;
- mutate those structures without needing VM source;
- run a game-specific oracle path;
- keep findings as reproducible payload patches or action streams.

## Portable lanes

### Binary-first parser lane

These lanes should work even when we only have retail assets:

- archive/container parsing;
- replay parsing;
- stage resource parsing;
- message-script parsing;
- config parsing;
- score/save parsing;
- ANM/resource-script parsing.

### Raw ECL semantic lane

For semantic fuzzing, the portable minimum is not "know every opcode". It is:

- split ECL into timeline and subroutine instructions;
- preserve enough structure to reserialize a valid payload;
- mutate generic fields directly.

That is why the exploration lane now includes source-less families such as:

- `generic-opcode`
- `generic-arg16`
- `generic-arg32`
- `generic-arg32-cross`
- `instruction-time`
- `instruction-aux-byte`
- `difficulty-mask`
- `timeline-time`
- `timeline-arg0`
- `timeline-opcode`
- `adjacent-instruction-time-cross`
- `adjacent-timeline-time-cross`

Those remain useful even when a future game's opcode semantics are only
partially labeled.

### Input / replay-style lane

Input mutation is already portable in spirit:

- mutate action streams;
- rerun twice for repeatability;
- keep only strong runtime drifts or wedges.

That should transfer to TH07/TH08 with much less per-opcode work than full ECL
labeling.

## Minimal game-profile boundary

A new game profile should only need to answer:

- where the retail game directory lives;
- how to launch the headless or Wine oracle;
- where archives / cfg / score / replay files live;
- how practice-stage or equivalent selection works;
- which seed corpora can be extracted;
- which artifact names correspond to ECL / ANM / MSG / stage resources.

The mutator core should not become TH06-specific again just because the first
implementation came from TH06.

## Oracle priorities

For source-less work, the most useful oracles are semantic rather than purely
memory-safety oriented:

- negative or impossible timeline state;
- stalled progress / stalled frame;
- stage-script drift;
- item / bullet / laser non-finite metrics;
- score / enemy-count / terminal-reason drift;
- repeat desync for identical seed + actions;
- accepted-with-drift parser results for resource formats.

## Current gaps

Still missing or incomplete:

- actual TH07/TH08 game profiles and corpora;
- ANM runtime oracles that see render/resource corruption, not only structural
  parse drift;
- more multi-resource or multi-state campaigns;
- more format lanes beyond the current TH06 layouts.
