# The "other" OS: EYESY_OF (openFrameworks + Lua)

> **Background research, 2026-07.** Written before this engine existed, to decide
> what to build. It is kept for context and is not updated; for what the platform
> does now, see the [README](../../README.md) and the [mode API](../API.md).

Before (and alongside) the Python/pygame OS v3, there was an
**openFrameworks-based engine** that runs **Lua scripts** — and it *is* the OpenGL one.

Repos:

- https://github.com/critterandguitari/EYESY_OF — the OF host app (~1,100 lines of C++ total: `src/ofApp.cpp` is 924)
- https://github.com/critterandguitari/EYESY_oFLua_Examples — 14 example Lua modes
- (also `EYESY_Modes_Pygame` — earlier pygame-era mode set, superseded by `EYESY_Modes_OSv3`)

## What it is

- `main.cpp` creates an **`ofGLESWindow`** (OpenGL ES 2.0) at **1920×1080** — real GPU rendering on the Pi's V3D, no 30 fps cap in sight
- `ofApp` hosts an **`ofxLua`** state: each mode folder has a `main.lua` with `setup()` / `update()` / `draw()` — same shape as the Python API
- Same hardware plumbing as the Python OS: **OSC port 4000** for knobs/keys/LED, MIDI notes via `/midinote`, audio via `ofSoundStream` → `audioIn()` callback → `inL` Lua table (L only, R channel commented out), trigger as `trig` bool, scenes/knob-sequencer state mirrored
- A shared `eyesy.lua` library is `require`d by every example (`require("eyesy")`) — it's *not* in the examples repo, it ships in the OS image. It provides the `colorPickHsb(knob, ofColor)` palette calls and presumably the knob/trig glue
- OSD is drawn to an FBO (`osdFbo`, `smallFbo`), IP/wifi polled on a thread

## What the Lua API gives you (from the examples)

Full openFrameworks surface, including things the Python OS can't do:

- **3D**: `of.Polyline` with `addVertex`/`curveTo`, `of.drawBox`, `of.Light` + `of.enableLighting`, `of.enableDepthTest` — genuine 3D scenes with point lights (see `Polyline/main.lua`: 3D scribble with a light)
- **Matrices**: `of.pushMatrix`/`popMatrix`/`translate`/`rotateDeg` everywhere
- **Video in**: a `VIDEO` example (plays a .mov) — the Python OS has no video input at all
- **Textures, meshes, paths, text** as first-class OF objects
- `inL` audio vector + `knob1..5` + `trig` + `midiNote`/`midiVel` + `colorPickHsb`

## Status / caveats

- Timeline: `EYESY_OF` created 2020-04, last pushed 2022-08. `EYESY_oFLua_Examples` pushed 2023-01. Python OS v3 (current shipping) is the newer line — the OF engine was the **earlier/beta** generation. It's "part of EYESY_OS" per its README, but the current v3 image ships the Python engine.
- Only 14 examples, all basic (mostly "draw a shape that reacts to `inL[i]`")
- The `eyesy.lua` shared library isn't published — you'd need it from a v1/v2 image or to reimplement it (the examples show exactly what it must provide: `colorPickHsb`, and the globals `w,h,w2,...`, `knob1..5`, `trig`, `inL`)
- Audio is mono-only (right channel commented out), and the buffer is OF's sound buffer (per-frame samples, not the 100-sample trick) — actually *finer-grained* than the Python OS

## What the source inspection established

The source is a useful base, but the checked-in executable is not a portable escape
hatch:

- It is a 32-bit ARM `linuxarmv6l` binary linked directly to legacy
  `libbrcmGLESv2`, `libbrcmEGL`, and `libbcm_host`. Do not assume it will run on a
  current CM4/KMS image.
- The project declares only `ofxOsc` and `ofxLua`; it does not pin openFrameworks,
  either add-on, or their commits. Reconstructing the build is discovery work.
- It uses LuaJIT 5.1 through `ofxLua`, opens an OpenGL ES 2 window at 1920×1080,
  and captures 256 stereo frames at 11,025 Hz, but only publishes the left channel
  to Lua.
- The host reads modes from `/sdcard/Modes/oFLua`, sends OSC replies on port 4001,
  and already handles mode switching, reload, scene-selected mode names, OSD,
  screenshots, knobs, MIDI, audio trigger, and the hardware trigger button.
