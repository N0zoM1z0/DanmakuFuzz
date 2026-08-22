# Replay `last-stage-offset-zero` truncation acceptance

Observed on August 22, 2026.

This finding comes from the TH06 replay parser lane. Starting from the local
synthetic minimal replay seed, we zero the last non-zero stage data offset,
recompute a valid checksum, and keep the rest of the replay payload unchanged.
The parser still accepts the replay cleanly, but the parsed stage-offset view
silently drops the final stage chunk:

- baseline stage offsets: `[80, 84, 89, 0, 0, 0, 0]`;
- mutated stage offsets: `[80, 84, 0, 0, 0, 0, 0]`;
- payload size stays `95` bytes, so the final stage bytes are still physically
  present in the file;
- parser-visible replay structure becomes shorter anyway because the final
  non-zero offset disappeared.

This is the kind of parser robustness case we want: not a hard reject, but an
accepted replay whose parsed structure is materially different from baseline.

Rebuild and re-evaluate the payload with:

```sh
PYTHONPATH=src python3 findings/parser/replay-last-stage-offset-zero-truncation-acceptance/reproduce.py
```

Current local evidence:

- campaign summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-replay/20260822T-campaign-b/campaign.json`
- per-case result:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/parser-replay/20260822T-campaign-b/0005-last-stage-offset-zero/result.json`
- standalone reproduction summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/findings/parser-replay-last-stage-offset-zero-truncation-acceptance/summary.json`

Why this one matters:

- it is accepted with a valid checksum, so downstream replay consumers would
  treat it as a legitimate replay file;
- it strands real stage data bytes behind a now-zeroed offset table entry;
- it gives the replay lane a stronger finding class than pure checksum or
  version rejection.
