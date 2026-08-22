# Stage 2 `time-set-zero` stall

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane. A `time-set-zero` mutation on
`ecldata2.ecl` drives the headless runtime into a stable stalled-progress case:

- headless trace freezes around frame `1226`;
- `stage_vm.loaded` flips false while `ecl_timeline.time` stays pinned near the
  same value;
- the exact minimized payload is now tracked as a compact
  `payload_patch.json`, so the finding no longer depends on ignored artifacts.

Use the local baseline corpus plus the tracked patch to rebuild the exact
triggering payload and rerun the case:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-time-set-zero-stall/reproduce.py
```

To also drive the rebuilt payload through retail Practice Stage 2 under Wine:

```sh
PYTHONPATH=src python3 findings/semantic/stage2-time-set-zero-stall/reproduce.py \
  --retail
```

Current local evidence:

- source semantic case:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-boss-sweep-smoke/ecldata2/0004-time-set-zero-s24-i0012/result.json`
- minimized summary:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/semantic-minimized/0004-time-set-zero-s24-i0012/summary.json`
- tracked exact payload patch:
  `findings/semantic/stage2-time-set-zero-stall/payload_patch.json`
- retail probe report:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-retail-run-stage2-time-set-staticprobe/report.json`

Current interpretation:

- headless: clearly interesting (`stalled-progress` / `stalled-frame`);
- retail: currently reaches `game-window-live`, not a crash, and the August 22,
  2026 screenshot probe still showed visible pixel changes instead of a fully
  static frame.
