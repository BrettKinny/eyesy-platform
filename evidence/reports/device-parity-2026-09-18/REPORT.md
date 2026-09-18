# Device parity re-run and scene hygiene — 2026-09-18

Device: CM3+ spare, <device-ip>, clone `<clone-id>`.
Release: `dev-8fcb282d8437` (armhf), renderer `VC4 V3D 2.1`, direct KMS, 720p60.
Observer: Guermok USB2 HDMI capture dongle (`/dev/video2`), HPD held by a
persistent streamer; every frame below is the composited KMS scanout read back
through that chain, not an engine-side grab.

Runs the OS v3 instrument layer end to end on hardware a second time — the
2026-09-17 run (`evidence/reports/os3-parity-2026-09-17/`) proved the features
with hand-driven captures; this one re-proves them with the automated harness and
leaves the machine clean. It also removes the scene residue the bench unit's
button matrix had accumulated.

## 1. Parity suite

```
python3 tests/device_parity_tests.py --host <device-ip> \
    --frames local/hdmi/latest.png --output local/reports/device-parity-final
```

**Result: `Device parity checks passed` — 13 steps, no assertion failures, 85 s.**
Summary artifact `local/reports/device-parity-final/summary.json`
(sha256 `68887eca1414…`) with six step captures beside it.

| Step | Asserted on `status.json` / disk | Measured |
| --- | --- | --- |
| 01 idle | `mode=starter`, `sequencer=stopped`, `led=7`, `fps>40`, `hud_draw_calls=9`, `mode_errors=0` | 60.31 fps, `hud_draw_calls` 9 |
| 02 trigger tone | replaces the input: `audio_synthesizing`, RMS > 0.3, left == right | mono, RMS 0.538 |
| 03 recording | Shift+Trigger arms and records knob moves, `led=1` | 46 frames |
| 04 playing | Shift+Screenshot plays, `led=3`, frames ≥ recorded | 183 frames |
| 05 save while playing | scene JSON persists `knob_sequence` (> 3 frames), `auto_clear` bool, `fg_palette` | `scene-20260918-005226-806.json`, 183 frames |
| 06 recall | reload restores playback | `sequencer=playing` |
| 07 Shift+Save update | in-place update writes `auto_clear`, drops the stopped sequence, `schema_version=1` | updated on disk |
| 08 hold Save (> 1 s) | deletes the loaded scene, recalls the neighbouring slot | test scene gone from `scenes/` |
| 09 palette cycling | Shift+4/5 step FG, Shift+7/6 step BG and return | `palette_count` 43, indices restored |
| 10 menu screens | Home + Video/Audio & MIDI/Palettes/Hardware test = screens 1-4, Video row restores Auto | `video_mode=""` |
| 11 hardware test | live `pots`/`buttons`/`audio` true, `midi` false (no source attached) | all four as asserted |
| 12 LED protocol | daemon port 4001 receives `[6, 1, 3, 7]` in order; `eyesyhw` active afterwards | `led_codes` exactly that sequence |
| 13 final idle | engine left idle and honest: `led=7`, `menu_screen=-1`, `mode_errors=0` | as asserted |

Frame evidence (all six in this directory, sha256 in `receipt.json`): `01-idle`,
`03-recording`, `04-playing`, `11-hardware-test`, `13-final-idle`,
`14-scenes-cleaned`. The capture tracks engine state — `03`→`04` differ by
29 857 px over a 747×456 box (the mode render moving between sequencer states);
`01`→`03` differ by 913 px (HUD text rows only, as expected for a static scene).

Two frame notes:

- `02-trigger-tone.png` is deliberately absent: it is byte-identical to
  `01-idle.png`. The harness releases the trigger (`keys(10, 0)`) inside the
  remote script and snapshots afterwards, so the scanout is already back at the
  idle state; the tone itself is asserted from `status.json`.
- `14-scenes-cleaned.png` was re-taken after the engine re-scanned the scene
  directory (§2) because the HUD draws from the engine's cached list.

## 2. Scene hygiene

The matrix glitch documented in `docs/BENCH-CHECKLIST.md` §3 had left 47 scene
files dated `2026-09-17` (38) and `2026-09-18` (9) beside the three genuine
`2026-09-13` baselines — 50 files, `scene_count` 50.

