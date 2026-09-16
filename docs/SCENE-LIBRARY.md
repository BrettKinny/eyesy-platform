# Scene Library Conventions

The library-wide contract every scene (engine or variant) must follow.
Rationale and family taxonomy: `local/reports/scene-library-blueprint/BLUEPRINT.md`.

## Knob contract (all scenes)

| Knob | Meaning |
| --- | --- |
| 1 | motion / energy (decay, speed, flow) |
| 2 | structure / morph (geometry, pattern constant) |
| 3 | detail / intensity (iterations, density, quality) |
| 4 | hue / palette drift |
| 5 | feedback / warp / zoom |

## Performance tiers (VC4 V3D 2.1, measured offscreen p50)

| Tier | Budget | Measured examples |
| --- | --- | --- |
| A | <= 16.7 ms (60 fps) | pure mesh/line scenes (~1-2 ms GPU); full-res single-pass shaders |
| B | <= 22.2 ms (45 fps) | (reserved) |
| C | <= 33.3 ms (30 fps) | half-res/iterative scenes: wireframe-room 23.5, phosphor 24.0, lorenz-trail 24.0, flow-field-drift 24.1, radar-sweep 23.8, lyapunov-field 28.8, rutt-etra 24.8, penrose-lattice 25.5, outrun-grid 25.3, riley-grating 26.2, complement-flash 26.7, reaction-diffusion 27.5, chladni-plate 27.6, whitney-kaleido 29.1, girih-stars 27.2, kali-bloom 30.3, textmode-field 32.1, plasma-flow 32.7, facet-terrain 33.3 |

Rules: fragment-iterative scenes render at 640x360 (or 480x270 for heavy
fields) and upscale; every scene gets a headless device run asserting its
tier before merge; the fleet envelope is 15.7-33.3 ms.

## milkdrop-engine tiers (dev-e46f786ab44d, 2026-09-16)

The milkdrop engine (one mode, 12 presets) measures per preset on device
(600 frames, offscreen, live platform service as GPU neighbour):

| preset | p50 |
| --- | --- |
| rot-spin 27.3, built-in-spectrum 27.3, sphere-rush 27.4, warp-oscillation 27.8, q-bridge 28.4, custom-wave-petals 28.3, zoom-drift 28.4, darken-drift 29.2, beat-pulse 29.0, custom-wave-ring 31.8 | tier C |
| sector-shards-16 40.4, sector-shards 50.0 | **waived** |

Waiver: the two glow-comp presets ship above tier C (24.6/19.9 fps) after
two optimization rounds (dense 480x270 content, composite at content res,
gather-count fix); the residual is the 5-gather max() composite's fill and
trig cost on VC4 and is intrinsic to the archetype at this content size.
Follow-up levers live in ROADMAP backlog (glow tier work). Everything else
in the engine meets tier C.

milkdrop engine facts (empirical, 2026-09-16):

- Composite through a content-resolution target + `draw_target` upscale —
  full-res composite passes dominate the frame budget; this pattern is now
  standard for any shader-display engine.
- Custom-wave per-point Lua evaluation costs real milliseconds on ARM
  (built-in-wave presets run ~7 ms/frame cheaper than custom-wave presets
  at equal pipeline); author 160-256 samples, not 512+, unless the look
  demands it.
- The milkdrop catalog saturates the 8-target budget (4 targets x 2 content
  sizes); no further in-mode targets are available without dropping dense.
- Warp sampling beyond [0,1] clamps to edge columns: extreme sphere/zoom
  values produce flat edge panels — keep per-frame warp/sphere magnitudes
  bounded (see sphere-rush tune).

## Design law

1. Never add light into the render target you next sample for decay — bloom
   inside a feedback loop self-amplifies to white. Composite with `max()` or
   plain decay.
2. Never clamp an attractor/iteration denominator above ~1e-9; a 1e-4 clamp
   collapses kaliset orbits onto one trajectory (flat gray).
3. Gray-Scott (and any reaction system) must seed `v`: with `v = 0` the
   reaction term is identically zero. Dither both channels against 8-bit
   storage stall.
4. Precompute construction geometry; regenerate only on trigger/param change;
   one reusable mesh handle per scene (8192-vertex cap).
5. Audio drives amplitude/rotation/color-phase; free-running rate uses
   `u_time` only. `ctx.trigger` is the only beat event (no tempo estimate).

## Known engine facts (empirical)

- `uv.y` runs top-down (0 = top of screen) in shader `uv` space.
- `e.palette(name, phase)` stop spacing is cyclic with i/n segments —
  characterize precisely before palette-critical work; Batch 1 scenes with
  palette-critical colors hardcode them.
- `e.text` size is not controllable; build glyph/dot atlases from primitives.

## Scene folder + variant format

- Engines: `modes/<family-name>/main.lua` (+ optional `<family-name>.frag`).
  The engine catalog auto-discovers any folder with `main.lua`.
- Variants: saved scene JSONs (storage/scenes/*.json) — parameters + state,
  never new code. A variant must be recognizable as its family but carry its
  own name, default palette, and trigger behavior.
- Future manifest fields (tags, tier, palette family) ride inside scene
  `state` until the scene schema gains a `library` block.
