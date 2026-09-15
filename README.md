# EYESY Platform

A personal Lua graphics platform for a CM3+ EYESY, with desktop previews,
openFrameworks rendering, stereo analysis, and isolated Bookworm builds.

## Develop locally

```sh
./eyesyctl bootstrap
./eyesyctl build
./eyesyctl test
./eyesyctl preview feedback --headless --frames 120
./eyesyctl prepare-native
./eyesyctl preview shader --native
./eyesyctl new-mode my-mode
```

The SDK archives are checksummed. Build dependencies live in rootless Podman
containers, not workstation packages. `prepare-native` stages Bookworm runtime
libraries under `local/runtime` so the preview can use the host graphics driver.
Headless previews use software rendering and are not hardware performance evidence.

Desktop controls: **1–5** select a knob; **Up/Down** adjust it; **Left/Right** switch
modes; **R** reloads; **Space** triggers; **N** simulates a MIDI note; **O** toggles
OSD; **C** toggles clearing; **S** saves a scene; **[ / ]** recall scenes; **G** saves
a screenshot. Edit Lua or fragment shaders to hot-reload them.
**M** opens settings: Up/Down selects a row, Left/Right changes its value, and Enter
saves. On the device, Shift+OSD opens settings, Scene buttons select the row, Mode
buttons change the value, and Save persists it.

Modes (27): `starter`, `stereo-mesh`, `shader`, `feedback`, `aurora`,
`prism-mesh`, `echo-feedback`, `phosphor`, `kali-bloom`, `chladni-plate`,
`outrun-grid`, `rutt-etra`, `plasma-flow`, `whitney-kaleido`, `lorenz-trail`,
`reaction-diffusion`, `ascii-wave`, `radar-sweep`, `riley-grating`,
`lyapunov-field`, `flow-field-drift`, `girih-stars`, `penrose-lattice`,
`facet-terrain`, `wireframe-room`, `complement-flash`, and `textmode-field`.
See [API](docs/API.md), [creative modes](docs/CREATIVE.md), and
[scene library](docs/SCENE-LIBRARY.md).
Use [WAV input and event recording](docs/INPUT-WORKFLOW.md) for repeatable sessions.

```sh
./eyesyctl preview starter --headless --frames 60 --replay tests/fixtures/replay.json
./eyesyctl preview starter --headless --frames 510 --switch-every 1
./eyesyctl bootstrap --arm
./eyesyctl build --arm
./eyesyctl package --arm
```

Build outputs are `engine/bin/engine` (desktop) and `engine/bin/eyesy-armhf` (CM3+).
Reports, screenshots, and scenes are under `local/`; packages are under `dist/`.
Do not run desktop and target builds concurrently: they have separate object paths
but share the project source tree and OF packaging hooks.

## Status and hardware work

No HDMI screen attached? Use the [headless development loop](docs/HEADLESS-DEVELOPMENT.md)
to test a package on the EYESY GPU and retrieve screenshots without switching services.

This is a working development implementation, not a hardware-qualified release.
The original EYESY card remains untouched. Follow [deployment](docs/DEPLOYMENT.md)
to prepare the spare card, establish SSH, and validate the GPU/audio probe before
activating the platform. [Implementation status](docs/STATUS.md) distinguishes
completed checks from remaining hardware work. The
[next-session bench checklist](docs/BENCH-CHECKLIST.md) covers those acceptance gates.

## Original research

- [01-architecture.md](01-architecture.md) — how the stock OS/modes work: hardware, software stack, engine internals, mode API, and the quirks/weaknesses that are raw material for customisation
- [02-ideas.md](02-ideas.md) — ~30 ideas organised in 5 depths (new modes → engine patches → new subsystems → render-pipeline rewrite → system rethink), with a suggested ramp and open questions
- [03-of-lua-engine.md](03-of-lua-engine.md) — the earlier/beta **openFrameworks + Lua** OS (`EYESY_OF`): the existing OpenGL engine, what it offers, and how it changes the plan

## Sources

- https://github.com/critterandguitari/EYESY_OS — OS: Python engine (`engines/python/`), web editor (`web/`), CM3/CM4 platform layer (`platforms/`)
- https://github.com/critterandguitari/EYESY_Modes_OSv3 — ~100 stock modes (S/T/U prefixed folders, one `main.py` each)
- https://github.com/critterandguitari/EYESY_OF — the earlier openFrameworks (OpenGL ES 2) host that runs Lua modes
- https://github.com/critterandguitari/EYESY_oFLua_Examples — 14 example modes for the OF/Lua engine
- https://github.com/critterandguitari — org overview (sibling ETC repos, etc.)
