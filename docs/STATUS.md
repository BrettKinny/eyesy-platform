# Implementation status

Updated after the 2026-09-12 overnight iteration. This is a capable development
platform, **not yet a fully bench-qualified replacement for stock EYESY**.

## Implemented and regression-tested

- Desktop and ARM openFrameworks 0.12.1/LuaJIT builds; seven shipping modes:
  Starter, Stereo Mesh, Shader, Feedback, Aurora, Prism Mesh, and Echo Feedback.
- Named/custom palettes, reusable dynamic meshes, shaders, ping-pong feedback,
  reduced-resolution targets, parameter bindings, scenes, and screenshots.
- Stereo waveform/FFT/onset analysis, nonblocking audio ring, MIDI state,
  OSC decoding, soft takeover, and settings/menu implementation.
- Bounded WAV analysis input and frame-indexed input recording/replay. WAV is
  not physical sound output; recordings are controls, not complete audiovisual
  sessions. See [input workflow](INPUT-WORKFLOW.md).
- Lua/input/resource validation and error reporting without losing the render
  loop. Tests cover bad shaders, mode failures, malformed replay, WAV formats
  and bounds, palettes, and render-target orientation.
- Pixel tests caught and fixed invisible VBO line strips and nested-FBO vertical
  inversion. Both desktop and ARM builds contain the reviewed fixes.
- Deterministic desktop replay screenshots, WAV EOF behavior, and MIDI/control
  press/release semantics pass integration checks.
- Core tests pass AddressSanitizer, UndefinedBehaviorSanitizer, and leak checks.
  A three-million-frame producer/consumer ring stress test passes ThreadSanitizer.
- Verified archives, actual ELF architecture checks, safe extraction paths,
  payload-derived release IDs, byte-reproducible packaging, source/SDK/container
  provenance, and strict SSH host-key verification.
- Transactional activation and previous-release/stock recovery are tested using
  mocked services and real temporary filesystems. This is not live display-service
  deployment qualification.

## Evidence on the fresh spare card

Original SD card remains untouched. Device is CM3+, EYESY OS v3.0; no HDMI screen
is attached. Stock boot remains selected and platform services remain disabled.

- Fresh-card preparation, clone UUID, verified SSH access, dependency inventory,
  and disabled platform service installation succeeded. Apt initially prevented
  read-only remount; controlled reboot restored `ro,noatime`. Immediate post-apt
  cleanup remains a known provisioning limitation.
- Native Lua mode loading exposed a stock/build C++ runtime incompatibility.
  Matching `libstdc++` and `libgcc_s` are now private release libraries, resolved
  through `$ORIGIN/libs:$ORIGIN`. System libraries were not replaced.
- Self-contained ARM package ran all seven modes for 900 frames each on real
  `VC4 V3D 2.1`. No mode errors or shader warnings; short-run median RSS growth
  was zero. Per-mode frame-time medians ranged about 15.7–29.7 ms under shared
  load with stock video. **Not all modes sustain 60 fps.** These are offscreen
  measurements, not HDMI timing or isolated production performance.
- Bounded real capture probe: 1200 frames, 48 kHz, analysis sequence 1837,
  no ring drops, stock restored. No known external signal was supplied, so
  channel separation, musical response, signal quality, and latency are untested.
- Independent transient watchdog experiment: deliberately stopped engine was
  restarted after about 4.63 seconds; a new PID and advancing heartbeat were
  verified. Stock remained active. This does not qualify Xorg/production recovery.
- `eyesyctl headless-test` passed its complete verified-package upload → native
  GPU run → local diagnostic retrieval workflow. See [headless development](HEADLESS-DEVELOPMENT.md).
- Native generated-WAV analysis, EOF handling, recorded OSC control replay,
  deterministic replay PNGs, and MIDI event semantics passed on the packaged ARM
  engine. These use synthetic/replayed events, not physical MIDI equipment.
- The frozen seven-mode package passed a **78.6-minute native soak: 216,000 frames,
  1,800 reloads**, all seven modes observed, and no errors/warnings or audio-ring
  drops across 4661 sampled statuses. Post-warmup first/last-window median RSS
  increased by **80 KiB**; the independent guard observed a 76.4 MiB peak. SoC
  temperature peaked at 60.7°C. These are RSS measurements, not total GPU memory.
- The kernel's memory cgroup controller is disabled, making systemd `MemoryMax`
  ineffective. A direct PID-identity guard covered RSS/temperature/duration limits
  and exited without triggering. The revised guard's termination path was also
  tested against an isolated disposable process, not a stock service.

Evidence: `local/overnight/package-round3/`,
`local/overnight/hardware-round2/`, and `local/overnight/headless-cli-round1/`.
Native input workflow evidence is in `local/overnight/input-workflow-round1/`.
Full-run checks and memory analysis: `local/overnight/soak-round1/analysis.json`.
Final local regression log: `local/overnight/final-regressions-round2.log`
(five core executables, 77 Python checks, and five graphics integration scripts).
The [overnight log](OVERNIGHT.md) records the experiment sequence and caveats.

