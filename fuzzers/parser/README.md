# Parser lane

Planned native harness targets:

- `pbg3_archive`
- `replay_parser`
- `stage_std_loader`

The lane is intentionally separate from headless orchestration. Parser fuzzing
should stay small, sanitizer-friendly, and directly attributable to a specific
loader or decoder.
