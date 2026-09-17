# 1080p (1920x1080) viability on CM3+ / VC4 V3D 2.1 — analysis

Date: 2026-09-15. Produced by the Plan1080p analysis agent (read-only; no
device access). Note: the agent returned this analysis in its structured
output but failed to write it to disk; this file is the verbatim content
recovered from `agent://Plan1080p`.

## Verdict

1080p (1920x1080) scanout is architecturally reachable on the CM3+ via the
existing KMS/GBM path, but not at 60fps for the full catalog: the engine
currently hardcodes a 1280x720 render pipeline in five places, and even before
that, four of the seven modes already miss 60fps at 720p under shared
stock-video load (measured p50 on real VC4, package-round3: aurora 22.79 ms,
shader 25.79 ms, feedback 29.73 ms, echo-feedback 29.66 ms). Scaling fill-bound
passes 2.25x puts those modes at roughly 15-25 fps at native 1080p [INFERENCE
extrapolated from measured 720p frame times and the measured 27% full->half
echo delta, docs/OVERNIGHT.md:174-181]. Recommended plan: keep 1280x720 as the
mode render resolution (or per-mode reduced targets), select a 1920x1080
kernel EDID mode only if the sink advertises one, and validate with the
VID_CTL latch oracle — the current dongle chain already upscales 720p to 1080p
capture, so native 1080p buys sharpness only for the cheap modes. True
native-1080p rendering for starter/stereo-mesh/prism-mesh is plausible but
their headroom is masked by the 60fps vsync cap and needs a measured 1080p
offscreen pass first.

## Mode availability

