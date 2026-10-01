# Roadmap

Updated 2026-09-16 after two scene-library batches. Point of this file: a
fresh session starts here and knows what is done, what is next, and where
the evidence lives.

**Where evidence lives (2026-09-17 split).** The scene catalog and its material
moved out of this repo into `eyesy-modes-bespoke`, `eyesy-modes-milkdrop` and
`eyesy-modes-factory`. Paths written as
`local/reports/...`, `local/<run>/...` or `docs/research/...` in the dated
entries below were correct when the entry was written. Scene material now
resolves as:

- design docs -> `eyesy-modes-bespoke/docs/` (bardo-night briefs, scene-library
  blueprint, batch-2 plan), `eyesy-modes-milkdrop/docs/trackB-plan/`
- per-scene evidence (summary + contact sheet) -> kept privately, outside the public repos
- research corpus -> `eyesy-modes-*/docs/research/` (see `docs/research/README.md`)
- raw verification runs and optimization sandboxes -> deleted 2026-09-17
  (regenerable harness output; the durable parts are the two lines above)
- platform/engine evidence (bench, HDMI, soak, bootstrap, the overnight
  rounds) is kept privately, outside the public repos; `local/` is scratch

## Where things stand

- The device runs `dev-f1ad163561e9` (92 modes across `bespoke`, `factory`,
  and `milkdrop`), carrying the OS v3 instrument layer and the live
  automatic `scenes/` directory rescan; `previous.json` points at
  `dev-8fcb282d8437`. Direct KMS engine (`--kms`), hardware GL (`VC4 V3D 2.1`)
  at ~60 fps, no Xorg in the display path. Rollback via `previous.json` is
  live-proven in both directions. Boot ownership is the platform.
- Scene library: batches 1-2 shipped (2026-09-15/16) — 20 new scenes
  across 11 families, all tier-measured on device; conventions and tier
  table in `docs/SCENE-LIBRARY.md`; research corpus in the mode-pack repos
  (see `docs/research/README.md`); blueprint and batch plans in
  `eyesy-modes-bespoke/docs/`.
- The black-screen bug is closed (V1/V2; `docs/HDMI-DISPLAY-ISSUE.md`).
- 2026-09-15 bench session:
  rollback qualified in all four paths (incompatible-previous rejection,
  stock, and KMS↔KMS both directions); recovery path qualified unattended
  (no-sink engine failure → start-limit → `OnFailure` → stock, ~9 s; platform
  recovery with sink present); legacy Xorg conf removed with the verified
  remount dance; `bootstrap --arm` arch defect fixed (single-arch amd64
  slim digest → multi-arch OCI index + `EXPECTED_ARCH` build-time assertion).
- Release manifests still carry `hardware_validated: false` — the remaining
  gates below decide when that flips.

## Next milestone

**EYESY OS v3 parity** — [the parity plan](docs/EYESY-OS-V3-PARITY-PLAN.md).

All five phases are implemented and verified: trigger-button audio synthesis,
the shift-button shortcuts (palette cycling, in-place scene update, hold-to-delete,
gain takeover), the key repeater, the knob sequencer with scene persistence,
`ctx.auto_clear` with the two-mode persist pilot, the stock-layout instrument HUD,
the cosine palette system, and a fullscreen configuration menu. Hardware receipts
(captured off the HDMI dongle) and the measured corrections to the plan are in
`docs/EYESY-OS-V3-PARITY-PLAN.md` §7; the automated 13-step device suite was
re-run green on 2026-09-18 and left the bench scene directory clean.

Still open, deliberately: the fleet-wide persist veil rewrite (only the
`starter`/`stereo-mesh` pilot modes carry it), USB storage override, and stock's
WiFi / MIDI-PC-mapping / backup / log menu screens (the platform owns those
through `eyesyctl`).

## Next work, in order

1. **Track B variant & performance pass** — `milkdrop-engine` shipped
   2026-09-16 (deployed `dev-e46f786ab44d`, 28 modes, 10/12 presets tier C,
   glow pair waived — see docs/SCENE-LIBRARY.md); the remaining work is the
   variant pass and tier tuning. Saved-scene JSONs per family
   (palette/regime/motion axes) are the cheap path from 27 engines+scenes to
   the 100+ target. QC: per-scene tier assertion + contact sheet per batch.
   Original scope: one Lua engine loading MilkDrop preset parameter JSONs as
   variants — per-frame equations -> Lua (tiny AVS-expression evaluator),
   per-pixel warp -> ~30 canonical ES2 fragments, comp -> display pass,
   blur -> multi-tap gather. Source: milkdrop2077/MilkDrop3 (BSD-3). Plan:
   `eyesy-modes-bespoke/docs/batch2-plan/PLAN.md` Track B; licensing note:
   community preset packs are third-party artwork — user-supplied content
   unless cleared.
