# Stage STD metadata metamorphic runtime equivalence

Observed on August 23, 2026.

This observation checks whether `.std` stage-file metadata fields affect
headless gameplay state. The runner patches each `stage*.std` through the
resource override path, runs `th06-headless`, and compares the full trace hash
and line count against the clean baseline.

Checked transforms:

- `RawStageHeader.unk_c` pattern;
- stage display-name replacement;
- stage-name C-string tail bytes after the first NUL;
- song-name C-string tail bytes;
- song-path C-string tail bytes;
- all song display names replaced;
- all song paths replaced.

Result across `stage1.std` through `stage7.std`:

- `49/49` relation holds;
- `49/49` runtime equivalent;
- `0` violations.

This is useful as a negative control for STD fuzzing. It says these header
metadata changes are not sufficient to perturb the current headless gameplay
trace, so later STD candidates should focus on object tables, quads, script
opcodes, offsets, or retail-specific audio behavior.

## Reproduce

Quick Stage 6 check:

```sh
PYTHONPATH=src python3 findings/runtime/stage-std-metadata-metamorphic-runtime-equivalence/reproduce.py
```

Current local evidence:

- `artifacts/checks/stage-std-metamorphic-runtime-stage1-20260823/campaign.json`
- `artifacts/checks/stage-std-metamorphic-runtime-stage2-20260823/campaign.json`
- `artifacts/checks/stage-std-metamorphic-runtime-stage3-20260823/campaign.json`
- `artifacts/checks/stage-std-metamorphic-runtime-stage4-20260823/campaign.json`
- `artifacts/checks/stage-std-metamorphic-runtime-stage5-20260823/campaign.json`
- `artifacts/checks/stage-std-metamorphic-runtime-stage6-20260823/campaign.json`
- `artifacts/checks/stage-std-metamorphic-runtime-stage7-20260823/campaign.json`
