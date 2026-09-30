# EYESY Customisation: Brainstorm

> **Background research, 2026-07.** Written before this engine existed, to decide
> what to build. It is kept for context and is not updated; for what the platform
> does now, see the [README](../../README.md) and the [mode API](../API.md).

Ideas organised by depth of intervention. Roughly in ascending order of how deep you go.

## Depth 0 — Extend the existing mode system (what the device was designed for)

1. **New modes in stock style.** Each mode is one `main.py` with `setup()`/`draw()`. Drop a folder into `/sdcard/Modes/`. Start with the classic scope family, then move to:
   - **FFT visualizer** — the engine only gives you a 100-sample waveform; do a numpy FFT on `audio_in` (or keep your own longer history) and draw bars/spectrum. No stock mode does true spectral analysis.
   - **Starfield / warp tunnel** driven by audio energy + MIDI notes (note = new ship, velocity = speed).
   - **Conway/cellular automaton** fed by the waveform (there's a `Cellular-Automata-Video-Synthesizer` repo in the same org for reference).
   - **Audio-reactive font/typewriter** — `T - MIDI Note Printer` exists; extend with pitch → glyph, velocity → size.
2. **Palette work.** Palettes are `A + B·cos(2π(Ct+D))` — a 12-number cosine formula. You can design palettes that are impossible with normal gradients (periodic, multi-hue loops). A small Python generator to explore/pretty-print palettes → `System/palettes.json` is a weekend project and immediately changes the look of every mode.
3. **Scene macros.** Scenes only store knobs, but nothing stops a *mode* from storing its own state in a file. Build one "director" mode that reads a JSON timeline (time → mode, knobs, palettes) and sequences your whole rig like a video jingle.
4. **Knob-sequencer extensions (mode-level).** The built-in seq is 1000 frames, all-or-nothing. In a mode you can keep your own longer per-parameter envelopes.

## Depth 1 — Patch the engine (small surgical changes to `eyesy.py` / `main.py`)

5. **Adaptive FPS / uncapped rendering.** `clocker.tick(30)` is a constant. Make it read from config; drop the cap for menu mode or when idle, or auto-throttle when a frame runs long.
6. **Longer audio history.** The 100-slot ring buffer is the single biggest limitation for interesting visuals. Bump `BUFFER_SIZE` to 512/1024, or keep a 2D history (scrolling wave). Backward-compatible: modes read `audio_in[0..99]` fine.
7. **Better trigger detection.** Currently `peak > 20000`, instant on, no release. Add attack/release smoothing + sensitivity per trigger source in config.
8. **Deeper scenes.** Add fields: per-mode custom state (pickled dict), knob-seq length/loop, LFO rates, trigger source. The scene JSON schema is your own to extend — old scenes just fall back to defaults (the code already validates per-field).
9. **Make `load_new_mode` actually work.** It's `print("not working...")`. Implementing it = create the folder, write the file, add to `mode_names`, `imp.load_source` it → the web editor can then *create* modes, not just edit.
10. **Kill `imp` (deprecated), use `importlib`** — small, safe, removes a landmine.
11. **Mode state teardown.** Currently globals from old modes linger. Give the API an optional `teardown(eyesy)` and call it on mode switch; also stop pre-running every mode's `setup()` at boot (run lazily on first use) — faster cold boot.
12. **Frame-diff "trails" in the engine instead of per-mode.** `auto_clear=False` is the only persistence option. Add a fade-amount (blit last frame with alpha N) as an engine feature — every mode gets smooth trails instantly.
13. **FPS/latency stats in OSD** (the FPS counter exists but is commented out in `main.py`) + frame-time histogram. Essential before doing anything ambitious.

## Depth 2 — New subsystems for the engine

14. **A real DSP layer in the audio process.** The audio sub-process is the natural home for: FFT (radix-2, 256/512 pts), band splitting (bass/mid/treble energies), onset detection, tempo estimation, note detection (autocorrelation). Expose as `eyesy.fft[64]`, `eyesy.bands`, `eyesy.beat` so *all* modes benefit. This is probably the highest-value single upgrade.
15. **LFO library.** Engine-level LFOs (sine/tri/square/ramp/random) clocked to MIDI clock or internal, assignable to knobs — turns the EYESY from "5 knobs" into a tiny generative system.
16. **Scene sets / crossfades.** Recall currently snaps. Crossfade knob values over N frames + allow "scene stacks" (play scene A's knobs for 8 beats, then B).
17. **OSC out.** The engine speaks OSC in (hw) but never out. Emit `/eyesy/audio/peak`, `/eyesy/knob/1..5`, `/eyesy/mode` etc. — makes the EYESY a controller for other gear, and lets you record its state for analysis.
18. **Web editor: live preview.** The Flask app already streams logs over WebSocket; add a small WebSocket frame stream (JPEG thumbnail @ 10 fps) so editing a mode in the browser shows the result without the TV.
19. **A "mode pack" format**: zip of modes+palettes, installable from web/USB with dependency check.
20. **Headless "EYESY as render node"**: finish `main_desktop.py` into a real desktop port (SDL window, no ALSA — use Pulse/PortAudio or file input) so you can develop modes at 4K on your workstation and only ship to the Pi. This alone multiplies how much you can do at depth 0.

## Depth 3 — Rewrite the render pipeline (keep the API, swap the engine)

21. **GPU render: pygame → SDL2 + OpenGL (or modern OpenGL via moderngl).**
    - Keep `setup(screen, eyesy)`/`draw(screen, eyesy)` and make `screen` a thin compat object: `draw.line/circle/rect/polygon` batched into GPU draw calls, or just blit to a texture.
    - The `vc4-kms-v3d` overlay is *already enabled* on the Pi — the V3D GPU is sitting idle. This is the single biggest perf win available: 1080p at 60 fps, and 1080p "slow" disappears.
    - Stock modes mostly use line/circle/rect/polygon/scroll — a 2D batcher covers them. Image-based modes blit textures.
22. **Per-frame compute in C/numba for hot loops.** E.g. a `eyesy.scopedraw()` C extension that takes the audio array + parameters and does the whole scope in one call. Or numba-jit the per-mode math. Modest but real (2-5×) on Pi CPUs.
23. **Swap pygame for a different frontend entirely, same "modes" API:**
    - **Raylib** (C, Python bindings) — simpler GPU 2D, built-in camera/affine, easy cross-platform (Pi + desktop).
    - **moderngl + Pillow** — maximum control, shaders available.
    - This is the "explore different frameworks" route: write a `Screen` shim that implements the handful of pygame calls the ~100 stock modes actually use (grep shows a very small surface: `draw.line/circle/rect/polygon`, `transform.scale/rotate`, `Surface`, `image.save`, `Rect`).
24. **Shader-based modes (the fun part).** Once you have a GPU path, add a second mode API: modes can submit a fragment shader + uniforms (time, knobs, audio texture). Suddenly you get plasma, raymarching, feedback loops, and everything from shadertoy. Audio becomes a 1D texture sampled in the shader. This is a *different instrument* while keeping the knobs.
25. **Video feedback engine.** Render at low res (320×180), run a feedback kernel (feedback, mirror, rotate) on the GPU, upscale to output. Classic Eyesy-adjacent visual; cheap on Pi.

## Depth 4 — Rethink the whole system

26. **C/Rust core with Python mode plugins.** Engine loop in C or Rust (real-time safe, no GIL, no 30 fps cap, proper lock-free SPSC audio buffer), modes as Python via CPython embedding — or as WASM — or as shared libraries. The mode API is small enough to keep.
27. **Real-time audio input path.** Replace "100 samples/sec via multiprocessing" with a JACK/ALSA direct-mapped buffer the render loop reads lock-free; add true per-sample triggers. Enables audio-locked animation at sub-ms jitter.
28. **Multi-device / networked EYESYs.** OSC out + a sync protocol (shared MIDI clock or PTP) = two EYESYs rendering complementary halves of one image, or one driving a projection + one a monitor. The ETC repos show Critter & Guitari are comfortable with OSC-over-network patterns.
29. **Boot-from-USB mode packs + OTA updates.** The USB-override mechanism exists; formalise it (versioned packs, signed, auto-updates) and the device becomes a platform, not an appliance.
30. **Replace the Pi's framebuffer path with HDMI + KMS directly** (or a dedicated HDMI encoder) to get proper 60 Hz timing and tear-free output; or capture the output path for recording (loopback to a file at 60 fps).

## Suggested ramp (if you want a path, not just a list)

1. **Weekend 1 (depth 0):** 2-3 new modes + a palette generator. Learn the API, feel the limits.
2. **Weekend 2 (depth 1):** adaptive fps, longer audio buffer, trails-by-fade, FPS stats in OSD. Everything else gets easier.
3. **Weekend 3 (depth 2):** DSP layer (FFT + bands + beat) in the audio process. This is the payoff — all modes, old and new, get better.
4. **Then (depth 3):** the big fork in the road:
   - **3a. "Make the Pi faster"** → SDL2+OpenGL batcher, keep pygame API compat.
   - **3b. "Make it a different instrument"** → shader-mode API on top of that.
   - **3c. "Make it a platform"** → finish the desktop port so you develop where you're comfortable.
5. **Depth 4** is a full-time hobby; do it only if 3a/3b have left you wanting.

## Open questions worth deciding early

- **Do you want stock modes to keep working?** (Decides whether you keep the pygame-shaped `Screen` or can break.)
- **Pi 3 or Pi 4?** (CM4 gets you 2× the CPU and a real GPU driver story; check which CM you have.)
- **Is HDMI out your target, or is it being recorded by something else?** (Changes the display-path work.)
- **Single user or shared?** (If you want to share modes with other Eyesy owners, keep the mode format compatible.)
