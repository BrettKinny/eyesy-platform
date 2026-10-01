# Overnight iteration — 2026-09-12

## Target

An expressive, efficient personal EYESY Lua platform with a trustworthy
edit/preview/test/package workflow. Work proceeds in small implementation,
review, experiment, and regression-test cycles. Luna agents handle bounded
features and tests; the coordinating agent reviews and integrates their output.
Agent completion reports are not acceptance evidence by themselves.

Original SD card stays untouched. The freshly flashed development card remains
stock-bootable. No HDMI screen is connected, so scanout, visible controls,
physical audio/MIDI signals, and latency remain explicit bench gates.

## Evidence so far

- The existing four modes each completed
  900 frames on desktop llvmpipe with no errors and zero measured median RSS
  growth after warmup (short 15-second runs, not a soak).
- Real spare-card surfaceless EGL probe: `VC4 V3D 2.1`, Broadcom,
  GLES 2.0 Mesa 23.2.1; 1280×720 pbuffer readback correct, 120 draws,
  p50 4.021 ms and p95 6.323 ms. This is a simple offscreen gradient workload,
  **not full-engine throughput or HDMI performance**.
- Standalone stereo DSP benchmark on CM3+: 1000 analyses averaged 619.862 µs.
  No pre-change target baseline was captured, so no speedup is claimed.
- After both probes, `eyesypy` remained active and root remained `ro,noatime`.
- Original graphics integration suite passed on first integrated desktop build.
- Palette validation/new-mode integration passed on first integrated build.
- Deployment transactions are tested with mocked services and real temporary
  filesystem changes. This does not replace live deployment/recovery qualification.

## Early checkpoint (superseded by integrated results below)

- Bounded WAV analysis input and recorded/replayed control events; review is
  checking startup validation, press/release fidelity, and deterministic behavior.
- Seven creative modes with named/custom palettes; visual quality and target
  costs are being measured, not assumed.
- Optional offscreen engine backend to test actual Lua/GLES modes on CM3+
  without changing display ownership.
- Reproducible archive metadata, complete payload-based release identity,
  explicit SSH host verification, and build provenance.
- Longer reload/soak runs and final updated desktop/ARM artifacts after integration.

Final acceptance results will be recorded in STATUS.md and the evidence folders;
this log is not a declaration of completion.

## Hardware integration findings

- Native mode loading initially crashed even though the graphics probe passed.
  An independent `std::filesystem` traversal also segfaulted inside the stock
  Raspbian `libstdc++`. Privately loading the Debian build's matching
  `libstdc++.so.6` and `libgcc_s.so.1` fixed both the traversal and all seven modes.
  The exact internal ABI difference is not established. System libraries were
  not replaced. The integrated release now carries private copies.
- Seven native
  VC4 offscreen runs, 600 frames each, no mode errors and no measured median RSS
  growth after warmup. Shader-heavy modes do not yet sustain 60 fps at full
  resolution alongside stock video. These short runs are not a soak or HDMI test.
- A transient systemd unit paused stock Python for a bounded 1200-frame
  real audio capture probe, then restored it. Device input was available at
  48 kHz, sequence 1837, zero ring drops; RMS was near the noise floor, as no
  known external signal was supplied. This qualifies capture plumbing, not
  channel separation, musical response, signal quality, or latency.
- Desktop pixel inspection exposed invisible reusable line meshes. OF's
  expanded line shader expects adjacency data absent from VBO line strips;
  disabling that shader during those draws restored the actual mesh geometry.
  Duplicate line-loop workarounds were removed. ARM revalidation subsequently
  passed with visible mesh geometry in native GPU screenshots.
- Pixel-level full/reduced-resolution comparison reproduced a vertical flip:
  OF 0.12.1 restored the window surface after an inner FBO ended, rather than
  the parent canvas surface. `tools/of-fbo-surface.patch` makes view-stack
  push/pop preserve that surface and its matrix-flip flag. The exact patch is
  applied with zero fuzz to both SDK caches and included in build provenance.
  Desktop quadrant comparison passes; both SDK builds were rebuilt and the
  self-contained ARM package subsequently passed all seven modes.

## Integrated checkpoint

- Desktop and ARM builds completed with the reviewed VBO/FBO fixes. ELF RUNPATH
  is exactly `$ORIGIN/libs:$ORIGIN` on both binaries. ARM `ldd` resolves the private
  C++ runtime pair from the package without an injected library search path.
- All seven packaged modes passed 900 frames each on real VC4, with stock video
  active. Frame-time medians span
  about 15.7–29.7 ms; full-resolution feedback remains below 60 fps in this setup.
- The complete `headless-test` CLI passed verified upload, native rendering, and
  local report retrieval. Its brief run
  overlapped the soak and must not be used as standalone throughput evidence.
- Its negative path also passed on-device using a separately named intentional
  draw-error fixture: the engine rendered its error state through frame 60,
  returned exit 2, and the CLI returned exit 1 after retrieving all diagnostics.
  The fixture builder is
  retained alongside the reports; negative archives must never be activated.
- A temporary independent watchdog unit recovered a deliberately SIGSTOP-ed
  engine in 4.6269 seconds, with a changed PID, restart count 1, and advancing
  VC4 heartbeat. Stock remained active and the test unit was stopped afterward.
