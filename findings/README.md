# Findings

This tree is the durable output of DanmakuFuzz.

Campaigns can be messy. Wine prefixes, traces, screenshots, and worker copies
are allowed to be temporary. A finding is different: it is a small, reproducible
claim about TH06 behavior, with enough recipe data to summon the same payload
again after the artifact storm has been swept away.

## Reproduction contract

Every promoted finding directory should be usable on a fresh machine with only:

- the repository;
- owned local TH06 retail inputs where required;
- public replay downloads where documented;
- the local build/runtime prerequisites from the main docs.

That means:

- keep proprietary or derivative Touhou blobs out of Git;
- include a `reproduce.py` that rebuilds the triggering payload or campaign;
- keep compact reconstruction metadata such as `payload_patch.json`,
  `payload_recipe.json`, or `cases.json` beside the reproducer when needed;
- treat ignored `artifacts/` paths as optional prior evidence, not as the only
  way to recreate the result.

## Metadata contract

New or updated finding directories should include `finding.json` beside the
README. The schema is tracked at `findings/schema.json` and can be checked with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.findings.validate_metadata
```

Use `--require-all` only after a directory has been migrated. Evidence levels
are intentionally explicit: format characterizations, parser-model-only cases,
headless candidates, retail behavioral divergences, and confirmed retail
crashes are not the same claim.

## What Belongs Here

- short analysis
- reproduction commands
- compact payload metadata
- helper scripts specific to the finding
- notes about cluster/root-cause relationships when multiple cases collapse
  into one basin
- `finding.json` once a finding has been triaged

What does not belong here:

- large raw traces
- copied retail assets
- one-off temporary campaign outputs
- Wine prefixes or patched game directories

## Layout

- `findings/semantic/...` for headless/runtime/replay findings
- `findings/parser/...` for file-format and loader findings
- `findings/runtime/...` for runtime crashes/oracle cases that are better
  grouped outside the semantic payload-mutator taxonomy
- `findings/by-status/...` for review indexes that group cases by current
  confirmation state. These directories intentionally use `INDEX.md` rather
  than `README.md` so metadata validation does not mistake an index bucket for
  a standalone finding.

Prefer one directory per finding, or one directory per tightly related basin
when several payloads reduce to the same root behavior. If the same mechanism
hits multiple stages, promote the basin and put the per-stage details in
`cases.json`.

## Triage status

`finding.json` may include `triage_status` when a finding has been reviewed
against the current oracle:

- `confirmed-retail`: Wine/retail confirmation has a concrete expected oracle.
- `retail-disconfirmed`: the earlier bug-shaped claim was checked and did not
  reproduce under the retail oracle.
- `retail-observation`: retail shows a benign or non-crash behavioral/visual
  difference, but not a bug oracle.
- `headless-pending-retail`: headless evidence exists and retail confirmation
  is still pending.
- `blocked-retail-oracle`: retail confirmation needs stronger controls before
  the result can be trusted.
- `format-observation`: accepted/equivalent parser behavior worth documenting,
  but not a bug candidate.
- `needs-reproduction`: old note that should be rebuilt before promotion.
