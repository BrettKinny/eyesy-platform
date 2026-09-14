# Roadmap

Updated 2026-09-15 after the black-screen fix shipped and passed V1/V2 on
hardware. Point of this file: a fresh session starts here and knows what is
done, what is next, and where the evidence lives.

## Where things stand

- The device boots into a working platform: release `dev-cf8b1ee8013f`,
  direct-KMS engine (`--kms`), hardware GL (`VC4 V3D 2.1`) at ~60 fps, no
  Xorg anywhere in the display path. Boot ownership is the platform.
- The original "boots into a black screen" bug is root-caused, fixed, and
  hardware-validated (V1 handoff/recovery, V2 platform-owned cold boot; see
  `docs/HDMI-DISPLAY-ISSUE.md` and `docs/STATUS.md`). The device-side story
  is closed: Xorg latched an undocumented `HDMI_VID_CTL` bit; the engine now
  never touches Xorg and only uses kernel-EDID modes.
- Release manifests still carry `hardware_validated: false` — the remaining
  gates below decide when that flips.

## Next work, in order

1. **Bench acceptance on the deployed service** (`docs/BENCH-CHECKLIST.md`
   sections 3–6): physical knobs/trigger/scene/MIDI behavior, known stereo
   signal through the codec, visible-latency feel, and the 60-minute soak
   with 500-switch memory measurement. This is the main remaining gate
   before the platform can be called a stock replacement.
2. **Rollback qualification** — for the first time two healthy platform
   releases exist (`dev-dd42a1d3bd86` previous, `dev-cf8b1ee8013f` current),
   so `eyesyctl rollback --target previous` is now exercisable per the
   checklist section 5; it was impossible before.
3. **Recovery-path verification on the KMS service**: induce engine failure
   (e.g., launch with no HDMI sink) and confirm `OnFailure` restores stock;
   then confirm a subsequent platform boot recovers. Note the engine
   correctly fails its connector probe when no display holds HPD.
4. **Infrastructure defect: `bootstrap --arm` builds wrong-arch images.** On
   this host the digest-pinned Debian base resolves to amd64 content inside
   a `linux/arm`-tagged image; the build then produces amd64 binaries. The
   working armhf image was recovered from dangling layers
   (`a450cfc9f3f0` + a derived image with `libdrm-dev libgbm-dev`). Fix the
   bootstrap (unpin the digest or use `--platform`), then rebuild both
   images and re-verify `eyesyctl build --arm` from scratch.
5. **Provision hygiene**: `/etc/X11/xorg.conf.d/10-eyesy-720p.conf` still
   sits on the device (a 2026-09-13 removal silently failed on the read-only
   root). It is inert for the platform now, but provision should remove or
   mask it, and removal must verify, not assume.
6. **Optional root-cause bisect (upstreamable):** the D1/D2 protocol in
   `docs/HDMI-DISPLAY-ISSUE.md` identifies exactly which Xorg action latches
   `HDMI_VID_CTL` bit 25 (prime suspect: the degenerate empty-name/zero-flags
   mode blobs). Not needed for the product; valuable for a
   raspberrypi/xserver report.
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