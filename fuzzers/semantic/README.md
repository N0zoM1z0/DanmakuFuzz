# Semantic lane

This lane owns:

- ECL seed corpus generation;
- ECL mutation;
- headless execution;
- semantic interestingness scoring;
- later minimization and retail replay handoff.

Native runtime changes, when needed, should be staged through
`third_party/th06-headless/` with minimal, reviewable patches.

## Current entrypoint

Run a targeted Stage ECL campaign with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.ecl_campaign \
  --seed-ecl reference/corpus/ecl/original/ecldata6.ecl \
  --limit 32
```

Each case gets its own ignored artifact directory containing:

- the loose-resource override payload;
- the headless trace;
- the combined runtime log;
- a `result.json` summary.

The campaign root also writes `summary.jsonl` and `campaign.json`.

Minimize a captured interesting case with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.minimize_case \
  --result artifacts/semantic/.../result.json
```

Prepare or launch an isolated retail confirmation worker from either a
semantic case or a minimized case with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.retail.confirm_case \
  --result artifacts/semantic-minimized/.../summary.json \
  --prepare-only \
  --dry-run
```
