# Automated bench acceptance — 2026-09-18

Device: CM3+ spare, <device-ip>, release `dev-8fcb282d8437` (41 modes),
renderer `VC4 V3D 2.1`, direct KMS, 720p60. Observer: the Guermok USB2 HDMI
capture dongle streaming continuously (`local/hdmi/latest.png`).

`tests/device_bench_auto.py` drives the deployed instrument over OSC + ALSA
(from the device itself), reads `status.json`, watches the HDMI capture, and
snapshots frames. It covers what needs no hands; the physical items stay manual
(see `docs/BENCH-CHECKLIST.md`). Machine-readable receipt and key frames are in
this directory (`summary.json`).

```
python3 tests/device_bench_auto.py --host <device-ip> \
    --output local/reports/device-bench-2026-09-18
```

**Result: `Bench automation passed` — 7 gates, 46 captures.**

| Gate | Asserted | Measured |
| --- | --- | --- |
| 00 idle baseline | `starter`, menu closed, sequencer stopped, `mode_errors` 0, `fps` > 20 | 60.0 fps, 41 modes, `hud_draw_calls` 9 |
| 01 latch oracle | `HDMI_VID_CTL` never `0xc2…` across 24 samples | only `0xc0000000` |
| 02 MIDI CC → knobs | CC 20–24 = 0 then 127 move the HUD knob sliders | 2458 px change in the slider region |
| 03 MIDI notes | notes 60/62/64 latch the engine's own hardware-test MIDI row | `diagnostics.midi` true |
| 04 MIDI transport | start/continue/clock/stop accepted without error | `mode_errors` 0 |
| 05 MIDI reconnect | dropping/re-adding the source disturbs nothing | `mode_errors` 0, LED 7 |
| 06 catalog render smoke | every mode loads, renders non-blank, and differs | 41/41 modes, 41 distinct frames |
| 07 final idle | left on `starter`, idle, menu closed | 60.3 fps |

## Findings

1. **`kirlian-aura` is broken in the deployed release** — `modes/kirlian-aura/`
   ships `main.lua` referencing `kirlian.frag`, but the fragment is absent, so
   the mode errors on load (`[ error ] mode: setup: shader file missing`).
   Already fixed in the pack (`eyesy-modes-bespoke/kirlian-aura/kirlian.frag`,
   2026-09-18); a redeploy clears it. The harness records it as a known-broken
   exclusion and still fails on any *other* mode error.
2. **MIDI input degrades over a long session.** On a freshly started engine,
   held notes light the HUD MIDI grid and CC moves the knob sliders. After the
   engine has been running a while and has seen many transient ALSA clients
   (each `aplaymidi` invocation is one), MIDI events stop being applied even
   though the connection forms (`aconnect -l` shows `aplaymidi → EYESY
   Platform`); an engine restart restores it. The likely cause is
   `pollMidi()`'s client-set reconciliation in `engine/src/main.cpp`: whenever
   the subscribed set changes it runs `midi.notes.fill(0)`, so a held note is
   cleared within one 2 s scan, and repeated client churn keeps the set
   unstable. Worth a follow-up: only clear the *stale* notes, or debounce the
   client-set change. The bench harness therefore reads MIDI on a fresh engine
   (notes via the latching `diagnostics.midi`, CC via the capture diff).

## Not covered here (needs hands or a signal source)

Physical knob/button feel, a known stereo line-in signal through the WM8731
codec, and HDMI-visible latency. See `docs/BENCH-CHECKLIST.md` §3–4, §6.
