# Findings

This tree is the durable output of the project.

Implementation lanes under `src/` and `fuzzers/` are allowed to evolve quickly.
`findings/` is where a weird case stops being “interesting output from one
campaign” and becomes a reproducible result.

## Reproduction contract

Every finding directory should be usable on a fresh machine with only:

- the repository;
- owned local retail inputs where required;
- public replay downloads where documented;
- the local build/runtime prerequisites from the main docs.

That means:

- keep proprietary or derivative Touhou blobs out of Git;
- include a `reproduce.py` that rebuilds the triggering payload or campaign;
- keep compact reconstruction metadata such as `payload_patch.json`,
  `payload_recipe.json`, or `cases.json` beside the reproducer when needed;
- treat ignored `artifacts/` paths as optional prior evidence, not as the only
  way to recreate the result.

## What belongs here

- short analysis
- reproduction commands
- compact payload metadata
- helper scripts specific to the finding
- notes about cluster/root-cause relationships when multiple cases collapse
  into one basin

What does not belong here:

- large raw traces
- copied retail assets
- one-off temporary campaign outputs

## Layout

- `findings/semantic/...` for headless/runtime/replay findings
- `findings/parser/...` for file-format and loader findings
- `findings/runtime/...` for runtime crashes/oracle cases that are better
  grouped outside the semantic payload-mutator taxonomy

Prefer one directory per finding, or one directory per tightly related basin
when several payloads clearly reduce to the same root behavior.
