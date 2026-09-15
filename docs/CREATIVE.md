# Creative runtime additions

This slice adds reusable palettes and three reference modes for the v1 Lua API.

## Palette API

`eyesy.palette(phase)` is unchanged: it returns three 0..1 channels from the
existing cosine palette. `eyesy.palette(name, phase)` returns a named palette,
with phase wrapped to `[0,1)` and linearly interpolated between its RGB stops.
Built-in names are `sunset`, `ocean`, `ember`, and `mint`.

Modes may register a palette during `setup` with
`eyesy.define_palette(name, {{r,g,b}, {r,g,b}, ...})`. A palette has 2..16 RGB
stops; channels are clamped to 0..1. Registration replaces an existing name,
including a built-in. Unknown names and malformed stop tables are Lua errors.
Palette stops are converted once during setup rather than rebuilt per draw.

## Reference modes

- `modes/aurora`: ES2 fragment shader ribbons with a custom aurora palette;
  quality knob 3 uses a preallocated 640x360 target below 0.75 and direct
  full-canvas rendering at 0.75 or above.
- `modes/prism-mesh`: reusable 192-vertex audio mesh and 46-vertex faceted strip,
  stereo color separation, depth animation, and named palette lookup.
- `modes/echo-feedback`: alternating full-size targets and render-target feedback,
  audio-reactive source orb, and an ember palette.

All three stay within the runtime limits (two targets maximum, one shader, and
238 mesh vertices per mode) and avoid retaining frame snapshot tables. The mesh modes
reuse their vertex table and mesh handle each frame.

## Knob map

| Mode | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| Starter | Size | — | — | Hue | — |
| Stereo Mesh | Amplitude | Rotation | Depth | Hue | Speed |
| Shader | Shape | — | — | — | — |
| Feedback | Decay | Rotation | Zoom | Hue | Size |
| Aurora | Flow | Glow | Quality | Palette phase | — |
| Prism Mesh | Amplitude | Depth | Spin | Palette phase | Speed |
| Echo Feedback | Decay | Orbit | Scale | Hue | Size |
| Phosphor | Decay | Morph | Gain | Hue | Swirl |
| Kali Bloom | Decay | Morph | Pulse | Hue | Zoom |

Bound parameters follow knob values, so a declared parameter default is not a
substitute for setting the corresponding knob in a replay. Workstation knobs
initially sit at 0.5. Aurora therefore uses its half-resolution path initially;
knob 3 values of 0.75 and above select full resolution.

Three prototypes live under `local/experiments`, outside release packages:
a curved 12-petal mesh sculpture, a shader tunnel, and reduced-resolution echo
feedback. All passed 600-frame native VC4 checks and screenshot inspection,
with no measured short-run median RSS growth. They are not included in the
frozen seven-mode soak or release artifacts.

The reduced-resolution echo uses two 640×360 targets instead of two 1280×720
targets, reducing feedback pixel work at the cost of visibly coarser edges.
Under concurrent stock video plus the soak, one preliminary comparison measured
53.83 ms median frame time for full-size echo versus 44.82 ms for the reduced
variant. This is a shared-load comparison, not an isolated speedup guarantee;
the post-soak repeat below is the stronger comparison.

Evidence: `local/overnight/prototypes-shared-round1/summary.json`.

After the soak stopped, a counterbalanced full/half/half/full comparison ran
900 frames per trial on the same packaged ARM engine, with stock video still
active. Both variants completed cleanly with zero measured median RSS growth:

| Variant | Median frame time, two trials | 900-frame wall time, two trials |
| --- | --- | --- |
| Full-size echo | 29.661 / 29.667 ms | 27.904 / 27.907 s |
| Half-size echo | 21.606 / 21.606 ms | 20.613 / 20.615 s |

This supports roughly 27% lower median frame cost for the reduced-resolution
variant in this offscreen setup, not a universal speedup or HDMI frame-rate claim.
Its coarser edges remain visible, so it stays an explicit experiment rather than
silently replacing the shipping mode. Evidence:
`local/overnight/echo-abba-round1/summary.json`.
