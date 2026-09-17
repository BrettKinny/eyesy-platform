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

## bardo-night scenes (2026-09-17, device-qualified; release dev-f2c914333761)

Nine scenes built in one night (reports + evidence:
`local/reports/bardo-night/`, dawn sweep `local/verify-catalog-bardo-dawn/`).
All nine pass the scene contract at 300 frames in the build container's
software GL, and all nine now hold tier C on the device after optimization
(device evidence `local/reports/bardo-device*/`; the dawn llvmpipe p50 of
16.6 ms proved 1.4-4.5x optimistic — llvmpipe timing never predicts VC4).

Device tier (VC4, 600 frames offscreen, tier-A neighbour; release
`dev-f2c914333761`):

| scene | shipped p50 | content |
| --- | --- | --- |
| temple-core | 26.3 | 320x180 ink + 320x180 composite, nearest blit |
| wireframe-bardo | 27.6 | 640x360 (unchanged) |
| tesseract-yidam | 27.6 | 640x360 (unchanged) |
| buddha-1kb | 33.2 | 640x360 (unchanged, borderline) |
| phosphor-seance | 29.5 | 320x180 field |
| mandala-bardo | 30.3 | 352x198, 2-ring eval + exact ink early-outs |
| copper-bar-hymn | 30.5 | 640x360 composite + 8x360 y-only raster |
| slit-scan-vortex | 30.9 | 320x180 |
| koan-terminal | 31.3 | 320x180 pass, 1.5 layout px |

| scene | what it is | knob map |
| --- | --- | --- |
| `mandala-bardo` | rotating sacred-geometry mandala: concentric petal rings grown outward from a base circle, breathing bindu, chalk-guideline fold seams, per-ring counter-rotation | 1 `speed` 0..2 ring rotation; 2 `fold` 6..16 radial symmetry; 3 `rings` 1..6 petal rings; 4 `hue` palette phase (0.32 = the authored saffron-petal / vajra-blue-ring look); 5 `bloom` afterglow |
| `temple-core` | TempleOS shrine corridor: two column rows converging on an altar with a rotating flat-shaded idol, seven-band rainbow backdrop, bell-strike palette rewrite — exactly sixteen CGA colours, no interpolation | 1 `speed` checkerboard scroll (silence-still); 2 `columns` 2..7 pairs per side; 3 `idol` rotation rate; 4 `hue` permutes the six chromatic CGA hues (indices 0 and 7 stay achromatic); 5 `glow` intensity ladder + step-mask halo |
| `buddha-1kb` | the 1k-intro discipline literal: three radial×angular cos terms = counter-rotating standing wave, one fragment formula, one target, no mesh | 1 `density` k 8..34 spatial frequency; 2 `fold` 3..9 angular harmonic; 3 `speed` phase drift 0.08..1.18; 4 `hue` phase in [0.05, 0.95]; 5 `mix` fringe/body separation |
| `wireframe-bardo` | retro-CGI chrome idol: 13-vertex icosahedron → 30 screen-space segments with exact 2D point-segment hidden-line removal, over a receding checkerboard | 1 `scale` world radius 0.90..1.90; 2 `tumble` both rotation rates; 3 `glow` wire half-width + halo gain; 4 `hue` slides the `chrome` ramp ±0.12; 5 `depth` floor fog rate |
| `slit-scan-vortex` | Belson/Whitney optical "beings of light": logarithmically-spaced filament layers, up to six counter-rotating into a central void, harmonic-stack angle offset | 1 `density` 2..6 live layers; 2 `rate` 0.10..0.95 rad/s rotation; 3 `streak` filament exponent 9.0→3.0; 4 `hue` slides the `belson` ramp 0.04..0.92; 5 `void` central void radius |
| `copper-bar-hymn` | Amiga copper bar as liturgy: closed-form sine bars with six hard colour bands per slab and a 5x7 dot-matrix scrolltext of "OM MANI PADME HUM", analytic in `y` only | 1 `count` 3..7 bars (slab thins as count rises); 2 `rate` 0.15..1.30; 3 `scroll` 0.6..14.6 cells/s × level; 4 `hue` both ramps + fan phase; 5 `glow` bar exposure + phosphor bloom |
| `koan-terminal` | teletype dharma machine: long-persistence phosphor tube striking out koans character by character, decaying to empty glass — 42 packed 5x7 glyph codes, one fragment pass | 1 `speed` 0.8..22.8 chars/s × level; 2 `scan` 0.14..0.74 raster-line darkness; 3 `glow` 0.30..1.85 bloom + halo; 4 `hue` ink phase 0.24..0.66 on the `phosphor` ramp; 5 `flicker` 0.20..1.30 beam flicker + hum bar |
| `tesseract-yidam` | four-dimensional meditation idol: the 8-cell's 16 vertices / 32 edges rotated in two commuting 4D planes, perspective-projected 4D→3D→2D and drawn as luminous wires | 1 `scale` 0.70..1.45 world units; 2 `rotate` XW 0.10..1.00 and YZ 0.13..1.18 rad/s (bass/mid scaled); 3 `dissolve` level-scaled wire dropout; 4 `hue` ramp band centre 0.28..0.54; 5 `glow` wire half-width + halo |
| `phosphor-seance` | spirit photography as video feedback: the field is the phosphor, re-sampled through a breath of rotation/zoom (Rutt/Etra drift) and stamped by blurred face-sigil presences on closed-form orbits | 1 `decay` afterglow clamp 0.970..0.995; 2 `drift` rotation per pass; 3 `ghosts` 2..5 head count, exposure divided by count; 4 `hue` `seance` ramp phase + slow auto-advance; 5 `jitter` per-pixel luminous hash |