- Every public example requires `eyesy.lua`. The host does not inject display
  dimensions or palette helpers itself, so recovering or recreating that module is
  a real compatibility task.

## Recommended direction

**Revive and modernise EYESY_OF as a separate Lua engine first. Do not build a
dual-engine hybrid yet.**

The immediate goal is not to replace OS v3 or preserve all Python modes. It is to
prove that Lua modes make a substantially better instrument: stable 1080p/60 GPU
rendering, detailed stereo audio, 3D, feedback, and shaders, while retaining the
EYESY controls and scene workflow.

Keep the stock Python image as a rollback path. If the Lua engine proves itself,
integrating engine selection into the boot/menu system becomes a later product
decision. Running Python and OF modes inside one process is out of scope.

### Upstream baseline and migration policy

Use two explicit dependency baselines for different purposes:

| Baseline | Dependencies | Purpose |
|---|---|---|
| Historical oracle | openFrameworks 0.11.2 + `ofxLua` 1.4.4, subject to confirmation | Reproduce old behaviour and generate compatibility fixtures; never the production target |
| Production | openFrameworks 0.12.1 + a pinned `ofxLua` commit containing its 0.12.1 bindings | Current ARM toolchain, graphics backend, fixes, and maintained development base |

The exact historical versions are an informed starting hypothesis: `ofxLua` 1.4.4
explicitly targets OF 0.11.2 and predates the last EYESY_OF commits. Confirm them
from a recoverable image or build artefacts before treating that pairing as fact.

Do not track either upstream `master` branch at build time. Record immutable commit
IDs, archive or checksum release inputs, initialize the `ofxLua` SWIG submodule, and
make the selected versions visible in the engine's build metadata and OSD.

Start production with **LuaJIT 5.1** for compatibility with the published EYESY
binary and embedded-Linux `ofxLua` configuration. Do not adopt the Lua 5.4 runtime
bundled by current `ofxLua` merely as a side effect of upgrading OF. Keep engine
code behind the Lua C API boundary and keep new mode features under the versioned
`eyesy` table so a later Lua 5.4 migration can be tested independently.

The production migration includes:

- regenerate the project against OF 0.12.1 rather than carrying old generated
  files or binary dependencies;
- replace the legacy Broadcom `libbrcmGLESv2`/`libbrcmEGL`/`bcm_host` display path
  with the graphics/window backend supplied and supported by the target OF ARM
  package, then prove fullscreen output on the real device;
- use the matching OF 0.12.1 `ofxLua` generated bindings; never combine modern OF
  headers with historical bindings;
- compile as the C++ standard expected by OF 0.12.1 and fix filesystem/path
  conversions at the host boundary;
- migrate new vector and matrix code to GLM types while retaining old `of.Vec*`
  behaviour only where the compatibility suite requires it;
- retain `ofSoundStreamSettings`, but select the EYESY codec deterministically,
  handle unavailable devices, and accept variable callback frame counts; and
- expose only a tested subset as stable `eyesy.*` APIs. Raw `of.*` bindings remain
  available for legacy/example compatibility but are not our long-term stability
  promise.

Upstream upgrades after this migration are intentional releases: update OF and
`ofxLua` together on a branch, regenerate bindings, run the complete Lua example
and hardware suite, and only then advance the pinned versions.

### Success criteria

The Lua engine earns further investment when it can:

1. boot on the target EYESY and render for 60 minutes without a crash or runaway
   memory use;
2. sustain 60 fps at the chosen output resolution for the reference 2D mode and
   at least 45 fps for the reference shader/feedback mode;
3. keep knob-to-photon latency below two rendered frames, excluding display
   latency;
4. provide stereo audio, MIDI notes, hardware/audio triggers, mode switching,
   reload, OSD, and screenshots;
5. load all 14 public example modes with either no changes or documented mechanical
   migrations; and
6. recover cleanly from a malformed Lua mode by showing an error screen and allowing
   the next/previous mode controls to work.

These are initial engineering budgets, not claims about the old engine's measured
performance.

## Target architecture

Keep the responsibilities narrow and testable:

| Component | Responsibility |
|---|---|
| `EngineApp` | OF lifecycle, render loop, display/FBO setup, frame timing |
| `ControlInput` | OSC 4000 parsing, knob normalization, keys, MIDI state |
| `AudioInput` | callback-safe stereo capture and immutable render snapshots |
| `TriggerDetector` | sensitivity, attack/release, retrigger holdoff, manual/MIDI sources |
| `ModeRuntime` | Lua state, API injection, load/reload/exit, protected calls, error state |
| `ModeCatalog` | discover and sort mode folders; validate `main.lua` and assets |
| `SceneBridge` | receive recalled mode/state and report current mode on OSC 4001 |
| `Osd` | status only; no mode/runtime ownership |

