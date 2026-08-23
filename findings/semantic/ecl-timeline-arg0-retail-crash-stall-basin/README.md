# ECL timeline arg0 retail crash/stall basin

Promoted on August 23, 2026.

This is the durable promotion of the ECL `timeline-arg0` family. It is the
current strongest ECL result because it crosses the full oracle chain:

- headless semantic campaign found the candidates;
- Wine retail confirmation patched the exact `ecldata*.ecl` payload into
  `ST.DAT`;
- clean retail baseline reached `game-window-live`;
- the mutant reached either `crash-dialog` or `retail-frame-stall`;
- the Stage 5 `timeline-arg0=256` stall representative passed repeat
  confirmation `2/2` with `--expect-classification retail-frame-stall`.
- closure analysis reduced every promoted payload to one timeline `arg0` cell
  and rebuilt all payload SHA256s from the original ECL corpus.

## Confirmed shape

The promoted set has 14 independent payloads across stages 2-6.

- crash cases primarily fault at retail addresses `004074DC` or `00412499`;
- stall cases stay inside the game window but fail the frame-progress oracle;
- every promoted retail run used `--compare-clean-baseline`.

The family should be read as a confirmed retail-positive basin. It is no longer
just a headless scent trail: the committed case recipes are enough to rebuild
the payloads without the original search artifacts.

## Reproduce

Representative repeated stall:

```sh
PYTHONPATH=src python3 findings/semantic/ecl-timeline-arg0-retail-crash-stall-basin/reproduce.py
```

Single crash representative:

```sh
PYTHONPATH=src python3 findings/semantic/ecl-timeline-arg0-retail-crash-stall-basin/reproduce.py \
  --case stage6-arg0-257 --repeat 1
```

Full promoted set:

```sh
PYTHONPATH=src python3 findings/semantic/ecl-timeline-arg0-retail-crash-stall-basin/reproduce.py \
  --all --repeat 1
```

Local evidence is enumerated in [cases.json](cases.json).
Closure evidence is summarized by the `closure` block in
[finding.json](finding.json).