2. **Scene library expansion**: flame variations (published fractal-flame math
   only — flam3 is GPL-3.0, no transliteration), DLA growth, Buddhabrot-lite
   accumulation, Whitney fans, Lissajous weaver.
3. **Physical bench acceptance** (`docs/BENCH-CHECKLIST.md` sections 3–4, 6):
   the automated half landed 2026-09-18 (`tests/device_bench_auto.py`: latch
   oracle, MIDI CC/notes/transport/reconnect, 41-mode render smoke). What remains needs hands:
   physical knob/button feel, a known stereo line-in signal through the codec,
   and HDMI-visible latency.
4. **Full-formality 60-min soak** with the **observe-only poller** — **done
   2026-09-18** on `dev-8fcb282d8437` (720 samples, 30 modes, flat thermal,
   flat per-mode RSS). Re-run after any
   engine change: `tools/soak_observe.py` (status.json `rss_bytes` + thermal at
   ~5 s; never `soak_guard.py`, which kills its target).
5. **Cold-boot recovery confirmation**: one user power-cycle after the
   no-sink failure → stock → platform sequence.
6. **Engine tooling & robustness**: the `scenes/` re-scan and the
   recovery-vs-fallback race are fixed (2026-09-18 — `engine/src/main.cpp`,
   `deploy/eyesy-platform-fallback.service`, `tests/test_fallback_unit.py`).
   Open: MIDI input stops being applied after a long session with many transient
   ALSA clients — `pollMidi()` runs `midi.notes.fill(0)` on every client-set
   change, clearing a held note within one 2 s scan; clear only stale notes.
   Landed 2026-09-16: SIGTERM exits 0, the KMS `modes[0]` fallback is loud
   (`engine/src/kms_window.cpp:253-263`), and `rollback --target stock`
   re-entry re-selects the installed release.
7. **Platform hardening**: read-only root restoration qualification after apt
   changes, fully pinned package acquisition, engine features per
   `docs/CREATIVE.md`.

Parked, not pursued:

- **1080p** — user decision 2026-09-15 (viability analysis in
  `docs/STATUS.md`). Revisit only if re-raised.
- **Optional upstreamable bisect**: D1/D2 protocol in
  `docs/HDMI-DISPLAY-ISSUE.md` (Xorg latches HDMI_VID_CTL bit 25).

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
  sync — trust `uptime -s` after sync; never reboot the device remotely
  (power-cycle it by hand); stop-then-start services (restart races vt/DRM
  master).

## Session log
- 2026-09-16 (later): scene verifier shipped (`tools/scene_verify.py`) —
  per-scene A/B contract harness over the engine's deterministic replay mode.
  Engine gained a deterministic `audio` replay event (gain/freq of the
  synthesized stimulus; main.cpp dispatch/synthesis + input_workflow.cpp
  validation, covered in tests/input_workflow_tests.py, whose negative-replay
  tests were also repaired — they used the long-removed `--probe` flag and
  could not have passed against the current engine). Metric: fraction of
  pixels differing at all (bit-deterministic engine ⇒ dead stimulus =
  byte-identical grabs = 0.0), mean-abs reported alongside; contact sheet per
  scene for the human pass. Full 29-mode catalog: 22 pass, 7 fail — each
  failure a specific finding: ascii-wave (knob2-max renders pure black; knob5
  pulse byte-dead), echo-feedback (near-blank output in every state, stddev
  0.06-0.38 — needs author eyes), lyapunov-field (speed knob byte-dead),
  outrun-grid (hue + drift declared but never referenced — source-confirmed;
  decay only marginally alive), radar-sweep + reaction-diffusion (zero audio
  response despite ctx.audio references), stereo-mesh (speed knob byte-dead).
  Evidence: `local/verify-catalog-2026-09-16/` (per-scene summary.json +
  contact-sheet.png + run-*/ evidence). Scene fixes await the next
  scene-library pass — note outrun-grid's dead hue/drift are visible quality
  knobs.
  Desktop engine rebuilt with the audio event; ARM engine needs
  `./eyesyctl build --arm` before the next device deploy.