All seven packaged modes remain available at 1920x1080 — the mode API is
resolution-agnostic (feedback/echo allocate targets from ctx.width/height;
aurora's half target is a fixed 640x360) and no mode would fail to load or
draw. Availability is not the constraint; sustained frame rate is. The three
cheap modes (starter, stereo-mesh, prism-mesh) are 60fps-capped at 720p with
unknown headroom and plausibly hold near 60fps at 1080p; the four fill-bound
modes already miss 60fps at 720p under shared load and would drop to roughly
15-25fps at native 1080p [INFERENCE extrapolated from measured 720p frame
times]. Practical consequence: a true-1080p release is realistic for the
mesh/starter modes, while the fill-bound modes should keep a
reduced-resolution render path (as aurora already does by default via its
640x360 target, modes/aurora/main.lua:15,21-29) and upscale.

## Per-mode outlook

- **starter** — 720p measured p50 16.02/p95 19.09 ms, 60fps-capped
  (local/overnight/package-round3/summary.json:369-371); work is one clear
  plus one audio-reactive circle plus text, so 1080p cost should stay within
  the 16.67 ms budget; outlook: likely holds ~60fps, low risk [INFERENCE].
- **stereo-mesh** — 720p measured p50 15.96/p95 19.10 ms, 60fps-capped
  (package-round3:431-433); two 256-vertex line strips plus clear and text,
  fill-light; outlook: likely holds ~60fps at 1080p; note the 1080px
  horizontal span constant (modes/stereo-mesh/main.lua:25) composes smaller
  at 1080p [INFERENCE].
- **prism-mesh** — 720p measured p50 15.69/p95 19.02 ms, 60fps-capped
  (package-round3:245-247); line strips plus a small alpha triangle fan,
  fill-light; outlook: likely holds ~60fps; span constant 1120
  (modes/prism-mesh/main.lua:40) composes smaller [INFERENCE].
- **aurora** — 720p measured p50 22.79/p95 23.48 ms at 44fps, already on its
  cheap default path (quality<0.75 renders the shader into a 640x360 target,
  then one full-screen upscale, modes/aurora/main.lua:21-29); the dominant
  costs are two full-window passes (target-to-canvas blit and
  canvas-to-scanout composite), each 2.25x at 1080p; outlook: ~45-55 ms p50,
  ~18-22fps — still the best of the shader modes, and its quality knob's
  full-res path (>=0.75) becomes effectively unusable at 1080p [INFERENCE].
- **shader (plasma)** — 720p measured p50 25.79/p95 26.45 ms at 39fps
  (package-round3:307-308); one full-resolution fragment-shaded pass plus
  composite, both 2.25x at 1080p; outlook: ~55-60 ms p50, ~17fps; would need
  a reduced-resolution target path like aurora's to stay usable [INFERENCE].
- **feedback** — 720p measured p50 29.73/p95 30.42 ms at 34fps
  (package-round3:183-185); full-res ping-pong: clear + textured decay draw +
  circle inside two ctx-sized targets, plus canvas composite; measured
  calibration from the echo variant (halving target area cut p50
  29.66->21.61 ms, docs/OVERNIGHT.md:174-181) shows ~10.7 ms of the cost
  lives in the scaling target passes and ~19 ms in the composite+CPU floor;
  at 1080p the target passes scale to ~24 ms and the composite roughly 2.25x;
  outlook: ~50-65 ms p50, ~15-20fps [INFERENCE].
- **echo-feedback** — 720p measured p50 29.66/p95 30.40 ms at 34fps
  (package-round3:121-123); same two-target ping-pong structure with
  rotate/scale; outlook: ~50-65 ms p50, ~15-20fps at native 1080p; the
  already-characterized reduced-resolution variant (27% lower median cost,
  visibly coarser edges) is the natural mitigation and remains outside the
  release as an explicit quality tradeoff [INFERENCE].

## Engine changes needed for a 1080p trial

- Parameterize the canvas FBO instead of hardcoding 1280x720:
  engine/src/main.cpp:422-428 (ofFbo::Settings width/height = 1280/720) — the
  mode render surface must follow the actual window/scanout size, otherwise
  1080p scanout only upscales 720p content (canvas.draw at
  engine/src/main.cpp:640 already scales to ofGetWidth/ofGetHeight).
- Pass the real size to the mode runtime: engine/src/main.cpp:168
  (loadMode(catalog[selected], 1280, 720)) — ctx.width/height, the FBO size
  budget (engine/src/runtime.cpp:568 'w > width'), and FBO_DRAW/SHADER_DRAW
  defaults (engine/src/runtime.cpp:606,687-688) all derive from this; runtime
  defaults are also hardcoded at engine/src/runtime.h:34.
- Parameterize the other window paths: engine/src/main.cpp:797 (GLFW
  settings.setSize(1280,720)), engine/src/main.cpp:800
  (createOffscreenWindow(1280, 720)), and the probe draw at
  engine/src/main.cpp:626 (hardcoded 640,360 center).
- Change KMS mode preference: engine/src/kms_window.cpp:253-263 prefers
  1280x720 55-65Hz and silently falls back to connector->modes[0]; add an
  explicit resolution preference/fallback policy while keeping the
  EDID-derived-kernel-blob-only rule (engine/src/kms_window.h:9-13;
  docs/HDMI-DISPLAY-ISSUE.md).
- Verify GBM scanout allocation at 1920x1080: gbm_surface_create at
  engine/src/kms_window.cpp:63-64 (GBM_FORMAT_XRGB8888, SCANOUT|RENDERING) —
  no code change expected, but allocation size and page-flip pacing at
  148.5MHz pixel clock need on-device confirmation.
- Update the documented API contract: docs/API.md:13 ('ctx.width/height are
  1280/720') and docs/API.md:68 (draw_target default 'w=1280,h=720' — actual
  engine default already follows runtime size at engine/src/runtime.cpp:606).
- Update test harness resolution assumptions: tests/creative_tests.py:13,
  tests/graphics_tests.py:15, tests/input_workflow_tests.py:16,50,
  tests/render_target_tests.py:26,35, tests/runtime_robustness_tests.py:13
  (xvfb 1280x720x24 screens and 1280/720 literals) need a size-parameterized
  or dual-resolution run.
- Per-mode design constants: prism-mesh span 1120 (modes/prism-mesh/main.lua:40),
  stereo-mesh span 1080 (modes/stereo-mesh/main.lua:25), orbit radii 260/180
  and 230/160 (modes/echo-feedback/main.lua:25-26, modes/feedback/main.lua:25-26),
  text at 32,48 — either derive from ctx.width/height or adopt a 1280x720
  virtual-resolution scheme upscaled at the canvas boundary; feedback/echo
  targets already use ctx.width/height and adapt automatically.
- Mode changes needed: none for availability — all seven modes load and draw
  at any ctx size; only composition constants (above) are 720p-tuned.

## Measurement plan (for a bench trial)

1. First, without engine changes, fit the fill-scaling curve on the spare
   using the existing reduced-resolution echo variant: run the packaged
   engine at additional internal target fractions (e.g. 960x540, 854x480)
   900 frames each with stock video active, reusing the package-round3
   harness, to confirm the ~linear pixel-scaling model before investing in
   the 1080p path (calibration anchor:
   local/overnight/echo-abba-round1/summary.json).
2. EDID check: capture the kernel connector mode list the dongle/HDMI sink
   exposes (modetest or the engine's KMS mode print,
   engine/src/kms_window.cpp:268-272) and confirm a named, flagged
   1920x1080@60 kernel blob exists before any code change; if absent, true
   1080p scanout is not reachable on this sink and the plan stops at an
   internal-resolution change.
3. Offscreen 1080p cost pass (no scanout risk): build with canvas/runtime
   size 1920x1080, run all seven modes 900 frames each via --offscreen with a
   1920x1080 pbuffer, stock video active, same harness as package-round3;
   record p50/p95/p99, RSS, temperature, audio drops; compare against the
   2.25x fill-scaling predictions.
4. KMS scanout validation with the latch oracle: after the EDID-confirmed
   1080p blob is selected, run vidctl_watch.sh continuously (the existing
   ~10Hz oracle, local/reports/bench-2026-09-15/vidctl.txt format) through
   mode selection, several minutes of scanout, and shutdown; acceptance is
   zero latched (0xc2...) samples, matching today's session baseline.
5. Live pacing check on the deployed service: run the existing guard +
   status.json sampler (1Hz) for a bounded window per mode at 1080p scanout
   — with the 2026-09-15 caveat: use an observe-only poller, not the
   kill-capable soak_guard, when pointed at the deployed service (see
   ROADMAP.md item 2). Verify p50/p95 from status.json, page-flip regularity
   via the frame-time window, and check dmesg/journal for any HVS underrun or
   CMA allocation failures; compare 720p-vs-1080p visually via the dongle
   capture (frame grabs like dongle/live-phase5/*.png) for text/geometry
   crispness.
6. GPU memory headroom measurement: with stock video active, record vcgencmd
   get_mem gpu/malloc_reloc (or vcdbg) before/after 1080p FBO and scanout
   allocation, especially for feedback/echo which hold two full-size targets
   plus depth (engine/src/runtime.cpp:570-577 useDepth=true); acceptance:
   allocation succeeds and peak stays clear of the 128MB split.
7. Quality decision gate: capture side-by-side dongle frames of the three
   cheap modes at native 1080p vs the current 720p-upscaled-by-sink chain;
   promote 1080p only if the measured sharpness gain justifies the
   scanout-mode-change risk, keeping heavy modes on the reduced-resolution
   path (aurora already ships half-res default; the echo half-res variant is
   already characterized at ~27% lower median cost).
8. All device steps are for the parent/owner to execute later; this analysis
   is read-only and no SSH, builds, or tests were run.

## Risks

- HDMI transmitter latch is the highest-severity risk: scanout-mode handling
  is the documented trigger boundary (client-constructed modes latched
  VID_CTL bit 25 twice; docs/HDMI-DISPLAY-ISSUE.md,
  engine/src/kms_window.cpp:22-28), and although a kernel EDID-derived 1080p
  blob is the safe class, it must be proven with the vidctl latch oracle
  before/after; failure mode requires a power cycle to recover.
- No GPU headroom: V3D is clock-fixed at 300MHz on this CM3+, and four of
  seven modes already miss 60fps at 720p under shared stock-video load; all
  1080p fps projections are downward extrapolations, never improvements.
- GPU memory pressure: gpu_mem split is 128MB shared with stock video; 1080p
  adds ~2.25x FBO color+depth (feedback/echo hold two full-size targets with
  depth, engine/src/runtime.cpp:570-577) plus larger GBM scanout buffers;
  allocation failure would throw at target creation and kill the mode
  mid-run.
- Extrapolation uncertainty: per-mode 1080p estimates are 2.25x fill scaling
  minus a fixed CPU/DSP floor (~620us DSP per docs/DSP-PERFORMANCE.md:10 plus
  per-frame Lua table rebuild of ~3100 audio/FFT/midi numbers at
  engine/src/runtime.cpp:325-364); the mesh modes' true headroom is masked by
  the 60fps vsync cap, so their 1080p outlook could be worse than 'likely
  60fps' — the offscreen 1080p pass must replace estimates with measurements.
- Sink capability unknown: the current chain negotiated 1280x720@60
  (rollback-previous-journal.txt); if the dongle's EDID lacks a 1080p60 blob,
  the KMS chooser silently falls back to modes[0]
  (engine/src/kms_window.cpp:262-263) — an explicit, loud preference/fallback
  is needed to avoid a surprise mode.
- Oracle blind spot: today's vidctl log shows an unexplained ~31-second
  contiguous block of 0x401c0000 (218 samples, t~1789427664-1789427696,
  local/reports/bench-2026-09-15/vidctl.txt) and 4.1% sporadic single-sample
  0xc0080000 toggles; the bit semantics outside the documented bit-25 latch
  are not established, so oracle coverage at 1080p should be qualified first.
- Composition regressions: modes' absolute-pixel constants (spans 1120/1080,
  orbit radii, text origins) will render proportionally smaller at 1080p;
  fixing them per-mode risks changing the accepted 720p look — a
  virtual-resolution layer changes behavior for all modes and needs its own
  regression pass.
- Visible-gain is limited: the sink chain already upscales the 720p scanout
  to 1080p capture (dongle PNGs are 1920x1080), so the benefit of native
  1080p is confined to text/geometry crispness and possibly reduced
  double-scaling; for fill-bound modes native 1080p would be a large fps
  regression for a small sharpness gain.
- No soak numbers exist at 1080p: today's 60-minute 500-switch soak qualifies
  the 720p deployed service only; a native-1080p release would require
  repeating the soak-scale memory/stability qualification before activation.
