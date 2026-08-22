# Headless resource override contract

The semantic lane needs a fuzz-only override path so mutated ECL payloads can
be fed into the headless runtime without rebuilding `紅魔郷ST.DAT` for every
test case.

## Required behavior

- baseline behavior stays unchanged when no override is configured;
- overrides are explicit and opt-in;
- only selected resource basenames are replaced;
- the override path is local-only and must not become a hidden runtime
  dependency;
- the patch point stays confined to the headless runtime, not the mutation
  tooling.

## Planned interface

One of the following is acceptable:

- environment variable such as `DANMAKUFUZZ_OVERRIDE_DIR`;
- explicit CLI option such as `--resource-override-dir`.

Lookup policy:

1. if override directory contains the requested basename, load that file;
2. otherwise fall back to the normal archive-backed lookup.

## Likely patch points

The override should intercept the earliest file-open path that already knows
the basename requested by the runtime. For the original TH06 code line this is
the `FileSystem::OpenPath(..., false)` path; for the headless fork the exact
portable equivalent will be patched inside `third_party/th06-headless/`.
