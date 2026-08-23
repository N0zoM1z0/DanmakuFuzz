# Stage 6 background ANM retail crash basin

Promoted on August 23, 2026.

This finding is the first ANM result in this run to cross from headless
runtime drift into a Wine retail true positive.

The Stage 6 accepted-profile ANM sweep produced three `stg6bg.anm` target hits:

- `first-sprite-offset-zero`: `anm-set-active-sprite-failure`;
- `first-script-id-ffff`: `anm-script-drift`;
- `first-script-offset-zero`: `anm-script-drift`.

After adding resource-level retail confirmation for `override_dir/entry_name`,
all three were patched into retail `ST.DAT` and reproduced as `crash-dialog`.
The clean baseline in each confirmation reached `game-window-live`.

The representative `first-sprite-offset-zero` case also passed repeat
confirmation `2/2` with `--expect-classification crash-dialog --require 2`.

Closure analysis reduced the basin to three single-cell resource-table edits:

- `sprite_offsets[0].offset = 0`;
- `script_entries[0].id = 65535`;
- `script_entries[0].first_instruction = 0`.

All three rebuild to the recorded payload SHA256s from the original
`stg6bg.anm` entry. The old ANM runtime campaign artifacts are useful audit
history, but they are not required to reconstruct the promoted payloads.

## Reproduce

Representative repeated crash:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage6bg-retail-crash-basin/reproduce.py
```

Full promoted set:

```sh
PYTHONPATH=src python3 findings/runtime/anm-stage6bg-retail-crash-basin/reproduce.py \
  --all --repeat 1
```

Local evidence is enumerated in [cases.json](cases.json). Closure evidence is
summarized by the `closure` block in [finding.json](finding.json).
