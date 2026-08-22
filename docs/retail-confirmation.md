# Retail confirmation boundary

Headless execution is used for search throughput and structured triage.

Retail Wine confirmation remains required for:

- crash reproduction claims against the shipped game;
- behavioral divergence claims that depend on original runtime semantics;
- final bug reports worth carrying forward.

Retail state must stay isolated:

- dedicated game directory;
- dedicated Wine prefix and display;
- dedicated artifact root;
- no sharing with unrelated solver work.

## Current runner

`danmakufuzz.retail.confirm_case` currently does three things:

- copies an owned TH06 tree into an isolated artifact-local `game/`;
- rebuilds the stage DAT archive with one replacement `ecldata*.ecl` payload;
- initializes a dedicated Wine prefix and optionally launches the retail exe.

Supported inputs:

- a semantic campaign `result.json`;
- a minimizer `summary.json`.

Example dry-run from a minimized case:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.confirm_case \
  --result artifacts/semantic-minimized/bullet-sprite-16-s01-i0003/summary.json \
  --prepare-only \
  --dry-run
```

Example isolated launch smoke:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.confirm_case \
  --result artifacts/semantic-minimized/bullet-sprite-16-s01-i0003/summary.json \
  --timeout-seconds 3
```

Each run writes an isolated artifact directory containing:

- `game/` with patched retail archives;
- `prefix/` with its Wine state;
- `wineboot.log` and `wine.log`;
- `report.json` with payload hash, patched archive hash, and launch result.

## Current limitation

This is still a launch-only retail handoff.

TH06 loads stage ECL when a stage starts, not at process startup. So this
runner proves:

- archive rebuilding works;
- isolation works;
- Wine can launch the original executable under the prepared environment.

It does not yet prove:

- that the patched ECL was reached by retail runtime;
- that a headless finding reproduces inside a real stage;
- that a minimized case reaches the same VM/opcode path in retail.

The next missing piece is a small retail control path for deterministic menu
navigation into Practice or a direct stage-start hook.
