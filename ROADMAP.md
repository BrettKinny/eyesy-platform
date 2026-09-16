# Roadmap

Updated 2026-09-16 after two scene-library batches. Point of this file: a
fresh session starts here and knows what is done, what is next, and where
the evidence lives.

## Where things stand

- The device runs `dev-fd196b8b39cf` (27 modes: 7 reference + 20 library
  scenes), direct KMS engine (`--kms`), hardware GL (`VC4 V3D 2.1`) at
  ~60 fps, no Xorg in the display path. Rollback via `previous.json` is
  live-proven in both directions. Boot ownership is the platform.
- Scene library: batches 1-2 shipped (2026-09-15/16) — 20 new scenes
  across 11 families, all tier-measured on device; conventions and tier
  table in `docs/SCENE-LIBRARY.md`; research corpus in `docs/research/`
  (15 docs); blueprint and batch plans under `local/reports/`.
- The black-screen bug is closed (V1/V2; `docs/HDMI-DISPLAY-ISSUE.md`).
- 2026-09-15 bench session (`local/reports/bench-2026-09-15/REPORT.md`):
  rollback qualified in all four paths (incompatible-previous rejection,
  stock, and KMS↔KMS both directions); recovery path qualified unattended
  (no-sink engine failure → start-limit → `OnFailure` → stock, ~9 s; platform
  recovery with sink present); legacy Xorg conf removed with the verified
  remount dance; `bootstrap --arm` arch defect fixed (single-arch amd64
  slim digest → multi-arch OCI index + `EXPECTED_ARCH` build-time assertion).
- Release manifests still carry `hardware_validated: false` — the remaining
  gates below decide when that flips.

## Next work, in order

1. **Track B: `milkdrop-engine` — SHIPPED 2026-09-16** (deployed
   `dev-e46f786ab44d`, 28 modes, 10/12 presets tier C, glow pair waived —
   see docs/SCENE-LIBRARY.md). Further Track B work (variant pass, tier
   tuning) is deferred. Original scope: one Lua engine
   loading MilkDrop preset parameter JSONs as variants — per-frame
   equations -> Lua (tiny AVS-expression evaluator), per-pixel warp ->
   ~30 canonical ES2 fragments, comp -> display pass, blur -> multi-tap
   gather. Source: milkdrop2077/MilkDrop3 (BSD-3). Plan:
   `local/reports/batch2-plan/PLAN.md` Track B; licensing note: community
   preset packs are third-party artwork — user-supplied content unless
   cleared.
2. **Variant pass**: saved-scene JSONs per family (palette/regime/motion
   axes) — the cheap path from 27 engines+scenes to the 100+ target.
   QC: per-scene tier assertion + contact sheet per batch.
3. **Backlog scenes**: flame variations (published fractal-flame math
   only — flam3 is GPL-3.0, no transliteration), DLA growth, Buddhabrot-
   lite accumulation, Whitney fans, Lissajous weaver.
4. **Physical bench acceptance** (`docs/BENCH-CHECKLIST.md` sections 3–4,
   6): knobs/trigger/scene/MIDI, known stereo signal through the codec,
   visible-latency feel across all 27 modes. Needs hands.
5. **Full-formality 60-min soak rerun** with an **observe-only poller**
   (status.json `rss_bytes` + thermal temp at ~5 s — not `soak_guard.py`,
   which kills its target; `tools/soak_guard.py:92-103`). The 27-mode
   library changes what "formality" means: per-mode p50s are already
   recorded in `docs/SCENE-LIBRARY.md`.
6. **Cold-boot recovery confirmation**: one user power-cycle after the
   no-sink failure → stock → platform sequence.
7. **Tooling follow-ups**: supported re-entry after `rollback --target
   stock` (activate refuses installed dirs); engine should exit 0 on
   SIGTERM (exits 1 today, spuriously firing `OnFailure`); KMS mode
   chooser falls back to `modes[0]` silently
   (`engine/src/kms_window.cpp:253-263`) — make it loud;
   recovery-vs-fallback race ends the fallback unit FAILED (benign,
   convergent).
8. **1080p — NOT PURSUED** (user decision, 2026-09-15; analysis parked in
   `local/reports/1080p-plan-2026-09-15/`). Revisit only if re-raised.
9. **Optional upstreamable bisect**: D1/D2 protocol in
   `docs/HDMI-DISPLAY-ISSUE.md` (Xorg latches HDMI_VID_CTL bit 25).
10. **Longer-term**: read-only restoration qualification after apt changes,
   fully pinned package acquisition, engine features per `docs/CREATIVE.md`.

## Bench infrastructure cheat sheet

- Capture dongle: HPD follows its UVC streaming state. Run exactly one
  streamer for the whole observation window
  (`ffmpeg -f v4l2 -input_format mjpeg -framerate 30 -i /dev/video2 -vf
  fps=1 -y /tmp/dongle/live/f%06d.png`); two UVC clients kill each other.
  Frame numbers in the PNG stream drift from wall time — locate evidence by
  pixel content (signalstats YAVG), and remember signalstats frame numbers
  are 0-based while filenames start at 1.
- Dongle output states: RGB(0,0,0) = no TMDS; uniform RGB(7,7,7) = sync
  present, pixels blanked (the latched state); anything else is content.
- Latch oracle: `tools/vidctl_watch.sh` (~10 Hz `HDMI_VID_CTL` log; healthy
  `0xc0000000`/`0xc0080000`, latched `0xc2000000`).
- Device tools restage after every boot (`/tmp` is tmpfs):
  `/tmp/xlib-vendor` (python-xlib wheel), `tools/rr_hdmi.py`,
  `tools/rr_flags.py`, `tools/xshot.py`.
- Device facts: `sudo -n` works; `/` is read-only (remount dance for
  `systemctl enable/disable`); device clock drifts ~2 days at boot until
  sync — trust `uptime -s` after sync; assistant must not reboot the device
  (user power-cycles); stop-then-start services (restart races vt/DRM
  master).

## Session log

- 2026-09-16 (later): Track B shipped and deployed (`dev-e46f786ab44d`,
  28 modes, 60.3 fps KMS path). One milkdrop engine, 12 self-authored
  presets, built by tower task agents against
  `local/reports/trackB-plan/BRIEF.md`. Device tier evidence per preset:
  10/12 tier C, glow pair waived (docs/SCENE-LIBRARY.md). QC caught five
  real defects by measurement (clamp off-by-one, comp_glow centering +
  gather count, blur1 texel inversion, per-point env sync). Tooling:
  headless-test/benchmark --replay passthrough for in-mode preset tiers;
  staging cleanup on success. BeatDrop-fork portables assessed
  (docs/research/BeatDropForkPorting.md) for the next engine round.
- 2026-09-13: first live activation; black screen observed through the
  then-unqualified capture chain; two service fixes (DPMS, eyesyhw Wants=).
- 2026-09-14: observer chain qualified (HPD↔streaming coupling found);
  A/B isolated Xorg; register root cause (`HDMI_VID_CTL` bit 25, sticky
  across clients until power-off); remediation plan drafted.
- 2026-09-15: direct KMS/GBM backend implemented, built, deployed; V1 and
  V2 hardware validation passed; boot ownership now platform.
- 2026-09-15 (later): bench qualification session — rollback all paths,
  recovery-path test, provision hygiene, bootstrap arch fix, second KMS
  release deployed, 53.7-min partial soak (+248 KiB), 1080p viability
  assessed. Evidence: `local/reports/bench-2026-09-15/`.