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

## Implemented interface

- environment variable `DANMAKUFUZZ_OVERRIDE_DIR` consumed by
  `third_party/th06-headless/src/FileSystem.cpp`;
- Python launcher option `--resource-override-dir`, which sets that
  environment variable for the child process.

Lookup policy:

1. if override directory contains the requested relative path, load that file;
2. otherwise, if override directory contains the requested basename, load that
   file;
3. otherwise fall back to the normal archive-backed lookup.

## Likely patch points

The override intercepts the existing `FileSystem::OpenPath(..., false)` path
before archive lookup. That keeps the patch confined to the headless runtime
and avoids coupling the mutator or corpus code to PBG3 packing.

## Validation note

On August 22, 2026, a Stage 6 run with a zero-byte overridden
`data/ecldata6.ecl` exited with `SIGSEGV` (exit 139), while the same override
mechanism pointed at the original extracted `ecldata6.ecl` completed normally.
So the override path is live and already yielded a first malformed-ECL crash
case worth minimizing.