- 2026-09-16 (later): stability batch (ROADMAP item 6) done and
  device-verified; deployed `dev-0cae3aba9192`. SIGTERM now exits 0
  (`Deactivated successfully`, no OnFailure; needed both the flag-driven
  exit in main.cpp AND an EINTR retry in the kms_window.cpp page-flip poll
  — desktop smoke missed the KMS-only path, caught live on device). KMS
  modes[0] fallback is loud (stderr + status.json `mode_fallback`;
  exercised live — current dongle EDID has no 720p, engine runs 720x480i).
  `rollback --target stock` → re-deploy same archive re-selects the
  installed release (sha256-verified, previous.json preserved). Fallback
  unit no longer starts stock blindly: state-gated poll (active→exit,
  failed→immediate handover, else 10 s wait); both branches verified live
  (healthy: no clobber; platform down: ~12.7 s → stock, success). Tests
  25/25. GIF research: docs/research/GIFModes.md — recommended path is
  offline GIF→PNG-frame transcode + existing image()/draw_image() blit;
  Lua decode blocked (no pixel-upload API); on-device video decode is a
  separate XL project. Capture note: blank RGB(7,7,7) after a service
  restart was NOT the VID_CTL bit-25 latch (register read 0x001c0000, bit
  25 clear) — the engine had been restarted while the dongle streamer was
  down, so it committed with the sink absent. Restart the engine with the
  streamer live → VID_CTL 0xc0000000 and live content on the capture
  (YAVG ~34, varied). The current dongle's EDID has no 720p, so the
  platform runs its 720x480i fallback mode; use the 720p dongle for
  720p60 visual work.

- 2026-09-16 (later): clean-checkout re-bench. Curated clean-checkout release
  `dev-b5cf00d32b6c` built (28-mode catalog verified in-package and on
  device; the fleet has since grown to 37 modes with the bardo night).
  Curated releases must build from a clean checkout — untracked
  `modes/milkdrop/` would otherwise be copytree'd into packages. Headless
  re-bench on real GPU: starter 60.00, stereo-mesh 60.00, prism-mesh and
  lyapunov-field also measured. NEW BOOT FACT (reproduced both ways,
  byte-identical binary): engine started while the sink is absent
  (HPD down — no streamer on the capture dongle) comes up degraded:
  VID_CTL 0x401c0000/0x001c0000, blanked pixels or ~51.8 fps flip
  pacing; persists after the sink appears and survives restarts of
  nothing but itself. Engine started with the sink live: VID_CTL
  0xc0000000, 60.4 fps, live content — even on the 480i fallback mode.
  Boot rule: power on / restart the platform ONLY with the display sink
  (or dongle streamer) already live. Not the bit-25 latch (bit 25 read clear
  throughout), not thermal (52.6°C), not the build.

- 2026-09-16 (later): item-4 soak done (60 min, observe-only
  `tools/soak_observe.py`, all 28 modes, 720 samples): zero errors, thermal
  flat 51.5-55.8 °C, backbone 60.3 fps, per-mode fps reproduces the tier
  table. One flag: same-mode RSS growth ≈ +2.2 MB/h (~73 KB/reload) — 8x
  the prior soak rate, reload-correlated (milkdrop preset loads are new);
  follow-up = switching-disabled vs enabled attribution run. Research: Buddhist × retro-CG
  scene backlog at `eyesy-modes-bespoke/docs/research/SacredRetroBuddhist.md`
  (flagship four:
  enso, kolam-knot, sri-yantra-exact, sand-dissolution; cultural flags
  documented).

- 2026-09-16 (later): Track B shipped and deployed (`dev-e46f786ab44d`,
  28 modes, 60.3 fps KMS path). One milkdrop engine, 12 self-authored
  presets, built by tower task agents against
  `eyesy-modes-milkdrop/docs/trackB-plan/BRIEF.md`. Device tier evidence per preset:
  10/12 tier C, glow pair waived (docs/SCENE-LIBRARY.md). QC caught five
  real defects by measurement (clamp off-by-one, comp_glow centering +
  gather count, blur1 texel inversion, per-point env sync). Tooling:
  headless-test/benchmark --replay passthrough for in-mode preset tiers;
  staging cleanup on success. BeatDrop-fork portables assessed
  (`eyesy-modes-milkdrop/docs/research/BeatDropForkPorting.md`) for the
  next engine round.
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
  assessed.