The audio callback must only write to a preallocated buffer. Lua table conversion,
FFT, trigger analysis, logging, and allocation happen off the real-time audio
callback. The render thread receives one coherent control/audio snapshot per frame.

## Lua mode contract, version 1

A mode is `/sdcard/Modes/oFLua/<mode-name>/main.lua` plus optional local assets. It
may define:

```lua
function setup() end   -- once after a successful load
function update(dt) end
function draw() end
function exit() end    -- best effort before reload/switch/shutdown
```

For initial compatibility, globals remain available:

```lua
w, h, w2, h2                    -- output dimensions and halves
knob1, knob2, knob3, knob4, knob5
inL, inR                        -- latest normalized stereo buffer, -1.0..1.0
trig                            -- true for one render frame per trigger event
midiNote, midiVel               -- latest event; velocity 0 means note-off
colorPickHsb(value, color)      -- legacy helper
```

New functionality should live under a versioned `eyesy` table rather than adding
more globals: `eyesy.apiVersion`, `eyesy.audio`, `eyesy.midi`, `eyesy.palette`, and
`eyesy.scene`. Keep `require("eyesy")` working as a compatibility shim. Define the
units, ranges, lifetime, and edge behaviour of every field in an API reference;
examples are tests, not the specification.

Mode calls must be protected. A load/setup/update/draw failure freezes or clears the
mode FBO, reports one rate-limited error in the OSD/log, and leaves controls alive.
Reload creates a fresh Lua state so stale globals and GPU resources do not leak
between modes.

## Delivery plan

### Phase 0 — Recover and de-risk the build

**Output:** a short compatibility report, a historical behavioural oracle, and a
reproducible OF 0.12.1 desktop build.

- Record the exact target hardware (CM3 or CM4), OS image/version, architecture,
  display path, and audio device names.
- Try the published binary only on a disposable/rollback-capable image; inventory
  its dynamic dependencies and preserve any `eyesy.lua` found on an old image.
- Test the OF 0.11.2 + `ofxLua` 1.4.4 historical hypothesis using object metadata,
  commit dates, add-on APIs, or a known old image. If reproducible, run it only as
  a behavioural oracle and capture fixtures from it.
- In parallel, create the production build using OF 0.12.1, a pinned compatible
  `ofxLua` commit and LuaJIT 5.1. Record all commits, submodules, compiler versions,
  package inputs, and architecture choices.
- Build the production host on desktop first, using simulated OSC and audio if
  necessary. Regenerate its project files and bindings rather than copying legacy
  generated output, then document the Pi native/cross-build path.
- Compile a minimal window/audio probe on the target before porting the complete
  host. It must prove fullscreen GPU output through the current display stack and
  reliable capture from the EYESY codec without legacy Broadcom libraries.
- Add a one-command build and a smoke test that loads a minimal Lua mode.

**Gate:** the production OF 0.12.1 host must build reproducibly on desktop and its
window/audio probe must run on the target hardware. Failure to reproduce the
historical baseline does not block production: retain the old binary, source,
examples, and captured behaviour as references. If current `ofxLua` cannot support
the target architecture cleanly, keep OF 0.12.1 but embed LuaJIT directly with a
small curated binding layer; do not downgrade the production graphics stack merely
to preserve the old wrapper.

### Phase 1 — Establish the compatibility baseline

**Output:** the original 14 examples running on desktop and target hardware.

- Recreate the minimum `eyesy.lua` (`w/h/w2/h2` and `colorPickHsb`) if it cannot be
  recovered. Golden-image test its palette output.
- Add safe handling for zero modes, missing `main.lua`, syntax errors, runtime
  errors, absent metadata, and failed assets.
- Make mode discovery/reload deterministic and prove Lua state teardown with a
  repeated-switch soak test.
- Build a desktop harness that can replay timestamped OSC, MIDI, knob, trigger, and
  audio fixtures. This becomes the fast development loop and regression runner.

**Gate:** all examples load, controls remain usable after a broken mode, and the
engine survives 500 automated switches/reloads without material memory growth.

### Phase 2 — Make it a reliable EYESY engine

