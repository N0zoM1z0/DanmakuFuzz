# Finding Status Index

This tree groups findings and recent retail-confirmation artifacts by current
triage state. It is an index layer only: the durable finding directories still
live under `findings/parser`, `findings/semantic`, and `findings/runtime`.

Use this index when deciding what to promote, what to stop replaying, and what
still needs a stronger oracle.

- `confirmed-retail/INDEX.md`: Wine/retail true positives with concrete oracle
  evidence.
- `retail-disconfirmed/INDEX.md`: candidates checked against retail and reduced
  to false positive or non-bug observation for the original claim.
- `headless-pending-retail/INDEX.md`: headless findings that are still plausible
  but not retail-confirmed.
- `blocked-retail-oracle/INDEX.md`: cases where retail proof is blocked by
  missing controls rather than by a negative result.
- `format-observation/INDEX.md`: parser/model observations intentionally kept
  out of the bug queue.

The machine-readable source of truth for this index is `manifest.json`.