## 2026-09-13 live deployment and HDMI investigation

First live transactional activation succeeded on the spare card: release
`dev-dd42a1d3bd86` passed health (advancing frames, VC4 renderer, audio
capture with zero drops), `previous.json` was committed, and the `OnFailure`
fallback restored stock twice when activation failed. Two service defects
were found and fixed in `deploy/eyesy-platform.service`: X's default
10-minute DPMS blanking (server flags `-s -dpms` added) and teardown from an
`eyesyhw` boot race (`Requires=` relaxed to `Wants=`).

After activation, no image reaches the display through the HDMI→USB capture
chain, while stock SDL/KMSDRM output displays from any clean boot. The
platform side is verified healthy end to end (engine frames, X framebuffer
contents captured via XGetImage, active CRTC at EDID-preferred timings,
identity gamma, linear and tiled scanout, RandR re-modeset, fbcon on vt1);
the bad display state persists across master handover until reboot. See
[HDMI display issue](HDMI-DISPLAY-ISSUE.md) for the evidence table and ranked
next tests; the decisive unrun one is the same output on a real HDMI display.
Boot ownership was restored to stock for a known-good power-on.

## 2026-09-14 root cause: latched HDMI_VID_CTL bit under Xorg

With the capture dongle observed directly on the workstation (after
diagnosing and controlling its HPD↔USB-streaming coupling), the black-screen
bug is reproduced and explained: any Xorg session on the card trips a sticky,
driver-undefined `HDMI_VID_CTL` bit 25 (`0xc0080000` → `0xc2000000`). TMDS
sync continues with pixels blanked, the state survives stock restarts on the
same boot, and only a power cycle clears it. Stock-first boots and the
firmware splash transmit fine. Xorg additionally commits degenerate mode
blobs (empty name, flags `0x0`; causality unproven) and fails its initial
config with EINVAL when composite is connected (576i chosen against
`vc4.tv_norm=NTSC`). Evidence, observer-chain qualification, and the
remediation plan — direct KMS/GBM engine scanout as the product fix, kernel
patch as rescue only, one-boot bisect protocol — are in
[HDMI display issue](HDMI-DISPLAY-ISSUE.md). Boot ownership is stock; the
platform must not ship Xorg-driven display on this kernel until fixed.

## 2026-09-15: black-screen fix shipped — direct KMS backend, V1+V2 passed

Root cause (2026-09-14, see [HDMI display issue](HDMI-DISPLAY-ISSUE.md)):
Xorg sessions latch an undocumented `HDMI_VID_CTL` bit on the BCM2837
transmitter (sync alive, pixels blanked) that no later client clears until
power-off. Fix: the engine gained a direct KMS/GBM scanout window
(`engine/src/kms_window.*`, flag `--kms`, kernel-EDID modes only, hardware
EGL on V3D) and the platform service dropped Xorg entirely.

Validated on hardware through the capture-dongle chain with the VID_CTL
oracle (`tools/vidctl_watch.sh`):
- **V1** (one boot, no power cycles): stock visible → platform engine live
  at ~60 fps on `VC4 V3D 2.1` (first hardware-GL run; Xorg path was stuck on
  llvmpipe at 14–20 fps) with OSD readable off the wire → stock recovered
  after engine exit. 788 oracle samples, zero latched.
- **V2** (deployed service, platform-owned cold boot): release
  `dev-cf8b1ee8013f` activated transactionally; firmware splash visible,
  then continuous engine output from boot; `VID_CTL=0xc0000000`; 60.4 fps;
  no Xorg process. **The device now boots into a working platform.**

Remaining HDMI-gate work on the deployed service: physical controls, mode
switching, display latency, and a soak; plus the old Xorg conf cleanup at
provision and the noted `bootstrap --arm` image-arch defect.

## Remaining acceptance gates

1. HDMI fullscreen scanout, resolution/orientation, visible controls, and display
   latency before activating the full display service.
2. Known stereo signals; physical MIDI notes/clock, knobs/buttons, settings feel,
   and disconnect/reconnect behavior.
3. Live transactional deployment, interrupted transfer, failed activation, and
   both previous-release/stock recovery of the production service.
4. Reliable immediate read-only restoration after provisioning apt changes.
   Failure now propagates as a nonzero exit; successful restoration still needs
   a future provisioning qualification, not another uncontrolled apt run tonight.
5. Fully pinned clean-machine package acquisition: SDK/base-image digests and
   exact build provenance are recorded, but apt repositories still float.
6. Qualified observation path: the HDMI→USB dongle is qualified for A/B
   display testing on the workstation using the continuous-streamer protocol
   (its HPD line follows its UVC streaming state; see HDMI-DISPLAY-ISSUE.md).
   The 2026-09-13 "never shows Xorg output" reading was the latched VID_CTL
   bit, not the chain. A real display remains recommended for final visual
   and latency acceptance.

Release manifests intentionally retain `hardware_validated: false`.
Use the [next-session bench checklist](BENCH-CHECKLIST.md) for the remaining gates.
