# EYESY mode API v1 (development)

The executable embeds LuaJIT and openFrameworks. Modes do not receive raw `of.*`
objects. The API below describes the implemented interface, not every planned extension.

## Lifecycle and context

`main.lua` returns `{api_version=1, setup=function(ctx), update=function(ctx,dt),
draw=function(ctx), teardown=function(ctx), save=function(), restore=function(state)}`.
Only `api_version` and `draw` are required. Reload creates a fresh Lua state. Methods
use plain function calls, not Lua colon syntax. Assets resolve within the mode folder.

`ctx.width/height` are 1280/720; `ctx.time/dt` are seconds. `ctx.knobs[1..5]` are
0..1. `ctx.trigger` is a one-frame boolean. Tables are frame snapshots; do not retain
them across frames. `setup` should create parameters/resources, not consume input.

`ctx.auto_clear` is the Persist setting: `true` (the default) means the mode should
clear each frame; `false` means Persist is on and the mode should let the previous
frame show through, for example by drawing a translucent rectangle instead of
clearing. The engine cannot do this for the mode, so a mode that calls `clear()`
unconditionally ignores the button. `modes/starter/main.lua` shows the idiom.

`ctx.audio` contains 1024 normalized samples per `left`/`right` channel, 513
one-sided Hann-window amplitude bins per `fft_left`/`fft_right`, `sample_rate`,
`rms_left/right`, `peak_left/right`, three `bands` (20–250, 250–4000, 4000–20000 Hz),
`age` in seconds, and `available`. Missing/stale audio becomes silence. FFT bin `i`
corresponds to `(i-1)*sample_rate/1024` Hz. Bands are root-sum-square amplitudes,
not normalized percentages. No beat-tempo estimation is promised.

`ctx.midi.notes[note+1]` and `ctx.midi.cc[controller+1]` are 0..127; `clocks` counts
MIDI clock pulses and `playing` tracks transport. Live input listens to the
configured source channel (default channel 1). `ctx.midi.events` holds per-frame
events with `status`, 1-based `channel`, `a`, `b`, and monotonic `time` in seconds.
Live CC 20..24 controls the five knob values. The settings menu selects audio,
MIDI-note, combined, or quarter-note MIDI-clock triggers.

## Parameters and utility functions

- `eyesy.param(name, default, min, max, knob)` declares a unique parameter in setup.
  Knob 1..5 maps to hardware; 0 leaves it unassigned. Read `ctx.params[name]`.
  Scene recall applies soft takeover until the physical knob crosses its saved value.
- `eyesy.palette(phase)` returns three color channels in 0..1 from a cosine palette.
- `ctx.palette_fg(phase)` and `ctx.palette_bg(phase)` return three channels from the
  instrument's current foreground and background palettes, which the player cycles
  with Shift + Mode and Shift + Scene and which scenes save. They default to the 43
  stock EYESY cosine palettes; `System/palettes.json` in storage overrides the list.
- `eyesy.palette(name, phase)` samples `sunset`, `ocean`, `ember`, `mint`, or a
  custom palette. Phase wraps modulo 1; adjacent RGB stops interpolate linearly.
- `eyesy.define_palette(name, {{r,g,b},...})` defines 2–16 RGB stops, clamped to
  0..1. Names are at most 64 bytes; at most 32 names including built-ins are
  allowed. Custom palettes are recreated on mode load.
- `eyesy.lfo(time, frequency_hz, phase)` returns a sine LFO in 0..1.
- `eyesy.random()` returns a deterministic pseudorandom value in [0,1), reset on load.
- `eyesy.capabilities` reports texture limits, target count, and mesh vertex budget.

## Graphics

Colors use 0..1; coordinates and line width use pixels; rotation uses degrees.

`clear(r,g,b,a=1)`, `color(r,g,b,a=1)`, `rect(x,y,w,h)`, `circle(x,y,r)`,
`line(x1,y1,x2,y2,width=1)`, `text(string,x,y)`.

`push()`, `pop()`, `translate(x,y,z=0)`, `rotate(degrees,x=0,y=0,z=1)`,
`scale(x=1,y=1,z=1)`. Underflow and more than 32 nested matrices are errors.
Matrices, camera, targets, style, and depth state are cleaned up after callbacks.

`begin_camera(x,y,z=800,target_x=0,target_y=0,target_z=0)`, `end_camera()`, and
`depth(boolean)` provide perspective camera and depth testing. Begin a camera before
pushing transforms and pop transforms before ending the camera.

`new_mesh()` returns a handle; `update_mesh(handle, vertices, indices?)` accepts
`{{x,y,z},...}` and optional 1-based triangle-index triples. Without indices it is a
line strip. `draw_mesh(handle)` renders it. Limit: 8192 vertices and 49152 indices.
`mesh(vertices)` is a convenience line strip; prefer reusable handles for animation.

`image(relative_path)` returns a handle; `draw_image(handle,x,y,w,h)` draws it.
`target(w,h)` returns a render target up to output size; `begin_target(handle)`,
`end_target()`, `draw_target(handle,x,y,w=1280,h=720)` manage it. At most eight targets
are allowed. Reading the currently bound target is rejected: alternate two handles
for feedback. Targets start cleared; later persistence is explicit.

`shader(relative_fragment_path)` creates a shader handle. Write an ES2-compatible
fragment body without `#version`. The host supplies a fullscreen vertex shader and
adapts the fragment body for desktop GL. `draw_shader(handle,time,energy,control)`
sets `u_time`, `u_energy`, `u_control`, and `u_resolution`; normalized coordinates
are `varying vec2 uv`. Drawing inside a target uses that target's dimensions for
both the rectangle and `u_resolution`, so shaders can render at reduced resolution
and upscale with `draw_target`. Changed `.frag` files compile as a transaction; failed edits
keep the previous program. Optional arguments five and six are tables of named
uniforms and render-target textures: `draw_shader(handle,time,energy,control,
{my_float=0.2,my_vec={1,2,3}}, {previous=target_handle})`. Scalars and vectors of
length 1..4 are supported; up to six target textures can be supplied. Sampling the
active render target is rejected.

Every shader can read `uniform sampler2D u_audio`: a 1024×2 single-channel texture,
left at y=0.25 and right at y=0.75. Decode samples with `texture2D(u_audio, uv).r *
2.0 - 1.0`. The ES2-compatible texture uses 8-bit normalized samples; use Lua's float
waveforms when that precision is insufficient.

## Scene state and failures

`save()` may return a string-keyed table containing booleans, strings, finite
numbers, and nested tables; arrays, userdata, cycles, and depth >16 are rejected.
`restore(state)` receives that table after setup.

A scene file is JSON with these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1`; other versions are rejected |
| `mode` | the mode folder name; the scene fails to load if that mode is missing |
| `parameters` | declared parameter values by name; knob-bound ones use soft takeover |
| `state` | the table returned by the mode's `save()` |
| `auto_clear` | the Persist setting (default `true` when absent) |
| `fg_palette`, `bg_palette` | indexes of the foreground and background palettes |
| `knob_sequence` | optional: the knob sequencer's recording, an array of five-value frames. It is written only while the sequence is playing, and playback resumes on recall |

Lua errors show an error screen while mode navigation and reload remain available.
Lua is trusted local code, not a security sandbox.

On the device the service runs under a systemd watchdog (`WatchdogSec=10`), and
when the engine keeps failing, `OnFailure` hands the instrument back to stock.
That recovery path has been exercised on hardware with the display disconnected;
recovery across a cold boot is still to be checked.
