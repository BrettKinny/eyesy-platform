# Scene library conventions

The contract every mode (scene) follows: the knob map, the performance budget on
the device, and the design rules that keep feedback and shader scenes stable.

Mode source lives in mode-pack repos, not in this repo: the engine repo owns
`starter` only, and `./eyesyctl modes sync` assembles the packs into `modes/`
for the packager. `./eyesyctl modes list` reports what the packs hold. See
`modes/README.md`. The public packs are
[eyesy-modes-factory](https://github.com/BrettKinny/eyesy-modes-factory) (ports
of the stock library) and
[eyesy-modes-milkdrop](https://github.com/BrettKinny/eyesy-modes-milkdrop) (a
MilkDrop-style preset engine).

## Knob contract

| Knob | Meaning |
| --- | --- |
| 1 | motion / energy (decay, speed, flow) |
| 2 | structure / morph (geometry, pattern constant) |
| 3 | detail / intensity (iterations, density, quality) |
| 4 | hue / palette drift |
| 5 | feedback / warp / zoom |

A mode that needs a different assignment says so in its header. Ports of stock
modes keep the stock knob behaviour instead.

## Performance tiers

Budgets are per-frame p50 on the device GPU (`VC4 V3D 2.1`):

| Tier | Budget |
| --- | --- |
| A | <= 16.7 ms (60 fps) |
| B | <= 22.2 ms (45 fps) |
| C | <= 33.3 ms (30 fps) |

Tier C is the ceiling for anything that ships. Fragment-iterative scenes render
into a 640x360 target (480x270 for heavy fields) and upscale with
`draw_target`. Every mode gets a run on the device before it is merged.

### Measuring on the device

Tier runs use `./eyesyctl headless-test` or `tools/benchmark.py`: 600 frames
offscreen on the device GPU while the deployed service keeps running. That
makes every number a shared-load number, and two things follow.

**There is a per-frame floor.** Even a mode that draws almost nothing pays the
engine's own per-frame cost plus whatever the rest of the device is doing. With
the live service on a light scene, the cheapest 640x360-plus-upscale scenes
measured 23.5–24.1 ms (September 2026), and `starter` measured 24.2–24.5 ms in
the factory pack's quietest sessions. Across other sessions the same `starter`
run measured up to 37.0 ms, and one load spike reached 47.9 ms. Tier A cannot
be shown offscreen; the deployed service itself runs `starter` at about 60 fps
on the KMS path.

**Absolute numbers from different sessions are not comparable.** The floor has
moved by 12 ms between sessions on the same device, and by 13 ms between two
back-to-back runs. So:

- Start from a known condition: the live service on a light scene at about
  60 fps (`./eyesyctl status`). A heavy scene left running, or the settings menu
  left open (OSC `/key` events go to the menu while it is open; key 1 exits),
  once inflated every measurement by 5–7 ms.
- Measure `starter` before and after the modes under test, interleaved, and
  compare each mode with the lowest floor in the same session. The factory pack
  gates on a marginal cost of at most 8.0 ms over that floor; see its
  `docs/device-tier/` receipts.
- Software GL (llvmpipe in the build container) never predicts VC4 cost. One
  batch measured a flat 16.6 ms there and 26–74 ms on the device.

### Measured examples

| Mode | Measured | Notes |
| --- | --- | --- |
| `milkdrop` presets (first twelve slots) | 27.3–31.8 ms | tier C; built-in-wave presets about 7 ms cheaper than custom-wave ones. Per-preset table in the pack's README |
| `eyesy-modes-factory` ports | mostly within 2 ms of the same-session floor | the pack's cost is dominated by the engine's own per-frame work, not draw-call count |
| `s-folia-angles` / `s-folia-curves` (factory) | 45.2 ms at full resolution, 32.96 ms at 320x180 | a persistence bridge costs three full-screen passes; shipped at quarter resolution |

## Optimization levers that worked on VC4

- Move full-resolution composite work into the content-resolution target and
  upscale. `ofFbo` targets are `GL_LINEAR`, so a chunky look needs a nearest
  resample in the shader (`floor(uv*RES)+0.5`) rather than the plain
  `draw_target` upscale.
- Hoist anything constant for the frame into Lua uniforms or a baked atlas.
- Exploit provable dead work: if at most two rings can reach a pixel, evaluate
  two, not all of them.
- Pure fill-rate cuts underdeliver: they return about 0.85 of their nominal
  ratio, on top of the fixed per-frame floor. Pass restructures (fewer
  full-screen passes) delivered at or above estimate.
