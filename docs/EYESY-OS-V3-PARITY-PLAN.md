# EYESY OS v3 Parity: Gap Analysis & Porting Plan

Documented: 2026-09-17  
Baseline comparisons:
- **Upstream specification**: [Official EYESY OS v3 User Manual](https://docs.critterandguitari.com/EYESY/ey_os_3/)
- **Upstream reference code**: `critterandguitari/EYESY_OS` (Python 3 / pygame engine: `main.py`, `eyesy.py`, `osd.py`, `osc.py`, `sound.py`)
- **Current platform**: C++ / openFrameworks 0.12.1 / embedded LuaJIT 5.1 direct-KMS engine (`engine/src/`)

---

## 1. Executive Summary

Our platform replaces the stock 30 fps CPU-pygame software rasterizer with a hardware-accelerated 60 fps GLES2 engine (shaders, meshes, FBO ping-pong feedback targets, 1024-sample stereo FFT, direct KMS scanout, transactional deployment with rollback).

However, while the 10 basic button actions were mapped (`loadMode +/-`, `recallScene +/-`, `saveScene`, `screenshot`, `trigger`, `osd`, `shift`, `autoClear`), **almost the entire stock "instrument interface" layer was left unported**:

1. **Trigger Button Audio Synthesis** — Stock synthesizes an undulating sine wave into the audio ring buffer while held so trigger/scope modes work without external audio. Ours only sets a one-frame boolean flag.
2. **Shift + Button Shortcuts**:
   - `Shift + Mode +/-`: cycle foreground color palette.
   - `Shift + Scene +/-`: cycle background color palette.
   - `Shift + Save`: update current scene in-place (overwrite) instead of appending a new scene.
   - `Hold Save (2s)`: delete currently loaded scene file.
   - `Shift + Screenshot`: knob sequencer play / stop.
   - `Shift + Trigger`: knob sequencer record-enable / stop.
   - `Shift + Knob 1`: live audio input gain adjustment with OSD bar feedback.
   - `Hold Mode / Scene +/- / Trigger`: key-repeater auto-scroll (fires after >10 ticks).
3. **The Knob Sequencer** — Entirely missing (recording, playback, status LED color feedback, per-scene persistence).
4. **On-Screen Display (OSD)** — Ours is a 64px 1-line debug string; stock is a rich HUD (5 knob sliders, stereo VU meters, 128-note MIDI grid, gain bar, palette swatches, trigger indicator, persist state).
5. **The On-Screen Menu System** — Ours is 3 rows of plain text; stock has 9 graphical screens (Video Settings, Audio/MIDI Settings, MIDI PC Mapping, Palettes, WiFi, System/Backups, Factory Diagnostics, Logs, Flash Drive).
6. **Persist (auto_clear) Mechanics** — `main.cpp` skips `ofClear` when `autoClear == false`, but `ctx` does not expose `auto_clear` to Lua, and modes call `e.clear()` unconditionally. The toggle is functionally inert across the fleet.
7. **Hardware LED Feedback** — Multi-color state machine on OSC `/led` (white, magenta, red, green).
8. **USB Storage Override** — Mounting `/usbdrive/Modes` on startup to override internal SD storage.

---

## 2. Feature-by-Feature Gap Analysis

### 2.1 Trigger Button Behavior

| Aspect | Stock OS v3 (`eyesy.py` / `main.py`) | Our Engine (`main.cpp`) | Gap |
|---|---|---|---|
| **Trigger Event** | Sets `eyesy.trig = True` for one frame | `trigger = true;` (consumed in draw) | Identical |
| **Simulated Audio** | While held (`key10_status`), **fills the audio buffer with an undulating sine wave** (`sin(undulate_p * 2π * (i/100) * 25000)`) and sets `audio_peak = 25000` | Does nothing to audio; trigger/scope modes remain dead if no external signal is present | **Missing** — holding trigger must synthesize test audio into the buffer |

### 2.2 Shift + Button Shortcuts & Key Matrix

Stock dispatches hardware keys via `eyesy.dispatch_key_event(k, v)` (`v > 0` = press, `v == 0` = release):

| Key | Normal Function | Shift Function (`key2_status == true`) | Our Current Engine State |
|---|---|---|---|
| **Key 1** | Toggle OSD (`toggle_osd()`) | Toggle Menu (`toggle_menu()`) | Handled (`menu = true`, 3-row text) |
| **Key 2** | **Shift** modifier | — | Handled (`shift = down`) |
| **Key 3** | Toggle Persist (`toggle_auto_clear()`) | — | Handled at engine level, but inert in modes |
| **Key 4** | Prev Mode (`prev_mode()`) | **Prev FG Palette** (`prev_fg_palette()`) | Shift action **dropped** |
| **Key 5** | Next Mode (`next_mode()`) | **Next FG Palette** (`next_fg_palette()`) | Shift action **dropped** |
| **Key 6** | Prev Scene (`prev_scene()`) | **Prev BG Palette** (`prev_bg_palette()`) | Shift action **dropped** |
| **Key 7** | Next Scene (`next_scene()`) | **Next BG Palette** (`next_bg_palette()`) | Shift action **dropped** |
| **Key 8** | Save Scene (new timestamped scene) | **Update Current Scene** (`update_scene()`) | Shift action **dropped** |
| **Key 8 (hold >2s)** | **Delete Current Scene** (`delete_scene()`) | — | Long-press detection **missing** |
| **Key 9** | Screenshot (`screengrab_flag = True`) | **Knob Seq Play/Stop** (`knob_seq_play_stop_key()`) | Shift action **dropped** |
| **Key 10** | Trigger (`trig = True` + sine audio) | **Knob Seq Record** (`knob_seq_record_key()`) | Shift action **dropped** |
| **Knob 1** | Mode Param 1 | **Audio Input Gain Takeover** (`check_gain_knob()`) | Shift action **dropped** |
| **Hold 4/5/6/7/10** | **Key-repeat** (fires every frame after 10 ticks held) | — | Key repeater **missing** |

### 2.3 The Knob Sequencer

Documented in Section 2.5 of the official manual:
- **Record Arm**: `Shift + Trigger` puts sequencer into armed state. Status LED turns **magenta**. Waits for knob movement.
- **Recording**: As soon as any knob moves past threshold, recording begins; LED turns **red**. Captures knob movements frame-by-frame (up to 1,000 frames).
- **Playback**: `Shift + Screenshot` or `Shift + Trigger` stops recording and begins looping playback; LED turns **green**.
- **Stopping**: `Shift + Screenshot` stops playback; LED turns **white**.
- **OSD Indicator**: Knobs display in **green** (playing), **red** (recording), or **white** (idle).
- **Scene Persistence**: If a scene is saved while a sequence is playing, the sequence is saved in the scene file and auto-plays on recall. `Shift + Screenshot` to stop, then `Shift + Save` to update the scene without the sequence.
- **Current status in repo**: Zero sequencer implementation.

### 2.4 Status LED Color Protocol

The hardware daemon (`eyesyhw`) listens on OSC `127.0.0.1:4000/led` for an integer value:

| Value | Manual State | Stock Code Source (`eyesy.py`) | Meaning |
|---|---|---|---|
| `7` | **White** | `stock_eyesy.py:1136` | Running / Stopped |
| `6` | **Magenta** | `stock_eyesy.py:1143` | Knob sequence record-enabled / armed |
| `1` | **Red** | `stock_eyesy.py:1131` | Knob sequence recording |
| `3` | **Green** | `stock_eyesy.py:1124` | Knob sequence playing |

*Note: Our engine currently never sends `/led` to port 4000; the LED stays at whatever state the C++ daemon initialized it to.*

### 2.5 On-Screen Display (OSD) HUD

| Element | Stock OS v3 HUD (`render_overlay_480`) | Our Current Engine |
|---|---|---|
| **Mode Info** | `Mode: (X of Y) Name` | Mode name only |
| **Storage Source** | Green `SD` or `USB` indicator | None |
| **Scene Info** | `Scene: (X of Y) Name` or `None` | In message string on recall only |
| **Resolution / FPS** | `Screen Size: 1280 x 720` + `FPS: XX` | `XX.X fps` |
| **OS Version** | `v3.0` | None |
| **Knob Sliders** | **5 vertical slider bars**, colored by sequencer state (white / green / red) | Single text: `knob N: 0.XX` |
| **Stereo VU Meter** | **15-segment dual bar graph** (Green → Yellow → Red) | None |
| **Audio Input Level** | Input level / gain bar | None |
| **Trigger Indicator** | Flash indicator when triggered | None |
| **MIDI Note Grid** | **128-note matrix** (32×4 squares) lighting up on active notes | None |
| **Color Palettes** | **Two vertical gradient preview swatches** (FG and BG) | None |
| **Persist Indicator** | Explicit text: `Persist: Yes` / `Persist: No` | None |
| **Error Handling** | Traceback rendered in red box without stopping background mode | Full-screen error wipe |

### 2.6 On-Screen Menu System

Stock provides 9 graphical screens navigated with Scene buttons (up/down), Mode buttons (value change), and Save (confirm):
1. **Home / Main Menu**: Icon grid / list navigating to sub-screens.
2. **Video Settings**: Select HDMI resolution (720p, 1080p, etc.) and composite format (NTSC/PAL) with restart prompt.
3. **Audio & MIDI Settings**: Trigger Source (Audio, MIDI Note, Audio+Note, MIDI Clock divisions), MIDI Channel (1–16), CC mapping for Knobs 1–5, CC for Persist (CC 25 default), CC for Palettes, CC for Mode selection, MIDI Note Mode Selection toggle.
4. **MIDI PC Mapping**: Assign Program Change numbers 1–128 to specific scenes, with live thumbnail preview.
5. **Color Palettes**: Fullscreen preview of FG and BG cosine palettes with waveform parameter graphs.
6. **WiFi & Network**: Scan SSIDs, on-screen keyboard for password entry, display IP address, signal strength, network logs.
7. **System Stuff**: Backup SD to USB, Eject USB drive, Forget WiFi data, Restart Video engine.
8. **Hardware Test**: Interactive diagnostics: potentiometer sweep test (turns green 0→1), button press test (3 presses required), MIDI notes 60/62/64 detection, stereo audio trigger threshold test.
9. **App Logs**: Real-time scrolling systemd / engine log viewer.

*Current state: We have only a 3-row plain text overlay inside the OSD bar for Gain, MIDI Channel, and Trigger Source.*

### 2.7 Persist / Auto-Clear Mechanics

- **Stock**: `eyesy.auto_clear` is read by modes. When true, modes fill background; when false, modes draw a semi-transparent `veil` surface (alpha ~10–30/255) for decaying trails.
- **Our Engine**: Engine skips `ofClear` when `autoClear == false`, but `ctx` does not expose `auto_clear` to Lua, and modes call `e.clear()` unconditionally inside `draw()`. Toggling persist has no visible effect.

---

## 3. Standing Constraints & Standing Freezes

Per `ROADMAP.md:36-37` and `ROADMAP.md:119-120`:
- **Scene-library pacing**: Scene code fixes and rewrites ride the scene-library batches.
- **Rule for porting**: Do **not** execute a sweeping 37-mode draw-idiom rewrite while the scene freeze is active. Keep initial persist work to the engine-side enabler (`ctx.auto_clear` + OSD indicator) and a 1–2 mode pilot (`starter` / `stereo-mesh`). Defer full fleet migration until after physical bench qualification.

---

## 4. Phased Porting Plan

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: Real-time Performance & Hardware Controls               │
│   1.1 Trigger audio simulation (undulating sine wave while held)│
│   1.2 Shift + Knob 1 audio gain live adjustment                 │
│   1.3 Shift + Save (update current scene in-place)              │
│   1.4 Hold Save for 2s (delete current scene)                   │
│   1.5 Hardware key-repeater (hold Mode/Scene +/- to scroll)     │
│   1.6 OSC /led multi-color status updates to port 4000          │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│ Phase 2: Persist Enabler & Minimal Pilot                        │
│   2.1 Expose ctx.auto_clear (bool) in ModeRuntime::snapshot     │
│   2.2 OSD displays "persist: on" / "persist: off"               │
│   2.3 Pilot veil idiom in starter and stereo-mesh               │
│   2.4 Regression tests for polarity and visible trail diff      │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│ Phase 3: Knob Sequencer Subsystem                               │
│   3.1 5-channel circular frame buffer (1,000 frames)            │
│   3.2 State machine: IDLE -> ARMED -> RECORDING -> PLAYING      │
│   3.3 Shift + Trigger (record arm), Shift + Screenshot (play)   │
│   3.4 LED color feedback (White, Magenta, Red, Green)           │
│   3.5 Scene JSON serialization (auto-play sequence on recall)   │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│ Phase 4: HUD & Instrument OSD                                   │
│   4.1 Dedicated openFrameworks vector overlay                   │
│   4.2 5 knob sliders (colored by sequencer state)               │
│   4.3 Stereo VU meters (15 segments) + trigger flash indicator  │
│   4.4 128-note MIDI activity grid                               │
│   4.5 Dual palette preview swatches                             │
│   4.6 Persist status, Scene index/name, Mode index/name         │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│ Phase 5: On-Screen Menu & Global Palettes                       │
│   5.1 Global FG/BG cosine palette manager + System/palettes.json│
│   5.2 Shift + Mode +/- (FG palette) & Shift + Scene +/- (BG)    │
│   5.3 Fullscreen 2D menu overlay engine                         │
│   5.4 Video resolution & composite format switcher              │
│   5.5 Audio & MIDI settings (CC maps, PC scene recall)          │
│   5.6 Factory diagnostics / hardware test screen                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Technical Specifications for Implementation

### Phase 1: Real-time Performance & Hardware Controls

#### 1.1 Trigger Audio Simulation
- **Files**: `engine/src/audio.h`, `engine/src/audio.cpp`, `engine/src/main.cpp`
- **Design**:
  - In `audio.h`: add `std::atomic<bool> synthesizing{false};` and `double undulatePhase{0};`.
  - In `audio.cpp`: inside the processing loop (or synthetic generator in `main.cpp`), when `synthesizing` is true:
    - Advance `undulatePhase += 0.005;`
    - Frequency factor `undulate = ((std::sin(undulatePhase * 2 * M_PI) + 1.0) * 2.0) + 0.5;`
    - Generate sine samples: `val = std::sin((i / 100.0) * 2 * M_PI * undulate) * 25000.0 / 32768.0;`
    - Override peak values to `25000.0 / 32768.0`.
  - In `main.cpp`: in `hardwareKey(10, down)`, set `audio.setSynthesizing(down)`.

#### 1.2 Shift + Knob 1 Live Audio Gain
- **Files**: `engine/src/main.cpp`
- **Design**:
  - In `pollOsc()`: when handling `/knobs` and `shift == true`:
    - If `std::abs(knobs[0] - rawKnob0) > 0.05` (pickup threshold):
      - Update `audioGain = std::clamp(rawKnob0 * 4.0, 0.0, 4.0);`
      - Call `audio.setGain(audioGain);`
      - Set transient message: `"Gain: " + ofToString(audioGain, 2)`.

#### 1.3 Shift + Save (In-Place Scene Update)
- **Files**: `engine/src/main.cpp`
- **Design**:
  - In `hardwareKey(8, true)`:
    - If `shift == true` and `sceneIndex >= 0 && sceneIndex < scenes.size()`:
      - Call `saveSceneInPlace(scenes[sceneIndex]);`
      - Overwrite the existing JSON file at `scenes[sceneIndex]` with current mode, parameters, and autoClear.
      - Message: `"Updated " + scenes[sceneIndex].filename().string()`.

#### 1.4 Hold Save for 2 Seconds (Delete Scene)
- **Files**: `engine/src/main.cpp`
- **Design**:
  - Add `double savePressTime = 0;` and `bool saveHeld = false;`
  - In `hardwareKey(8, true)`: `savePressTime = ofGetElapsedTimef(); saveHeld = true;`
  - In `update()`: if `saveHeld && (ofGetElapsedTimef() - savePressTime > 2.0)`:
    - `saveHeld = false;`
    - If `sceneIndex >= 0 && sceneIndex < scenes.size()`:
      - Remove file `fs::remove(scenes[sceneIndex]);`
      - Reload scenes; update `sceneIndex`; show message `"Deleted scene"`.

#### 1.5 Hardware Key Repeat
- **Files**: `engine/src/main.cpp`
- **Design**:
  - Add `std::array<int, 11> keyHeldTicks{};`
  - In `update()`: for keys 4, 5, 6, 7, 10:
    - If pressed, increment ticks.
    - If `ticks > 10` and `(ticks % 3 == 0)`: call action handler (fast-scroll modes/scenes or rapid trigger).

#### 1.6 OSC `/led` Feedback
- **Files**: `engine/src/main.cpp`
- **Design**:
  - Open UDP send socket to `127.0.0.1:4000`.
  - Helper `void sendLed(int color);`
  - Constants:
    - `LED_WHITE = 7` (normal / idle)
    - `LED_MAGENTA = 6` (sequencer armed)
    - `LED_RED = 1` (sequencer recording)
    - `LED_GREEN = 3` (sequencer playing)
  - Call on state changes and pulse on MIDI notes.

---

### Phase 2: Persist Enabler & Minimal Pilot

#### 2.1 Engine Runtime Context
- **Files**: `engine/src/runtime.h`, `engine/src/runtime.cpp`, `engine/src/main.cpp`
- **Design**:
  - Update `ModeRuntime::snapshot()` signature to accept `bool autoClear`.
  - In `runtime.cpp`: push `lua_pushboolean(lua, autoClear); lua_setfield(lua, -2, "auto_clear");` into `ctx`.
  - In `main.cpp`: pass `autoClear` at call sites (lines 179 and 612).
  - In `main.cpp`: update OSD line to display `(autoClear ? " | persist off" : " | persist on")`.

#### 2.2 Minimal Pilot Fleet
- **Files**: `modes/starter/main.lua`, `modes/stereo-mesh/main.lua`
- **Design**:
  ```lua
  if ctx.auto_clear then
    e.clear(bg_r, bg_g, bg_b)
  else
    e.color(bg_r, bg_g, bg_b, 0.08)
    e.rect(0, 0, ctx.width, ctx.height)
  end
  ```
- **Deferred Modes**: Remaining direct-canvas modes (`prism-mesh`, `facet-terrain`) migrate in the next scene-library pass.

---

### Phase 3: Knob Sequencer Subsystem

#### 3.1 Sequencer Engine
- **Files**: `engine/src/knob_sequencer.h`, `engine/src/knob_sequencer.cpp`, `engine/src/main.cpp`
- **Design**:
  - State enum: `STOPPED`, `ENABLED` (armed), `RECORDING`, `PLAYING`.
  - Storage: `std::vector<std::array<double, 5>> frames;` capped at 1,000 frames.
  - Recording trigger: when `ENABLED`, if any knob moves `std::abs(k - last[i]) > 0.02`:
    - Transition to `RECORDING`.
    - Set LED to `1` (Red).
  - Loop playback: when `PLAYING`, inject recorded values into active knob array each frame; set LED to `3` (Green).
  - Shortcuts:
    - `Shift + Trigger` (Key 2 + 10): Toggle record (STOPPED → ENABLED; RECORDING/PLAYING → STOPPED).
    - `Shift + Screenshot` (Key 2 + 9): Toggle play/stop (PLAYING ↔ STOPPED).
- **Scene Serialization**:
  - Add `"knob_sequence"` object to scene JSON.
  - Auto-start playback on scene recall when sequence data is present.

---

### Phase 4: HUD & Instrument OSD

#### 4.1 Vector HUD Rendering
- **Files**: `engine/src/main.cpp`, `engine/src/osd_hud.h`, `engine/src/osd_hud.cpp`
- **Design**:
  - Top panel (`600x140` at 720p) rendered over canvas when `osd == true`:
    - **5 Knob Sliders**: vertical bars showing 0–1 values. White = manual, Green = seq playback, Red = recording.
    - **Stereo VU Meter**: 15 segments per channel (1–8 Green, 9–14 Yellow, 15 Red).
    - **128-Note MIDI Grid**: 32 columns × 4 rows of small rectangles.
    - **Trigger Flash**: Indicator box lighting on active trigger.
    - **Audio Gain & Input Level Bar**: Visual marker showing current gain multiplier.
    - **Dual Palette Swatches**: Vertical gradient strips showing current FG and BG color maps.
    - **Status Strings**: Mode index/count, Scene index/count, Persist On/Off, FPS.

---

### Phase 5: On-Screen Menu & Global Palettes

#### 5.1 Global Palettes Subsystem
- **Files**: `engine/src/palette_manager.h`, `engine/src/palette_manager.cpp`
- **Design**:
  - Load `System/palettes.json` containing cosine tuples `(a, b, c, d)`.
  - Maintain active `fg_palette_index` and `bg_palette_index`.
  - `Shift + Key 4 / 5`: decrement / increment foreground palette.
  - `Shift + Key 6 / 7`: decrement / increment background palette.
  - Pass palettes to Lua via `ctx.palette_fg(phase)` and `ctx.palette_bg(phase)`.

#### 5.2 Fullscreen Interactive Menu
- **Files**: `engine/src/menu_system.h`, `engine/src/menu_system.cpp`
- **Design**:
  - Activated by `Shift + OSD` (Key 2 + 1).
  - Sub-pages:
    - **Palettes**: Visual waveform and gradient explorer.
    - **Audio & MIDI**: Trigger source selection, MIDI channel, CC assignments.
    - **Video Settings**: KMS display resolution selection.
    - **Hardware Test**: Interactive diagnostic grid verifying pots, buttons, audio trigger, and MIDI notes.
  - Navigation: Scene +/- for cursor up/down; Mode +/- for value change; Save for enter/confirm; OSD for exit.

---

## 6. Verification and Acceptance Gates

| Phase | Verification Method | Pass Criteria |
|---|---|---|
| **Phase 1** | Headless replay with synthesized trigger + OSC monitor | Holding trigger synthesizes audio in `status.json`; `/led` sends 7, 6, 1, 3 to port 4000; long-press Save deletes scene |
| **Phase 2** | `tests/graphics_tests.py` persist regression test | Polarity assertion passes; grab hashes differ between persist-on and persist-off runs in `starter` |
| **Phase 3** | Automated knob sequencer replay test | Recorded knob movements replay accurately over 120 frames; scene recall restores active sequence |
| **Phase 4** | Headless screenshot inspection of OSD | Sliders, VU meters, MIDI grid, and trigger flash render cleanly at 720p without frame drops |
| **Phase 5** | Interactive menu navigation via recorded inputs | All 9 sub-screens navigate, persist settings to `config.json`, and exit cleanly |