**Output:** hardware feature parity for the features worth retaining.

- Port the current OS v3 OSC message contract deliberately; write contract tests
  from captured messages rather than assuming both generations match.
- Publish right-channel audio and increase/configure sample rate and buffer size.
- Replace the raw peak threshold with attack/release, sensitivity, and holdoff.
- Preserve mode selection during scene recall and define which scene fields belong
  to the platform daemon versus the Lua engine.
- Add frame time, audio callback health/xruns, Lua error, and memory metrics to the
  OSD/log.
- Package the binary, Lua library, service definition, and configuration as an
  installable overlay with a documented rollback to the stock engine.

**Gate:** meet the stability and latency criteria above on the actual device, with
audio, MIDI, knobs, scenes, screenshots, reload, and OSD exercised together.

### Phase 3 — Deliver the reason to use Lua

**Output:** three polished reference modes, not more engine surface area.

1. a stereo waveform/mesh mode proving the detailed audio path;
2. a fragment-shader mode using time, knobs, trigger, and audio texture; and
3. a ping-pong FBO feedback mode proving persistence and GPU performance.

Add an engine-owned 1D audio texture, FFT/band data, palette textures/uniforms, and
FBO helpers only as demanded by those modes. Each reference mode gets a declared
performance budget and visual regression captures.

**Gate:** decide from actual use whether Lua is good enough to become the default
engine. A technically successful host with uninspiring modes does not pass.

### Phase 4 — Optional OS integration

Only after the instrument is proven:

- choose Lua-only replacement, boot-time engine selection, or a supervised
  Python/Lua process switch;
- teach the web editor to recognize `main.lua`, validate and hot-reload it;
- version the mode API and create an installable mode-pack format; and
- migrate scene storage only after ownership and rollback semantics are settled.

Avoid a per-mode process switch in the first integration. Engine changes are slow,
failure-prone transitions and should be explicit at boot or from a supervisor.

## Test strategy

- **Unit:** knob normalization, OSC decoding, trigger envelope/holdoff, mode sorting,
  scene mapping, palette math.
- **Contract:** recorded OSC traffic from the hardware daemon; Lua global/table
  types, ranges, and update timing.
- **Integration:** synthetic audio + OSC replay into a hidden/windowed host; assert
  mode lifecycle, FBO output hashes/tolerances, and error recovery.
- **Hardware:** 60-minute soak, 500 switches/reloads, audio disconnect/reconnect,
  rapid scene recall, screenshot writes, and power-cycle/rollback checks.
- **Performance:** p50/p95/p99 frame time, dropped frames, audio xruns, control event
  age at render, RSS/GPU memory over time. Report distributions, not just average
  fps.

## Main risks and exits

| Risk | Early test | Exit |
|---|---|---|
| Old OF/ofxLua stack cannot build on current OS | Phase 0 pinned build | Fresh OF host or direct Lua embedding |
| Legacy Broadcom GLES path conflicts with KMS/CM4 | Minimal fullscreen render on target | Modern OF/GLFW/KMS backend |
| `eyesy.lua` behaviour is unknown | Recover old image; compare examples | Specify and ship a clean v1 shim |
| Current `ofxLua` 0.12.1 work is not a tagged release | Pin a reviewed commit and build all bindings | Maintain a small project fork or curated direct bindings |
| Lua 5.4 changes legacy mode behaviour | Run examples under both runtimes | Ship LuaJIT 5.1 initially; defer 5.4 |
| ARM64 target misses embedded-Linux addon rules | Compile minimal binding probe on target | Add explicit `linuxaarch64` config or use direct embedding |
| Audio callback races with Lua/render thread | TSAN where possible + load/soak fixtures | Double/triple-buffered snapshots |
| Lua bindings lack required modern GL calls | Shader/audio-texture spike | Small curated C++ API bindings |
| Scope expands into cloning all of OS v3 | Phase gates and reference modes | Keep stock image as rollback; defer hybrid |

## Decisions needed before Phase 0

1. **Target board:** CM3 or CM4, including RAM variant.
2. **Rollback medium:** spare SD card/image, or permission to modify the working
   installation with a verified backup.
3. **Product goal:** personal instrument (recommended first) or distributable image
   for other EYESY owners.
4. **Compatibility promise:** the 14 Lua examples only (recommended) or eventual
   compatibility with the ~100 Python modes.

Everything else should be learned through the Phase 0 and Phase 1 spikes rather
than decided in advance.
