# 60-minute observe-only soak — 2026-09-16

**Release:** `dev-b5cf00d32b6c` (28-mode catalog), engine sha256 `3b08774a…`
(byte-identical to `dev-0cae3aba9192`). **Conditions:** direct KMS scanout
1280x720@60 (CRTC-verified, `VID_CTL 0xc0000000`), sink-present start per the
new boot rule, capture dongle EDID (1080p-capable sink, 720p chosen by the
mode chooser), no streamer held during the run (HPD toggling — proven harmless
to a correctly-started engine). **Tooling:** `tools/soak_observe.py`
(observe-only: samples status.json + thermal at 5 s, OSC /key 5 mode switch
every 120 s; never signals or kills the engine — ROADMAP item 5). Data:
`local/soak-2026-09-16-samples.jsonl` (720 samples, 3595 s, single monotonic
series; stale 7-line prefix from a killed pre-fix instance trimmed on device).

## Results

| Metric | Value | Assessment |
| --- | --- | --- |
| RSS | first-window median 70.2 MB → last 72.0 MB; peak 72.9 MB | **+1.8 MB nominal**, but see same-mode analysis |
| Same-mode RSS | starter 69.75→71.97 MB, stereo-mesh 69.88→72.19 MB (t=0→3480) | **genuine growth ≈ +2.2 MB/h ≈ 73 KB per reload** (30 reloads) |
| Thermal | min 51.5, median 53.7, max 55.8 °C | flat, ~28 °C below throttle |
| fps | median 44.1 overall; starter/stereo-mesh/prism-mesh 60.3 | matches recorded tier table exactly (tier C scenes 34–49 fps) |
| mode_errors | 0 | clean |
| Modes visited | all 28, 24 samples each (starter/stereo-mesh 47–49 via wrap) | full catalog exercised |

## Findings

1. **Stability: pass.** Zero mode errors, zero crashes, no service restarts,
   thermal flat, backbone scenes at 60.3 fps over the full hour.
2. **Memory growth is real but small and mode-reload-correlated.** +2.2 MB/h
   measured on repeat visits of the *same* mode (rules out mode-dependent
   baseline confounds). ≈73 KB/reload × 30 reloads. Prior bench soak
   (+248 KiB/53.7 min, fewer switches) ran ~4.6 KB/min vs ~38 KB/min here.
   Over a 3 h session this is ~7 MB — not a threat, but a regression vs the
   previous rate worth attribution: candidate causes are per-reload
   LuaJIT/allocation churn (30 reloads this run) and the milkdrop engine's
   preset JSON loads (new since the last soak). **Follow-up:** rerun with
   switching disabled vs enabled to separate time-leak from reload-leak.
3. **fps per mode matches `docs/SCENE-LIBRARY.md` tiers** — the live-service
   measurements reproduce the tier table (e.g. radar-sweep 49.0 fps ≈ 23.8 ms
   recorded; milkdrop 38.3 fps ≈ 26 ms, tier C). No tier regressions.

## Gate status

ROADMAP item 5 (full-formality soak with observe-only poller): **done**.
Remaining gates for `hardware_validated`: physical bench items (BENCH-CHECKLIST
§3/4/6), cold-boot recovery confirmation, and the leak-attribution follow-up
above (advisory, not a gate).
