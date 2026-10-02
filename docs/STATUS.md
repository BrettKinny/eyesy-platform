# Implementation status

This is a working development platform, **not yet a fully bench-qualified
replacement for stock EYESY**. It boots and runs on a CM3+ EYESY with OS v3.0,
drawing through direct KMS at 720p60 with hardware GL (`VC4 V3D 2.1`). Release
manifests keep `hardware_validated: false` until the manual checks in the
[bench checklist](BENCH-CHECKLIST.md) pass. What is still open is listed in the
[roadmap](../ROADMAP.md).

The run reports behind the hardware results below (device logs, captures,
samples) are kept privately; this page summarises them.

## Engine

- Desktop and ARM builds of openFrameworks 0.12.1 with embedded LuaJIT. ARM
  releases carry the Debian build's `libstdc++` and `libgcc_s` privately, after
  the stock Raspbian runtime was found to crash `std::filesystem` traversal in
  the engine. System libraries are not replaced.
- The v1 Lua [mode API](API.md): parameters bound to knobs with soft takeover,
  named, custom and global palettes, immediate primitives, reusable meshes,
  ES2 fragment shaders, up to eight render targets for feedback and
  reduced-resolution rendering, perspective camera and depth, images, scenes
  and screenshots.
- Stereo waveform, FFT and band analysis on a nonblocking audio ring; MIDI
  notes, CC, clock and transport over ALSA sequencer ports; OSC from the stock
  `eyesyhw` daemon.
- Lua, shader, input and resource errors are reported without stopping the
  render loop. Changed `.frag` files recompile as a transaction and keep the
  previous program on failure.
- Bounded WAV analysis input and frame-indexed record/replay of controls,
  including a deterministic replay mode with synthesized audio; see
  [input workflow](INPUT-WORKFLOW.md).
- The `scenes/` directory is scanned at startup and its mtime polled every
  second, so scene files added or removed outside the engine show up without a
  key press.

The engine repo ships one mode, `starter`. Every other mode lives in a mode
pack repo and is assembled into `modes/` with `./eyesyctl modes sync`; see
`modes/README.md`.

## Display

- **Direct KMS** (`--kms`, `engine/src/kms_window.*`): the engine takes DRM
  master, picks a mode from the kernel's EDID list only, and scans out through
  GBM/EGL on V3D. This is the production path; Xorg is not used, because any
  Xorg session on this board left HDMI blanked until a power cycle
  ([HDMI display issue](HDMI-DISPLAY-ISSUE.md)).
- **Offscreen** (`--offscreen`): a surfaceless EGL pbuffer, used to run
  packaged modes on the device GPU without touching the display. See
  [display backends](DISPLAY-BACKENDS.md).
- When the display has no 720p mode, the engine falls back to the first EDID
  mode and says so on stderr and in `status.json` (`mode_fallback`).
- Start the engine with the display (or capture-dongle stream) already live.
  Started with no sink, it fails its start check and the fallback hands over to
  stock; a start with the sink missing can also leave output degraded until the
  engine restarts with the sink present.

## Instrument layer

The EYESY OS v3 instrument layer is ported and verified on hardware: trigger
audio synthesis, the shift shortcuts (palette cycling, in-place scene update,
hold-to-delete, gain takeover), the key repeater, the knob sequencer with scene
persistence, persist (`ctx.auto_clear`), status LED colours, the stock-layout
HUD, the 43 stock cosine palettes, and a fullscreen menu with Video, Audio &
MIDI, Palettes and Hardware test screens. See the
[parity plan](EYESY-OS-V3-PARITY-PLAN.md).

## Release and deployment

- Archives are byte-reproducible, with payload-derived release IDs and recorded
  source, SDK, container and package provenance. Builds use a digest-pinned
  Debian base image.
- Activation checks the clone ID, board, archive structure, checksums and ELF
  architecture before switching, installs releases immutably, switches with an
  atomic symlink, and keeps a release only once frames advance on the GPU.
- Rollback goes to the previous release or to stock. Re-deploying an installed
  release after a rollback to stock selects it again.
- The engine exits 0 on SIGTERM, so routine stops do not trigger the failure
  path. When the engine keeps failing, `OnFailure` runs the fallback unit,
  which waits for the platform to recover and otherwise starts stock.

See [deployment](DEPLOYMENT.md).

## Tests

`./eyesyctl test` runs the native core tests (CTest: core, WAV, DSP
regression, audio-ring and WAV mutation stress) and the Python unit tests.
`--graphics` adds the integration scripts: pixel-level graphics and
render-target checks, creative and palette checks, input workflow and replay,
and runtime robustness. The engine core has passed AddressSanitizer,
UndefinedBehaviorSanitizer and leak checks, and the producer/consumer audio
ring has passed a three-million-frame ThreadSanitizer stress test.

Two suites run against a deployed device: `tests/device_parity_tests.py` (the
13-step OS v3 parity run) and `tests/device_bench_auto.py` (the automated half
of the bench checklist). `tools/scene_verify.py` checks a mode against the
[scene library](SCENE-LIBRARY.md) contract.

## Recorded runs on hardware

All on a CM3+ spare card running EYESY OS v3.0, with the original card kept
untouched.

| What | Result |
| --- | --- |
| HDMI scanout | Direct KMS live at about 60 fps on `VC4 V3D 2.1`, through a same-boot stock → platform → stock handoff and a platform-owned cold boot. The `HDMI_VID_CTL` latch never set. |
| Deployment and rollback | All four paths: an incompatible previous release is rejected and restored automatically; `--target stock`; `--target previous` in both directions between two healthy KMS releases. |
| Recovery | With no display attached, the engine fails its start check, systemd's start limit trips, and `OnFailure` starts stock in about 9 s. Recovery with the display present is clean. |
| Long runs | A 78.6-minute offscreen run of the first seven modes: 216,000 frames, 1,800 reloads, no errors or audio-ring drops, median RSS up 80 KiB. Two 60-minute observe-only soaks of the deployed service across 28 and 30 modes: no crashes, flat temperature. |
| OS v3 parity | All 13 steps of `tests/device_parity_tests.py`, with HDMI captures at each step. |
| Bench automation | All gates of `tests/device_bench_auto.py`: HDMI latch oracle, MIDI CC 20–24 to knobs, notes, transport, disconnect/reconnect, and a 41-mode render smoke. |
| Audio capture | A bounded capture run on the codec at 48 kHz with no ring drops. No known signal was supplied, so channel separation and response are untested. |

These do not cover physical controls, a known stereo signal, display latency or
cold-boot recovery; those are the remaining manual checks.

## Known limitations

- **Memory growth.** One soak measured same-mode RSS growth of about 73 KB per
  reload (about 2.2 MB/h at its switching rate); a later soak saw flat per-mode
  RSS. Not yet attributed.
- **MIDI after client churn.** MIDI input was seen to stop being applied after
  a long session with many transient ALSA clients, until the engine restarted.
- **Memory limits.** The device kernel has the memory cgroup controller
  disabled, so systemd `MemoryMax` has no effect. `tools/soak_guard.py` enforces
  RSS, temperature and duration limits by PID instead.
- **Provisioning.** Restoring the read-only root immediately after apt has not
  been qualified live, and apt repositories are not pinned.
- **Bench unit button matrix.** The CM3+ spare emits bursts of spurious key
  events; a spurious save press writes a scene. See the
  [bench checklist](BENCH-CHECKLIST.md).
