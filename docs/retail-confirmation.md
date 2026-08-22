# Retail confirmation boundary

Headless execution is used for search throughput and structured triage.

Retail Wine confirmation remains required for:

- crash reproduction claims against the shipped game;
- behavioral divergence claims that depend on original runtime semantics;
- final bug reports worth carrying forward.

Retail state must stay isolated:

- dedicated game directory;
- dedicated Wine prefix and display;
- dedicated artifact root;
- no sharing with unrelated solver work.
