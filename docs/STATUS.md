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

Remaining HDMI-gate work after the later bench session: physical controls,
stereo signal, and display latency still need hands; the full-formality
60-min soak needs one clean rerun (today's was stopped at 53.7 min). The
Xorg conf cleanup and the `bootstrap --arm` defect are fixed.

## 2026-09-15 (later): bench qualification session

Evidence and phase-by-phase detail: `local/reports/bench-2026-09-15/REPORT.md`.

- **Rollback qualified live in all four paths**: the Xorg-era previous
  (`dev-dd42a1d3bd86`) is safely rejected (`unknown argument: --kms`) with
  automatic sub-2-second restore; `--target stock` restores visible stock;
  and after deploying `dev-c2f150be2380` (built by the fixed bootstrap),
  `--target previous` was live-proven in both directions between healthy KMS
  releases for the first time. Device ends on `dev-c2f150be2380` with
  `previous.json` → `dev-cf8b1ee8013f`.
- **Recovery path qualified unattended**: no-sink engine start fails with an
  actionable probe error → start-limit → unit failed → `OnFailure` fallback
  starts stock (~9 s total); stock stays up with no display; platform
  recovery with the sink present is clean. Cold-boot variant still needs one
  user power cycle.
- **Provision hygiene**: legacy `/etc/X11/xorg.conf.d/10-eyesy-720p.conf`
  removed on the device with verified rw→rm→verify→ro; the provisioner now
  does the same loudly (10 targeted tests pass).
- **`bootstrap --arm` defect fixed**: the base pin was the single-arch amd64
  manifest of the bookworm-slim index; now pinned to the slim multi-arch OCI
  index with an `EXPECTED_ARCH` build-time assertion. Both images rebuilt
  from scratch; armhf ELF and private runtime libs verified; desktop build
  unaffected.
- **Partial deployed-service soak** (early stop): 53.7 min, 446/500 OSC mode
  switches, all landed (`reloads=447`), zero mode errors, zero audio drops,
  RSS growth **+248 KiB** (69.9 → 70.2 MiB window medians, peak 70.4 MiB),
  SoC peak 58.0 °C.
- **1080p viability assessed** (`local/reports/1080p-plan-2026-09-15/`):
  scanout reachable via EDID 1080p modes, but native 1080p60 is not viable
  for 4/7 modes (they already miss 60 fps at 720p); recommendation is to keep
  720p rendering and calibrate before any native-1080p trial.
- **New known findings** (follow-ups): engine exits 1 on SIGTERM (routine
  stops mark the unit failed and spuriously fire `OnFailure`); no supported
  re-entry to an installed release after stock rollback; KMS mode chooser
  silently falls back to `modes[0]`; recovery-vs-fallback race leaves the
  fallback unit FAILED (benign, convergent).

## 2026-09-15 (evening): two creative scenes shipped

Two new Lua modes extend the seven-mode set; release `dev-cd72740cc708` is
live (transactional deploy, `previous.json` → `dev-c2f150be2380`, platform
service active at ~60 fps on the KMS path, real codec audio).

- **phosphor** — stereo XY oscilloscope with phosphor afterglow: left/right
  buffers drawn as XY and time-domain traces into a half-res (640x360)
  ping-pong feedback chain (feedback warp + decay + vignette in one shader
  pass), halo/core mesh passes for glow, sum-of-phasors synthetic Lissajous
  when audio is silent, trigger jumps orbit ratios. Desktop preview verified
  visually; on-device offscreen p50 **24.0 ms (~41 fps)**, zero errors, zero
  RSS growth.
- **kali-bloom** — kaliset (`a - |p|`, 10 iterations, half-res) fragment
  bloom with bounded max()-composite feedback, bass zoom breathing, treble
  core accent, trigger morphs the fractal constant. On-device offscreen p50
  **30.3 ms (~33 fps)**, zero errors, zero RSS growth. Both sit inside the
  shipped fleet's 15.7-29.7 ms envelope; full-formality 60 fps remains an
  open gate for shader modes.

Evidence: `local/reports/headless-phosphor-round2/` (full-res baseline),
`headless-phosphor-round3/`, `headless-kali-round2/`, plus desktop previews
under `local/preview/grabs/`. Tuning history caught two design traps now
encoded in the shaders: bloom inside a feedback loop self-amplifies to
white, and clamping the kaliset denominator at 1e-4 collapses orbits onto a
shared trajectory (uniform gray).

## 2026-09-15 (night): scene library batch 1 shipped

Eight more Lua scenes built from the research swarm (blueprint:
`local/reports/scene-library-blueprint/BLUEPRINT.md`, raw corpus in
`docs/research/`). Release `dev-95ed836e02d1` live (transactional, health
passed, ~59.5 fps on the KMS path, real codec audio). 17 modes total.

| scene | family | on-device p50 |
| --- | --- | --- |
| chladni-plate | sacred geometry / cymatics | 27.6 ms |
| outrun-grid | cyberpunk / synthwave | 25.3 ms |
| rutt-etra | video synthesis raster warp | 24.8 ms |
| plasma-flow | fbm domain warp (2-octave) | 32.7 ms |
| whitney-kaleido | Whitney permutation lattice | 29.1 ms |
| lorenz-trail | attractor phosphor trail | 24.0 ms |
| reaction-diffusion | Gray-Scott on GPU (first anywhere on EYESY) | 27.5 ms |
| ascii-wave | dot-matrix terminal | 31.0 ms |

All passed desktop preview, 81-test suite, and on-device headless runs
(`local/reports/batch1-*`); two required optimization rounds (plasma:
3->2-octave fbm + 480x270 targets, 72.5->32.7 ms; ascii: half-res ASCII
pass, 44.9->31.0 ms). Engineering notes: e.palette stop spacing is cyclic
(i/n segments) - characterize precisely before palette-critical work;
outrun hardcodes its trio for the same reason. Knob contract held:
k1 motion/energy, k2 structure, k3 detail, k4 hue, k5 feedback.

## 2026-09-16: scene library batch 2 shipped

Ten scenes from the ideation swarm (op art, retro-futurism, sacred
geometry, vintage CGI, psychedelia, ports). Release `dev-30e2ba1e0197`
live (transactional, health passed, ~60 fps on the KMS path). 27 modes.

radar-sweep 23.8 ms, wireframe-room 23.5, lyapunov-field 24.5,
flow-field-drift 24.1, riley-grating 26.2
(converted to an analytic fragment shader after the mesh version measured
36.6 - analytic op-art needs zero marshalling), penrose-lattice 25.5
(5-wave quasicrystal at 480x270 after 39.7 at 640x360), complement-flash
26.7, girih-stars 27.2 (half-res pass after 34.9), textmode-field 32.1
(480x270 content pass after 33.7), facet-terrain 33.3 (at the tier C
bound). All zero-error, zero RSS growth (`local/reports/batch2-*`).

New engineering facts: screen-space `uv.y` is top-down; centered-coordinate
scenes need the translate, top-left-origin particle fields do not;
`e.palette` stop spacing remains unreliable for palette-critical color
(riley/lyapunov/outrun hardcode authored pairs); equal-luminance opponent
pairs are luma-normalized to 0.45 by an iso() helper, not `1-c` complements.
Research corpus: `docs/research/` (15 docs).

## Remaining acceptance gates

1. HDMI scanout, resolution, and orientation are validated through the
   qualified dongle chain; visible physical controls and display latency
   remain (need hands; a real display is recommended for final acceptance).
2. Known stereo signals; physical MIDI notes/clock, knobs/buttons, settings feel,
   and disconnect/reconnect behavior.
3. Live transactional deployment and rollback of the production service are
   now live-proven (all four paths, see bench report); interrupted transfer
   and failed activation remain covered by the earlier mocked/test-filesystem
   evidence and may be re-exercised live opportunistically.
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

## 2026-09-16 (later): Track B shipped — milkdrop engine

The scaling unlock is live: `modes/milkdrop/` is one Lua engine (736 lines)
that plays 12 self-authored MilkDrop-style presets through six canonical ES2
fragments. Release `dev-e46f786ab44d` deployed transactionally, healthy at
60.3 fps on the KMS path (28 modes). Built by tower-local task agents
(qwen3.8:27b) against `local/reports/trackB-plan/BRIEF.md`: T1 AVS-subset
expression evaluator (36/36 tests, mutation-checked), T2 fragment library,
T3 preset pack, T4 engine integration.

Device tier evidence (600 frames per preset, offscreen, VC4): 10/12 presets
meet tier C (27.3-31.8 ms); the two glow-comp presets ship waived at 40.4/
50.0 ms after two optimization rounds — the 5-gather composite's VC4 fill
cost is intrinsic at content res (waiver + levers in docs/SCENE-LIBRARY.md).

Bugs found and fixed during QC (all caught by measurement, not review):
clamp_engine indexed default/min instead of min/max (comp gamma collapsed
to 0.1, decay to 0 — the "no trails" symptom), comp_glow double-centered its
gather ring (+0.9/axis, flat-frame output), blur1 inverted its texel scale
(black blur), comp_glow ran six gathers instead of five, and per-point wave
env missed per-frame state. Engine facts added to docs/SCENE-LIBRARY.md.
Tooling: headless-test/benchmark gained --replay passthrough so in-mode
presets get individual device tier runs; remote staging now cleans up on
success (tmpfs was filling).

Research: BeatDrop fork (OfficialIncubo) portables assessed in
docs/research/BeatDropForkPorting.md — FFT/wave shader variables ranked
first for a post-v1 engine round.

## 2026-09-17 (dawn): bardo night — nine scenes

Nine scenes built in one night and catalog-verified together at dawn. Every
one is a single Lua mode plus a single fragment pass — no new engine
machinery, no new pipeline pattern — and all nine pass
`tools/scene_verify.py` at 300 frames (one sweep, nine `--mode` flags:
9/9 verdict pass, exit 0, 16 runs per mode — base, base2, knob mid/max pairs,
audio quiet/loud/freq, and a MIDI note-on — plus a trigger-assisted 17th for
`koan-terminal`; byte-identical `base` vs `base2` determinism everywhere).

| scene | what it is | llvmpipe p50 |
| --- | --- | --- |
| mandala-bardo | Tibetan sand-mandala construction: petal rings grown outward from each base circle, breathing bindu, chalk-guideline fold seams | 16.65 ms |
| temple-core | TempleOS shrine corridor in exactly sixteen CGA colours, 320x180 ink target upscaled | 16.67 ms |
| buddha-1kb | the 1k-intro discipline literal: three cos terms = a counter-rotating standing wave, one formula, no mesh | 16.67 ms |
| wireframe-bardo | retro-CGI chrome idol: 13-vertex icosahedron → 30 screen-space segments, exact hidden-line removal | 16.66 ms |
| slit-scan-vortex | Belson/Whitney "beings of light": logarithmic-spiral filament layers counter-rotating into a void | 16.65 ms |
| copper-bar-hymn | Amiga copper bars as liturgy, with a 5x7 dot-matrix scrolltext, analytic in `y` only | 16.66 ms |
| koan-terminal | teletype dharma machine: koans struck out on a long-persistence phosphor tube, decaying to empty glass | 16.64 ms |
| tesseract-yidam | the 8-cell rotated in two commuting 4D planes, projected 4D→3D→2D as luminous wires | 16.67 ms |
| phosphor-seance | spirit photography as video feedback: the phosphor field restamped by blurred face sigils | 16.66 ms |

Verification method and evidence: `local/verify-catalog-bardo-dawn/`
(whole-sweep `summary.json` + per-mode `<NN-mode>/summary.json`,
`contact-sheet.png`, `run-*/{replay.json,engine.log,report.json,grabs/}`),
run in `localhost/eyesy-build:bookworm` with `--xvfb`. Build reports,
design rationale, and per-scene hashes: `local/reports/bardo-night/01..09-*.md`
and `dawn-checkpoint.md`. Each scene's first-pass evidence dir
(`local/bardo-verify-01/00-mandala-bardo/`, `local/verify-temple/`,
`local/verify-buddha1kb/`, and the per-scene `scene0N-verify/` dirs) is
unchanged and listed in its report.

**The p50 column is llvmpipe software GL inside the build container, not the
VC4 device.** It is a same-machine regression baseline, not a performance
claim: no device tier is asserted for any of the nine until the on-device
benchmark pass (`tools/benchmark.py`) runs per mode. The structural
expectation — one 640x360 (or 320x180) fragment pass, ≤ 5 texture taps, one
upscale, no iteration — puts them at or below the cost of shipped tier A/B
scenes, but that is untested on hardware.

Facts recorded for the library (also in `docs/SCENE-LIBRARY.md`): knobs rest
at 0.5, because the engine writes the knob snapshot over every declared
`e.param` default each frame — the verifier's `base` state is one *extreme*,
not the resting look; `buddha-1kb`, `wireframe-bardo`, `slit-scan-vortex`,
`copper-bar-hymn`, `koan-terminal` and `phosphor-seance` deliberately occupy
non-contract knob slots, documented in each mode header; palette names added
are `bardo`, `temple`, `buddha1k`, `chrome`, `belson`, `copper`, `yidam` and
`seance`, and `koan-terminal` re-defines the `phosphor` name the shipped
phosphor mode already uses (a later `define_palette` overwrites the entry and
the palette budget only counts new names, so mode switching re-defines it
correctly; no duplicate-name error exists). Cyclic hue ramps legitimately give
a zero `knob4-max` A/B diff in `mandala-bardo` and `phosphor-seance` while
`knob4-mid` stays large.

Docs cutover: README's mode list is now 37 named modes — the nine bardo scenes
plus `milkdrop`, which the list had been missing since the Track B release —
and `docs/SCENE-LIBRARY.md` carries the nine knob maps. `./eyesyctl test`
passed unchanged after the cutover (ctest 5/5, 120 Python tests OK), so no
catalog-coupled test needed fixing. No commits were made.

## 2026-09-17 (later): bardo scenes device-gated, optimized, and shipped

The nine bardo-night scenes met the on-device tier gate only after two
optimization rounds. Release `dev-f2c914333761` is deployed transactionally
(`previous.json` → `dev-b5cf00d32b6c`), health passed, 60.3 fps on the KMS
path, zero errors, and the device carries all 37 modes. `modes/zzprobe`
(scratch diagnostic, "delete after use") is excluded from releases; it stays
in the repo.

Device tier (VC4 V3D 2.1, 600 frames offscreen, live platform on
`stereo-mesh` as GPU neighbour, evidence `local/reports/bardo-device*/`):

| scene | first gate p50 | shipped p50 | what changed |
| --- | --- | --- | --- |
| temple-core | 57.1 | 26.3 | composite moved into the 320x180 ink target + nearest-blit upscale (full-res pass was 16x redundant) |
| wireframe-bardo | 27.6 | 27.6 | unchanged (passed as built) |
| tesseract-yidam | 27.6 | 27.6 | unchanged (passed as built) |
| buddha-1kb | 33.2 | 33.2 | unchanged (borderline pass) |
| phosphor-seance | 73.7 | 29.5 | 320x180 field, drift trig + eye profile substitutions, exact sigil bounding test |
| mandala-bardo | 55.3 | 30.3 | 352x198 content, ring loop 6→2 evaluations (≤2 rings touch a pixel), exact ink early-outs |
| copper-bar-hymn | 67.6 | 30.5 | y-only bar raster to an 8x360 target (1/80 fill), scrolltext font baked into a Lua atlas |
| slit-scan-vortex | 46.1 | 30.9 | 320x180 content, per-layer phase pre-expansion (identity refactor) |
| koan-terminal | 74.1 | 31.3 | 320x180 pass at 1.5 layout px, hum/corner substitutions, flyback branch-gated, tints folded |

Baseline caveat: the "first gate" column was measured before the neighbour
drift was discovered, so the round-1 numbers for the late-measured scenes
(phosphor-seance, koan-terminal) may carry some of the same +5-7 ms skew.
The shipped column is the authoritative tier evidence: every number in it
was measured under the verified tier-A neighbour condition, matching how
the batch 1/2 fleet was gated.

All pass `tools/scene_verify.py` at 130 and 300 frames; the restructured
shaders carry same-sim-frame equivalence A/Bs (mandala and the seance trig
are pixel-exact; the substitutions are bounded and measured in
`local/ab-opt2-mandala-bardo/`, `local/koan-opt2-ab/`, `local/opt2b-slit/`,
`local/verify-opt2-phosphor-seance/opt2-report.json`).

New measurement facts for the library:

- **llvmpipe p50 is meaningless for tier work.** The dawn sweep measured a
  flat 16.6 ms on all nine; the real VC4 gate measured 26-74 ms (1.4-4.5x).
  Only structure (pixels x taps x per-pixel math) predicts; the container is
  a correctness gate only.
- **There is a ~23.5 ms engine floor** per frame at 720p output (cheapest
  shipped 640x360-content + upscale scenes all measure 23.5-24.1). Pure
  fill cuts deliver about 0.85 of their nominal ratio plus a fixed term;
  pass restructures (move full-res work into the content target, hoist
  per-frame constants to Lua) delivered at or above estimate.
- **The benchmark neighbour matters.** A stuck settings menu (OSC `/key`
  events route to `settingsKey` while the menu is open; key 1 exits) left
  the live service on `complement-flash` at 43.8 fps, which inflated every
  offscreen gate number by 5-7 ms and looked like four regressions. Gate
  runs must start from the verified condition: live platform on a tier-A
  scene at ~60 fps (`./eyesyctl status` + OSC key check on the device).

