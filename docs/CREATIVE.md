# Creative runtime: palettes, persist and reference modes

How colour and persistence work for a mode, and which modes to read as
examples. The full call list is in the [mode API](API.md).

## Palettes

A mode has three ways to pick colours. Each returns three channels in 0..1.

**A fixed cosine palette.** `eyesy.palette(phase)` returns
`0.5 + 0.5*cos(2π(phase + i/3))` for the three channels: a full hue wheel, and
the quickest way to get a hue sweep from a knob.

**Named palettes with stops.** `eyesy.palette(name, phase)` samples a named
palette, with `phase` wrapped to `[0,1)` and linearly interpolated between its
RGB stops. The built-in names are `sunset`, `ocean`, `ember` and `mint`. A mode
registers its own during `setup` with
`eyesy.define_palette(name, {{r,g,b}, {r,g,b}, ...})`: 2..16 stops, channels
clamped to 0..1. Registering an existing name replaces it, including a
built-in. Unknown names and malformed stop tables are Lua errors. Stops are
converted once at registration, not per draw. Custom palettes are recreated
whenever the mode loads, and at most 32 names can exist, built-ins included;
re-defining an existing name does not count against that limit.

Stop spacing is cyclic, with i/n segments, so the last stop blends back into
the first. When exact colours matter (an authored pair, an equal-luminance
opposition), check the sampled values or hardcode the colours.

**The instrument's palettes.** `ctx.palette_fg(phase)` and
`ctx.palette_bg(phase)` sample the foreground and background palettes the
player has selected, as on the stock EYESY: Shift + Mode cycles the foreground
palette and Shift + Scene the background, the HUD shows both as swatches, and
scenes and `config.json` save the selection. These are the 43 stock EYESY OS v3
cosine palettes (`color = a + b*cos(2π(c*t + d))` per channel). A
`System/palettes.json` in the platform's storage replaces the list: an array of
objects with a `name` and three-element `a`, `b`, `c` and `d` arrays. A mode
that colours itself from these follows the player's choice, the way stock modes
do.

## Persist

The Persist button sets `ctx.auto_clear`. When it is `true` (the default) a
mode clears each frame; when it is `false` the previous frame should stay and
fade. The engine skips its own clear, but a mode that calls `clear()`
unconditionally still wipes the frame, so a mode has to honour the setting
itself. `starter` shows the idiom: clear when `ctx.auto_clear` is true, and
otherwise draw a translucent full-screen rectangle to fade the previous frame.

A mode that keeps a feedback target can treat Persist as its decay control
instead. A pygame-style "draw over the last frame" port needs a persistence
bridge (draw into a target, fade it, blit it), which costs three full-screen
passes; render that pair at reduced resolution (see the
[scene library](SCENE-LIBRARY.md) notes).

## Reference modes

| Mode | Where | What to read it for |
| --- | --- | --- |
| `starter` | `modes/starter/` in this repo | the smallest complete mode: two bound parameters, a palette lookup, audio-reactive size, and the persist idiom |
| `milkdrop` | [eyesy-modes-milkdrop](https://github.com/BrettKinny/eyesy-modes-milkdrop) | a shader engine: warp and composite passes through ping-pong targets at content resolution, a preset catalog, custom per-point waves, and all eight targets in use |
| `s-*` ports | [eyesy-modes-factory](https://github.com/BrettKinny/eyesy-modes-factory) | stock pygame modes mapped onto the immediate primitives and meshes, with stock knob behaviour, palette registration, and reduced-resolution persistence bridges |

Knob maps:

| Mode | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| `starter` | Size | — | — | Hue | — |
| `milkdrop` | Motion | Preset | Detail | Hue | Feedback |

Each factory port documents its own knob map in its header and its
`docs/ports/<slug>.md` report.

Bound parameters follow the knob values, so a declared parameter default is not
a substitute for setting the corresponding knob in a replay. Knobs start at 0.5
on the workstation and on a fresh start of the device.