Shared facts from the night worth carrying forward:

- **Knobs rest at 0.5, not at the declared `e.param` defaults.** The engine
  writes the knob snapshot over every declared default each frame, so a
  headless preview and a fresh device show all five at 0.5; the verifier's
  `base` zeroes all five instead (one *extreme*, not the resting state).
- **Deliberate knob-slot deviations** (mode header fixes the assignment, and
  the decision is documented in each report): `buddha-1kb` (1/3 swapped),
  `wireframe-bardo` (1 is size, 2 is motion), `slit-scan-vortex` (1 is
  density, 2 is motion), `copper-bar-hymn` (2/3/5), `koan-terminal` (2/3/5),
  `phosphor-seance` (1 is afterglow, 5 is jitter).
- Cyclic hue ramps make the verifier's `knob4-max` diff legitimately 0.0
  (`mandala-bardo`, `phosphor-seance`); the `mid` diff proves the knob live.
- Palette names claimed by the night: `bardo`, `temple`, `buddha1k`, `chrome`,
  `belson`, `copper`, `phosphor`, `yidam`, `seance`. `phosphor` is a
  re-definition — the shipped phosphor mode owns that name too; a later
  `define_palette` overwrites the entry and the 32-name cap (four built-ins
  preloaded) only counts *new* names, so the two modes simply re-define it on
  load and there is no duplicate-name error.
- **Optimization levers that delivered on VC4** (first gate missed tier C on
  six of nine; see `docs/STATUS.md` 2026-09-17): move full-res composite
  work into the content-resolution target and upscale with a nearest
  resample pass (`floor(uv*RES)+0.5`; `ofFbo` targets are GL_LINEAR, so
  `draw_target` upscale blurs chunky looks — temple-core); hoist anything
  frame-constant into Lua uniforms or a baked atlas (copper-bar-hymn font,
  seance orbits/ink, koan tints/flicker); pre-expand per-layer phase
  constants (slit-scan); exploit provable dead work (mandala: at most two
  rings reach a pixel; seance: sigils have bounded support). Pure fill cuts
  alone underdeliver — VC4 has a ~23.5 ms per-frame floor and credits only
  ~0.85 of a nominal fill ratio.
- **Benchmark hygiene**: gate runs need the live platform on a tier-A scene
  at ~60 fps (`./eyesyctl status`); a heavy GPU neighbour inflated every
  measurement by 5-7 ms once. llvmpipe p50 never predicts VC4 (16.6 ms
  flat at dawn vs 26-74 ms real).

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

## Scene verification (tools/scene_verify.py)

Per-scene contract check built on the engine's deterministic replay mode
(fixed 60 fps clock, synthesized 220/440 Hz audio). Every check is an A/B pair
of engine runs whose replays differ only in the stimulus under test; both grab
their final frame at the same sim time, so the pixel delta contains the effect
alone -- free-running motion cancels exactly. The engine is bit-deterministic,
so a dead stimulus produces byte-identical grabs; the effect metric is the
fraction of pixels differing at all, and thresholds are absolute. Mean-abs
diff is reported alongside for magnitude.

Runs per scene (N frames each, default 130): `base` + `base2` (identical
replays -- any nonzero diff invalidates the machine's results), one run per
declared knob at mid and max (mid catches cyclic params such as hue, where
0 and 1 are the same palette phase), a trigger-assisted `knobK-trig` run for
any knob whose mid and max both show no effect (catches trigger-gated
params), audio quiet/loud/freq variants, and a MIDI note-on 30 frames before
the grab.

Asserts: survival (exit 0, no mode_errors/shader_warning), determinism
(base vs base2), no dead knobs (some knob state must change more than
`--min-fraction`, default 0.001, of pixels -- 0.0 for a dead knob),
blank/whiteout bounds and flatness (design laws 1-3 as pixel signatures),
audio reactivity (when the scene references `ctx.audio`), trigger response
(when it references `ctx.trigger`). Unassigned knobs and unreferenced
stimuli are reported, not failed. Aesthetics and family resemblance stay a
human pass over `contact-sheet.png`.

Usage (software GL in the build container; the real-GPU tier gate remains the
device benchmark):

```sh
podman run --rm --init --arch amd64 --userns=keep-id \
  -v "$PWD:/workspace" -v "$PWD/.cache/of:/opt/of" -w /workspace \
  localhost/eyesy-build:bookworm \
  python3 tools/scene_verify.py --mode <scene> --output local/verify-NNN --xvfb
```

Whole catalog: omit `--mode`. Exit 0 iff every selected scene passes.
Evidence per scene: `summary.json`, `contact-sheet.png`, and
`run-<name>/{replay.json,engine.log,report.json,grabs/}`.
