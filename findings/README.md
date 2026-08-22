# Findings

This tree tracks reviewed findings separately from the implementation lanes.

Rules:

- keep proprietary/derivative Touhou blobs out of Git;
- every finding directory must include a `reproduce.py` script that rebuilds the
  triggering payload from the local baseline corpus or retail archive;
- if a finding depends on an exact minimized payload, track a compact
  `payload_patch.json` or equivalent reconstruction metadata beside the
  reproducer;
- store only notes, analysis, scripts, and compact reconstruction metadata here;
- point to ignored local artifacts under `artifacts/` for previous runs, but do
  not rely on them as the only way to reproduce the finding;
- prefer one directory per finding or per tightly related finding family.

Suggested layout:

- `findings/semantic/...` for headless/runtime findings;
- `findings/parser/...` for parser/format findings.
