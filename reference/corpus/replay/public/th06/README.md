# Public TH06 replay corpus

This directory keeps the reproducible source-of-truth for the small public TH06
replay corpus used by the replay semantic lane.

The `.rpy` binaries themselves are not tracked in git. Instead, keep:

- the public source URLs;
- expected file size and sha256;
- expected replay metadata relevant to the lane (`difficulty`,
  `shottype_chara`, and populated stage slots).

Rebuild the corpus into the default artifact directory with:

```sh
PYTHONPATH=src python3 -m danmakufuzz.corpus.fetch_public_replays \
  --manifest reference/corpus/replay/public/th06/manifest.json \
  --output-dir artifacts/replay-corpus-public/th06
```

That fetcher validates the replay checksum and verifies the expected populated
stage slots, so later replay-lane runs do not silently drift if a public source
changes.

Use the resulting corpus with the multi-stage replay runner:

```sh
PYTHONPATH=src python3 -m danmakufuzz.semantic.replay_corpus_campaign \
  --input-dir artifacts/replay-corpus-public/th06 \
  --limit-replays 3 \
  --limit-stage-slots 6 \
  --limit 6 \
  --continue-after-hit \
  --trace-compact-counts
```

`replay_corpus_campaign` is the intended entrypoint for full-game public
replays because it fans one `.rpy` out into per-stage tasks. The lower-level
`replay_desync_campaign --input ...` path is still useful for a single-stage
replay or an already isolated stage payload.
