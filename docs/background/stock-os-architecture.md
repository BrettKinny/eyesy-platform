# EYESY Source Research: Architecture

> **Background research, 2026-07.** Written before this engine existed, to decide
> what to build. It is kept for context and is not updated; for what the platform
> does now, see the [README](../../README.md) and the [mode API](../API.md).

Repos examined (cloned to /tmp/eyesy-research, 2026-07):

- `critterandguitari/EYESY_OS` — the "operating system": Python engine + web editor + Raspberry Pi CM3/CM4 platform layer
- `critterandguitari/EYESY_Modes_OSv3` — ~100 stock modes, each a folder with a single `main.py`
- `critterandguitari/` — also has ETC (a sibling Python-based MIDI instrument, very similar architecture), 201-PocketPiano (CHIP-8, ASM), 5-Moons, Cellular-Automata-Video-Synthesizer, etc.

## Hardware

- Raspberry Pi Compute Module (CM3/CM4) on a custom board
- WM8731 audio codec over **SPI** (custom kernel patch needed — see `platforms/eyesy_cm3/README.md`)
- 10 hardware buttons + 5 hardware knobs, exposed over **OSC on localhost:4000** by a C++ daemon (`hw_controls/`, systemd unit `eyesyhw`)
- MIDI-in via a `ttymidi` UART service (the `ttymidi` device) + USB MIDI
- Video out through the framebuffer (`dtoverlay=vc4-kms-v3d,composite`), pygame `set_mode` to the FB
- Read-only root filesystem; user storage on a third ext4 partition mounted at `/sdcard`
- Storage layout: `/sdcard/{Modes,Scenes,Grabs,System}` — a USB stick can override all of it

## Software stack

| Layer | Tech |
|---|---|
| Video engine | Python 3 + **pygame** (SDL2), capped at **30 fps** by `clocker.tick(30)` |
| Audio | `pyalsaaudio` in a **separate multiprocessing.Process**, sharing a `ctypes.Array(c_float, 100)` ring buffer via `multiprocessing` shared memory + lock |
| MIDI | `mido` (both `ttymidi` and USB ports) |
| HW control | C++ daemon sending OSC (knobs, keys, LED) |
| Web editor | Flask + Flask-Sock (WebSocket), ACE code editor, runs as a second systemd service; talks to engine over OSC + `systemctl` |
| UI/menu/OSD | pygame surfaces, hand-rolled `screen_*.py` / `widget_*.py` classes |

## The engine core (~5,300 lines of Python total)

- `eyesy.py` (1,256 lines) — the god object. Holds: knob state + knob **sequencer** (record/playback of knob moves, up to 1000 frames), scenes (save/recall to `/sdcard/Scenes/scene-####/`), palettes, MIDI note state, config, key handling.
- `main.py` (373 lines) — the main loop. Every frame: `osc.recv()` → `midi.recv_*` → knob updates → knob seq → fill `eyesy.knob1..5` → audio copy → `mode.draw(mode_screen, eyesy)` → blit → OSD/menu → flip → `clear_flags()`.
- `sound.py` — audio capture: 32 kHz, 16-bit, period 32, **downsamples to 100 frames per second** by averaging 16 samples each (stereo → L/R). Peak-detect for audio trigger.
- Modes are loaded with **`imp.load_source`** (deprecated module!) at startup; all modes' `setup()` runs up front (memory check), then `draw()` is called per-frame with `sys.modules[mode].draw`.
- A mode is a folder with `main.py` exposing `setup(screen, eyesy)` and `draw(screen, eyesy)`; everything else is module-level globals.

## Key API a mode has

```python
eyesy.xres, eyesy.yres            # 1280x720 default
eyesy.knob1..5                    # float 0..1 (or sequenced)
eyesy.audio_in, eyesy.audio_in_r  # 100-frame L/R buffers, ±32768
eyesy.audio_peak, eyesy.audio_peak_r
eyesy.trig                        # True for one frame when triggered
eyesy.midi_notes[128], eyesy.midi_note_new
eyesy.auto_clear                  # if False, screen persists (trails!)
eyesy.color_picker(v)             # fg color from knob4
eyesy.color_picker_lfo(v, rate)   # LFO'd color
eyesy.color_picker_bg(v)          # sets bg color
eyesy.get_color_from_phase(t, i)  # palette A-Bcos(2π(Ct+D)) formula
eyesy.set_led(n), eyesy.screengrab()
```

## Notable quirks / weaknesses (raw material for deep customisation)

1. **CPU-bound 2D rendering**: everything is `pygame.draw.*` to a software surface, blitted to the FB. 30 fps cap is a constant, not adaptive. 1080p is marked "slow" in the resolution list.
2. **No GPU**: `vc4-kms-v3d` is enabled in config.txt (KMS + V3D) but pygame uses the plain SDL video driver to the framebuffer — the GPU is doing nothing for the user's content.
3. **Audio is heavily downsampled** (100 values/sec) — great for scopes, bad for anything needing detail; the ring buffer is fixed size 100, no history/scroll.
4. **`imp.load_source`** + all modes' `setup()` pre-run at boot = slow cold start, and mode state lives in module globals that never get torn down on mode switch (memory leak across mode changes).
5. **Single 100-sample shared buffer** with a lock per frame; trigger is a simple peak threshold (20000) with no attack/release.
6. **Scenes are shallow**: 5 knob values + palettes + auto_clear + optional knob-seq. No per-mode state, no audio params, no LFO rates.
7. **Knob sequencer is fixed**: 1000 frames max, no looping length control, no per-knob enable.
8. **No external input besides MIDI/OSC**: no file input beyond a few hardcoded "image" modes, no video in, no network content.
9. **Web editor** can edit code live (OSC `/reload`) but `load_new_mode` is literally `print("not working...")` — you can't add a *new* mode from the web, only edit existing ones.
10. **Palettes** are the lovely `A + B·cos(2π(C·t + D))` formula (see `get_color_from_phase`) — an underused gem; user palettes can be loaded from `System/palettes.json`.
11. `main_desktop.py` exists — a desktop variant that fakes the 10 keys with keyboard 1-0 and has audio/MIDI/OSC commented out. It's hacky (hardcoded `/Users/owen1/sdcard`) but proves the engine can run off-device.
12. Error handling: exceptions in `draw()` are caught and printed at 30 Hz — a buggy mode spams the log.
13. The **ETC** repos (sibling project) use the same Python "mother script + modes" pattern — ideas can be cross-pollinated (e.g. ETC_Mother has similar structure).

## Performance reality check

- CPU: Pi 3/4-class (1-2 GHz ARM), Python doing ~50-500 `pygame.draw` calls/frame
- The stock modes are *simple* by design; anything vector-heavy (Boids = 250 boids + obstacle collision) is already the heavy end
- Memory: engine caps its budget at 75% of RAM (`memory_used`), OSD shows it
