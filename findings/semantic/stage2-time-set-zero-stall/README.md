# Stage 2 `time-set-zero` stall

Observed on August 22, 2026.

This finding comes from the TH06 semantic lane. A `time-set-zero` mutation on
`ecldata2.ecl` drives the headless runtime into a stable stalled-progress case:

- headless trace freezes around frame `1226`;
- `stage_vm.loaded` flips false while `ecl_timeline.time` stays pinned near the
  same value;
- the minimized local payload currently lives under ignored artifacts, but this
  finding does not depend on that blob being present.

Use the local baseline corpus to rebuild the triggering payload and rerun the
case:

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
- retail probe report:
  `/home/yann/yann/touhou/DanmakuFuzz/artifacts/tmp-retail-run-stage2-time-set-staticprobe/report.json`

Current interpretation:

- headless: clearly interesting (`stalled-progress` / `stalled-frame`);
- retail: currently reaches `game-window-live`, not a crash, and the August 22,
  2026 screenshot probe still showed visible pixel changes instead of a fully
  static frame.