- Fixed per-pass overhead (target binds, blits, a fade rect) is real: halving a
  persistence bridge's resolution twice returned +21.0 → +11.7 → +8.8 ms.
- Custom per-point Lua evaluation costs real milliseconds on ARM. Author 160–256
  samples per wave, not 512+, unless the look demands it.

## Design laws

1. Never add light into the render target you next sample for decay — bloom
   inside a feedback loop self-amplifies to white. Composite with `max()` or
   plain decay.
2. Never clamp an attractor/iteration denominator above ~1e-9; a 1e-4 clamp
   collapses kaliset orbits onto one trajectory (flat gray).
3. Gray-Scott (and any reaction system) must seed `v`: with `v = 0` the
   reaction term is identically zero. Dither both channels against 8-bit
   storage stall.
4. Precompute construction geometry; regenerate only on trigger or parameter
   change; one reusable mesh handle per scene (8192-vertex cap).
5. Audio drives amplitude, rotation and colour phase; free-running rate uses
   `u_time` only. `ctx.trigger` is the only beat event (no tempo estimate).
6. Check `ctx.auto_clear` before clearing, so the Persist button has an effect
   (`modes/starter/main.lua` shows the idiom).

## Engine facts worth knowing

- `uv.y` runs top-down (0 = top of screen) in shader `uv` space.
- Knobs rest at 0.5 on a fresh start, not at the declared `e.param` defaults:
  the engine writes the knob snapshot over every bound parameter each frame.
- `e.palette(name, phase)` stop spacing is cyclic with i/n segments.
  Characterize it before palette-critical work, or hardcode the colours.
- `e.define_palette` on an existing name overwrites it, and the 32-name cap
  counts only new names, so two modes may define the same palette name.
- `e.text` size is not controllable; build glyph or dot atlases from
  primitives.

## Scene folder and variant format

- Engines: `<mode-name>/main.lua` plus optional `.frag` files and assets, in a
  pack repo. The engine catalog auto-discovers any folder with `main.lua`.
- Variants: saved scene JSONs (`scenes/*.json`) — parameters plus state, never
  new code. A variant must be recognizable as its family but carry its own
  name, default palette, and trigger behaviour. The scene schema is in the
  [mode API](API.md#scene-state-and-failures).
- Future manifest fields (tags, tier, palette family) ride inside scene `state`
  until the scene schema gains a `library` block.

## Scene verification (`tools/scene_verify.py`)

A per-scene contract check built on the engine's deterministic replay mode
(fixed 60 fps clock, synthesized 220/440 Hz audio). Every check is an A/B pair
of engine runs whose replays differ only in the stimulus under test; both grab
their final frame at the same sim time, so the pixel delta contains the effect
alone — free-running motion cancels exactly. The engine is bit-deterministic,
so a dead stimulus produces byte-identical grabs; the effect metric is the
fraction of pixels differing at all, and thresholds are absolute. Mean-abs diff
is reported alongside for magnitude.

Runs per scene (N frames each, default 130): `base` + `base2` (identical
replays — any nonzero diff invalidates the machine's results), one run per
declared knob at mid and max (mid catches cyclic params such as hue, where 0
and 1 are the same palette phase), a trigger-assisted `knobK-trig` run for any
knob whose mid and max both show no effect (catches trigger-gated params), audio
quiet/loud/freq variants, and a MIDI note-on 30 frames before the grab.

Asserts: survival (exit 0, no mode errors or shader warnings), determinism
(`base` vs `base2`), no dead knobs (some knob state must change more than
`--min-fraction`, default 0.001, of pixels), blank/whiteout bounds and flatness
(design laws 1–3 as pixel signatures), audio reactivity (when the scene
references `ctx.audio`), and trigger response (when it references
`ctx.trigger`). Unassigned knobs and unreferenced stimuli are reported, not
failed. The `base` run zeroes all five knobs, so it is one extreme rather than
the resting look, and a cyclic hue knob can legitimately show a zero `max` diff
while its `mid` diff proves it live. Aesthetics and family resemblance stay a
human pass over `contact-sheet.png`.

Usage (software GL in the build container; the real-GPU tier check remains the
device run):

```sh
podman run --rm --init --arch amd64 --userns=keep-id \
  -v "$PWD:/workspace" -v "$PWD/.cache/of:/opt/of" -w /workspace \
  localhost/eyesy-build:bookworm \
  python3 tools/scene_verify.py --mode <scene> --output local/verify-<scene> --xvfb
```

Whole catalog: omit `--mode`. Exit 0 if and only if every selected scene
passes. Evidence per scene: `summary.json`, `contact-sheet.png`, and
`run-<name>/{replay.json,engine.log,report.json,grabs/}`.