- Five core executables pass normal and ASan/UBSan/leak checks. The audio ring
  stress test transfers three million frames across three capacities and passes
  ThreadSanitizer. Expanded WAV checks include duplicate chunks, invalid/truncated
  formats, non-finite float samples, and a valid sparse file exceeding decoded
  memory limits. A separate structured mutation campaign uses independently
  validated PCM16/float32 seeds: seed 57829, 10,000 cases, 3333 accepted and 6667
  rejected. Every accepted result is checked for finite/clamped samples and
  bounded dimensions; the campaign passes sanitizers. This is bounded mutation
  coverage, not exhaustive fuzzing.
- Packaging repeated byte-for-byte with the same archive hashes:
  ARM `dist/dev-dd42a1d3bd86-armhf.tar.gz`, SHA256
  `0a5b4b0e4aff9a2b8848db4c23f2611d38b5e0428a375b6a977a17f6fa03698f`;
  desktop `dist/dev-a3600ffb7efd-amd64.tar.gz`, SHA256
  `cfd2fd037bc9703931a32bb40324cdf7477e0aeaa2856501a76737a8ae352146`.
  These are seven-mode development artifacts, not hardware-accepted releases.
- Three creative experiments remain isolated under `local/experiments/`:
  smooth mesh kaleidoscope, shader tunnel, and reduced-resolution echo feedback.
  Desktop and native images were inspected; all prototypes passed 600 native
  frames under shared load. Any promotion decision is separate from the frozen
  seven-mode soak.
- Native input integration passed on the packaged engine: generated 44.1 kHz WAV
  analysis (RMS 0.258), EOF behavior, OSC recording, MIDI replay semantics, and
  matching PNG hashes across repeated control replays. No physical MIDI signal was used.
- Final local checkpoint: five core tests, 77 Python tests, and all five graphics
  integration scripts pass. Packaging still reproduces the hashes above after
  the test/tool refinements; no production engine or mode changes were introduced.
- The revised pidfd guard was tested against a disposable `/usr/bin/sleep`
  process on the spare. Round 1 correctly terminated it but misclassified the
  disappearing executable link as an error; a regression test and fix followed.
  Round 2 recorded `duration limit` without an error, and the parent independently
  observed SIGTERM exit. The 5-second polling interval plus cleanup means a
  1-second requested limit is not a 1-second response-time guarantee.

## Completed long-run qualification

At about 12:00 UTC, a bounded transient service started 216,000 frames, switching
every 120 frames across the frozen seven-mode catalog. Both stock Python and the
hardware daemon remain active; root stays read-only. The benchmark samples status,
RSS, and SoC temperature throughout. The engine completed naturally after
4716.957 seconds (78.6 minutes), with 216,000 frames and 1,800 reloads. Its exit
code was zero, and all seven modes were observed across 4661 status samples.
No sampled errors, shader warnings, or audio-ring drops were recorded.

The kernel's memory cgroup controller is disabled. Although systemd accepts
`MemoryMax=256M`, it cannot enforce it on this boot. A direct guard was therefore
attached to the verified experiment PID, checking 256 MiB RSS, 80°C, and duration
limits. Its evidence starts after the soak's initial warmup; the main benchmark
has earlier samples. Guard completion alone does not establish engine success.

The soak uses an earlier benchmark snapshot whose mode-file summary only hashes
the initial mode. The frozen package/archive hash above identifies the full tested
catalog. The current harness now hashes all traversed modes and fails on transient
sampled warnings/errors as well as final status. Final soak analysis applies
those checks retrospectively to its stored samples. That recheck passed
(`local/overnight/analyze_soak.py`).

Post-warmup first/last-window median RSS was 72,282,112 / 72,364,032 bytes:
**80 KiB measured growth**. The main sampler's post-warmup peak was 72,679,424
bytes; the independent guard caught a higher transient peak of 80,093,184 bytes
(76.4 MiB). Their different sampling times explain the different peaks. RSS is
not total GPU memory. Temperature peaked at 60.686°C; throttling flags remained
clear in the checks. Neither guard nor benchmark duration limit triggered.

The final 4026-frame timing window reported p50 22.95 ms / p95 30.27 ms. Those
are **not full-run percentiles**: the engine deliberately bounds retained timing
samples. Short CLI, input, and prototype experiments briefly shared the GPU with
the soak; stock video remained active throughout. This run qualifies headless
stability under that workload, not HDMI pacing or physical-input acceptance.

Both transient soak/guard units became inactive, while stock Python remained
active. The original card and boot selection were unchanged.

## Final efficiency check and handoff

The post-soak full/half/half/full echo comparison completed 900 frames per trial
without errors or measured median RSS growth. Median frame times were
29.661 / 21.606 / 21.606 / 29.667 ms; wall times were
27.904 / 20.613 / 20.615 / 27.907 seconds. Stock video remained active, but the
extra soak engine was no longer running. The reduced-resolution variant has
roughly 27% lower median frame cost in this setup, with visibly coarser edges;
it remains outside the release as an explicit quality tradeoff.

Final read-only device check: stock Python, hardware daemon, MIDI bridge, web
editor, and SSH active; platform service disabled; root `ro,noatime`;
`throttled=0x0`; temperature 52.1°C; no leftover `eyesy-engine` processes.
All experiment data is retained. Nothing was enabled as a new boot default.

The final provisioning review also fixed EXIT-trap status propagation: failed
read-only restoration now returns nonzero even if the main operation succeeded.
The actual cleanup function is tested under strict Bash flags with inert
mount/sync stubs. This fixes error reporting, not the underlying busy-remount
condition, which remains a bench/provisioning follow-up.

The final regression, sanitizer and thread-sanitizer runs passed.
The remaining physical and production-service gates are in
[BENCH-CHECKLIST.md](BENCH-CHECKLIST.md); manifests remain hardware-unvalidated.
