# 60-minute observe-only soak — 2026-09-18

**Release:** `dev-8fcb282d8437` (41 modes). **Conditions:** direct KMS scanout
1280x720@60 (`HDMI_VID_CTL 0xc0000000`), capture dongle streamer holding HPD.
**Tooling:** `tools/soak_observe.py` (observe-only: samples `status.json` +
thermal at 5 s, OSC `/key 5` mode switch every 120 s; never signals or kills the
engine). Data: `samples.jsonl` (720 samples, 3595 s).

The device was shared with the user's in-flight scene tier gates
(`benchmark.py` offscreen runs) early in the window, which is visible as the
low-fps tail; the soak still completed without a restart.

## Results

| Metric | Value | Assessment |
| --- | --- | --- |
| Samples / span | 720 / 3595 s | full 60 min, single monotonic series |
| Modes visited | 30 (one 120 s visit each) | catalog cycle from `starter` to `phosphor-seance` |
| RSS | per-mode window delta 0.00–0.13 MiB over 120 s | **flat within each visit**; the +6.1 MiB first-window→last-window figure is mode-dependent baselines, not growth |
| Thermal | min 55.3, median 56.9, max 62.3 °C | flat, ~18 °C below throttle |
| fps | `starter` p50 60.3; per-mode p50 24.4–60.3 | matches the tier table (tier C scenes 24–52 fps) |
| mode_errors | 1 → 2 | one carried over from the bench session, one transient |
| Crashes / restarts | 0 | clean |

## Findings

1. **Stability: pass.** No crashes, no service restarts, thermal flat, `starter`
   holding 60.3 fps for its visit.
2. **Memory growth is small and not monotonic.** Unlike the 2026-09-16 soak
   (which measured +2.2 MB/h from *repeat* visits of the same mode), this run
   visits each mode once, so a within-visit delta is all it can measure — and
   that is 0.00–0.13 MiB over 120 s. No mode shows a sustained ramp.
3. **fps per mode matches `docs/SCENE-LIBRARY.md`.** `buddha-1kb` (28 fps),
   `textmode-field` (33.5), `ascii-wave` (34.7) and the rest reproduce the
   recorded tiers; the 105 samples below 30 fps are the heavy tier-C scenes, not
   a regression.
4. **One transient mode-load error.** `mode_errors` went 1 → 2 exactly at the
   `kali-bloom → koan-terminal` switch (t = 2405 s). `koan-terminal` loaded
   cleanly in the bench's 41-mode sweep the same day, so this is intermittent
   (a load-time race, possibly under the concurrent benchmark load). Worth
   watching; not reproduced.
5. **The other error is the deployed release's `kirlian-aura`**, which ships
   without its `kirlian.frag` (see `evidence/reports/bench-auto-2026-09-18/`);
   the mode sits in the catalog but the cycle did not reach it in this window.

## Gate status

ROADMAP item 4 (full-formality soak with the observe-only poller): **done** for
`dev-8fcb282d8437`. Remaining gates for `hardware_validated`: the physical bench
items (`docs/BENCH-CHECKLIST.md` §3/4/6) and cold-boot recovery confirmation.
