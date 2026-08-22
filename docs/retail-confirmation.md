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

`danmakufuzz.retail.confirm_case` currently does four things:

- copies an owned TH06 tree into an isolated artifact-local `game/`;
- normalizes the TH06 cfg to `32-bit + windowed` so Xvfb/Wine can reach the title screen;
- restores the local full-unlock `score.dat` when one is present under `全开档/`;
- rebuilds the stage DAT archive with one replacement `ecldata*.ecl` payload;
- initializes a dedicated Wine prefix and can either stop at launch or drive Practice mode.

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

Example isolated Practice Stage 6 confirmation:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.confirm_case \
  --result artifacts/semantic/fullstage6-stage6-seed7-ecldata6/0004-bullet-count1-zero-s01-i0003/result.json \
  --practice-stage 6 \
  --difficulty 3 \
  --timeout-seconds 20
```

Each run writes an isolated artifact directory containing:

- `game/` with patched retail archives;
- `prefix/` with its Wine state;
- `wineboot.log`, `wine.log`, and `xvfb.log` when live stage control runs;
- `control-*.png` screenshots when Practice automation runs;
- `control-window-census.json`, `control-window-names.txt`, and `control-xwininfo.txt` for post-start retail UI evidence;
- `report.json` with payload hash, patched archive hash, and launch result.

## Current limitation

TH06 loads stage ECL when a stage starts, not at process startup. The current
runner now proves all of these for Reimu A Practice:

- archive rebuilding works;
- isolation works;
- Wine can launch the original executable under the prepared environment;
- deterministic keyboard automation can enter Practice Stage 1--6;
- patched `ecldata6.ecl` can be carried all the way to Final Stage entry.

It also has a first-pass retail oracle:

- `game-window-live` when the main TH06 window remains live after the Practice
  start sequence and observation delay;
- `crash-dialog` when Wine exposes `プログラム エラー` or `Wine Debugger`
  windows after stage start.

It still does not prove:

- generic route automation from Start through Ending;
- memory-backed retail state sensing;
- that every interesting case reproduces the same VM/opcode path as headless.

The remaining missing pieces are:

- route-play automation;
- tighter oracles than window/dialog sensing;
- automatic replay of minimized interesting cases instead of one-off manual runs.
