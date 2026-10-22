# Roadmap

What the platform does today, and what is still open. For the detail behind the
"done" list, see [implementation status](docs/STATUS.md).

## Done

- **Engine.** C++17 openFrameworks 0.12.1 with embedded LuaJIT, the v1 Lua mode
  API, stereo audio analysis, MIDI, OSC, scenes, palettes, shaders, meshes and
  render targets. Desktop and ARM builds.
- **Display.** A direct KMS/GBM scanout backend with hardware GL on the CM3+
  (`VC4 V3D 2.1`) at 720p60. Xorg is gone from the display path, after any Xorg
  session was found to leave HDMI blanked until a power cycle
  ([HDMI display issue](docs/HDMI-DISPLAY-ISSUE.md)).
- **Instrument layer.** EYESY OS v3 parity: trigger-button audio synthesis,
  the shift shortcuts, the knob sequencer, persist (`ctx.auto_clear`), the
  stock-layout HUD, the 43 stock cosine palettes and a fullscreen settings menu
  ([parity plan](docs/EYESY-OS-V3-PARITY-PLAN.md)).
- **Release tooling.** Byte-reproducible packages with build provenance,
  versioned releases that record their platform and pack commits (published
  as GitHub pre-releases from v0.1.0), transactional deploy, rollback to the previous release or to stock, and an
  `OnFailure` fallback that hands the instrument back to stock.
- **Hardware qualification so far.** Deploy and rollback in all four paths;
  unattended recovery to stock when the engine fails with no display attached;
  a 60-minute observe-only soak; the automated half of the bench checklist
  (HDMI latch oracle, MIDI CC/notes/transport/reconnect, a 41-mode render
  smoke); and the 13-step OS v3 parity suite.
- **Mode packs.** The engine repo ships only `starter`. Other modes live in
  their own repos and are assembled with `./eyesyctl modes sync`:
  [eyesy-modes-factory](https://github.com/BrettKinny/eyesy-modes-factory)
  (ports of the stock library) and
  [eyesy-modes-milkdrop](https://github.com/BrettKinny/eyesy-modes-milkdrop)
  (a MilkDrop-style preset engine).

## Open

### Hardware acceptance

Release manifests carry `hardware_validated: false` until these manual checks
pass ([bench checklist](docs/BENCH-CHECKLIST.md)):

- Knob and button feel, and settings changes, on the physical controls.
- A known stereo signal through the line input: channel separation and
  response.
- HDMI-visible latency on a real display.
- Cold-boot recovery: a power cycle after a no-display engine failure, checking
  the instrument comes back through stock to the platform.

### Hardware and output coverage

- **CM4.** Only the CM3+ has been tested.
- **Composite video.** Not offered; scanout is HDMI-only direct KMS.
- **Native 1080p.** EDID 1080p modes are reachable, but several modes already
  miss 60 fps at 720p. Rendering stays at 720p unless that changes.

### Stock features not yet ported

- **Wi-Fi setup and the web editor.** The platform is managed from a
  workstation over SSH with `eyesyctl`; the stock web editor still controls the
  stock engine only.
- **Menu screens.** The menu has Video, Audio & MIDI, Palettes and Hardware
  test. Stock's Wi-Fi, MIDI program-change mapping, backups, logs and flash
  drive screens are not ported.
- **USB modes.** Stock loads modes from `/usbdrive/Modes` in place of the SD
  card. The platform does not.

### Engine

- **Memory growth.** One early soak measured same-mode RSS growth of about
  2.2 MB/h, correlated with mode reloads. On v0.1.3, a no-switching baseline
  and 1,188 rapid reloads (Lua and MilkDrop modes) showed no growth after
  warm-up. What remains is a multi-hour soak across the whole catalog.
- **Persist adoption.** Done in the factory pack (79 of 87 ports) and
  checked by `tools/scene_verify.py`. MilkDrop treats feedback as its own
  persistence; whether Persist should change its decay is open.

### Platform hardening

- **Read-only root after provisioning.** The provisioner remounts `/`
  read-write, runs apt, and remounts it read-only. On the first live run the
  read-only remount failed after apt and a reboot was needed. Failure is now
  reported as a nonzero exit, but a live run that restores `ro,noatime` in the
  same invocation has not been qualified.
- **Pinned apt packages.** The build base image and SDK are pinned by digest,
  and installed package versions are recorded in the build provenance. The apt
  repositories behind the build container and the provisioner still float, so
  a rebuild on a later date can resolve newer packages.
