# Roadmap

Updated 2026-09-15 after the bench qualification session (rollback, recovery
path, provision hygiene, bootstrap arch fix, partial soak). Point of this
file: a fresh session starts here and knows what is done, what is next, and
where the evidence lives.

## Where things stand

- The device runs `dev-c2f150be2380` (built by the fixed bootstrap), direct
  KMS engine (`--kms`), hardware GL (`VC4 V3D 2.1`) at ~60 fps, no Xorg in
  the display path. `previous.json` → `dev-cf8b1ee8013f`, so
  `rollback --target previous` is live-proven in both directions between
  healthy KMS releases. Boot ownership is the platform.
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

1. **Physical bench acceptance** (`docs/BENCH-CHECKLIST.md` sections 3–4,
   6): knobs/trigger/scene/MIDI, known stereo signal through the codec,
   visible-latency feel. Needs hands; everything remote-drivable is done.
2. **Full-formality 60-min soak rerun**: today's deployed-service soak was
   stopped early at 53.7 min / 446 of 500 switches (memory growth +248 KiB,
   zero mode errors/drops) — rerun once to close the formality.
3. **Cold-boot recovery confirmation**: one user power-cycle after the
   no-sink failure → stock → platform sequence (service-level recovery is
   already live-proven).
4. **Tooling follow-ups found during the bench session**:
   - supported re-entry after `rollback --target stock` (activate refuses
     installed dirs; today required manual `reselect_cf8b.py`);
   - engine should exit 0 on SIGTERM (today it exits 1, so routine stops mark
     the unit failed and spuriously fire `OnFailure`);
   - KMS mode chooser silently falls back to `modes[0]`
     (`engine/src/kms_window.cpp:253-263`) — make the fallback loud;
   - recovery-vs-fallback race: `restore_selection`'s stop of a restarting
     unit fires `OnFailure`, whose stock start then gets canceled by
     `Conflicts` (benign, convergent, but the fallback unit ends FAILED).
5. **1080p decision** (`local/reports/1080p-plan-2026-09-15/analysis.md`):
   scanout is reachable (EDID exposes 1080p), but native 1080p60 is not
   viable for 4/7 modes (they already miss 60 fps at 720p; ~15–25 fps
   projected). Recommended: keep 720p render resolution; if pursuing
   sharpness, start with the agent's fill-scaling calibration + offscreen
   1080p cost pass.
6. **Optional root-cause bisect (upstreamable):** the D1/D2 protocol in
   `docs/HDMI-DISPLAY-ISSUE.md` identifies exactly which Xorg action latches
   `HDMI_VID_CTL` bit 25. Not needed for the product.
7. **Longer-term items** from `docs/STATUS.md` gates: read-only restoration
   qualification after apt changes, fully pinned package acquisition, and
   (later) engine features per `docs/CREATIVE.md` / `03-of-lua-engine.md`.

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