- Whole directory tarred to `local/scratch/scenes-before-cleanup-20260918.tar`
  (1 095 680 bytes, 51 entries) before anything moved.
- All 50 files parsed as JSON objects carrying a `mode` key; the 47 non-baseline
  files matched the glitch naming window (`scene-20260917-*`, `scene-20260918-*`).
- The 47 were moved — not deleted — to `/tmp/eyesy-scene-quarantine-20260918` on
  the device (tmpfs, so they survive the session but not a reboot), leaving:

```
scene-20260913-060941-755.json  170 B  music:music 644
scene-20260913-060941-822.json  170 B  music:music 644
scene-20260913-061657-231.json  170 B  music:music 644
```

**The engine does not notice a deletion by itself.** `refreshScenes()` runs only
from `saveScene()` and `recallScene()` (`engine/src/main.cpp:386-401, 447`), so
immediately after the cleanup `status.json` still claimed `scene_count=50`,
`scene_index=49`, `scene: scene-20260918-005320-989`. One Scene-key step re-scanned
and the engine came back consistent: `scene_count=3`, `scene_index=0`,
`scene-20260913-060941-755` loaded, `mode=starter`, `mode_errors=0`, `fps` 60.3 —
visible in the HUD as `Scene: (1 of 3) scene-20260913-060941…` with
`Recalled starter` on the message line. Any future surgery on `scenes/` must end
with a step press (or an engine restart) before reading `status.json`.

Observation window: 120 s, sampling the directory every 5 s with
`menu_screen`/`menu_row` alongside. **Zero** new files, zero spurious saves, zero
OSD events; the directory still held exactly the three baselines at the end. This
bench unit is quiet right now — the bursts are intermittent, not continuous.

## 3. Bench state after this session

- Window and scanout: `HDMI_VID_CTL 0xc0000000` on every sample — a 6 s run of the
  latch oracle `tools/vidctl_watch.sh` (33 samples) plus three standalone reads.
  Capture stream live: `ffmpeg -f v4l2 -input_format
  mjpeg -video_size 1280x720 -framerate 30 -vf fps=2 -update 1` writing 69-82 KB
  PNGs, far above the ~4 KB blank threshold, content alternating only as engine
  state changes.
- Engine: `audio_available` true at 48 kHz, `audio_dropped` 0, `mode_errors` 0,
  `shader_warning` empty, `hud_draw_calls` 9, `auto_clear` true, catalog
  `mode_count` 41, `scene_count` 3, sequencer stopped, LED idle 7.
- Release identity: `/sdcard/eyesy-platform/active.env` →
  `EYESY_RELEASE=dev-8fcb282d8437`; `current` symlink → `releases/dev-8fcb282d8437`;
  `previous.json` → `dev-8460b87739f5`, so a platform rollback target exists. The
  deployed release carries `manifest.json` (per-file sha256, `eyesy-engine`
  `85ab64caea1e…`, `hardware_validated: false`) and `build-provenance.json`
  (binary hash, the three openFrameworks patches, SDK lock `of_v0.12.1_linuxarmv6l`
  `e4b2a135…`, build image `sha256:c54204ed…`, package lock `e7430b2b…`).
- Defect, unchanged: button-matrix bit 3 → key 8, i.e. a spurious press/release
  pair writes a scene and a held one deletes the loaded scene. Rate today was
  zero over two minutes, but it produced 47 files over the preceding day.

## 4. Handoff

The OS v3 instrument layer is delivered and re-proven on hardware. Next platform
milestones: physical bench qualification (`docs/BENCH-CHECKLIST.md`), the
full-formality 60-minute soak, and cold-boot recovery confirmation (see
`ROADMAP.md`). The EYESY-side bench state is settled — known-good release, live
engine, VC4 renderer, a scene visibly animating, the 13-step suite green.

One thing the next bench session should carry: **scene-directory hygiene.**
Re-check `scenes/` for glitch residue and keep a host-side copy after
programming; the save/delete gates in `docs/BENCH-CHECKLIST.md` §3 hold only
while the button matrix is quiet.
