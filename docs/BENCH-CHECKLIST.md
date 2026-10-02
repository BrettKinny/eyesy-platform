# Bench checklist

The manual checks that remain before a release can carry
`hardware_validated: true`. They need a person at the instrument, a known
audio source, or a real display.

Already covered on hardware, and not repeated here (see
[implementation status](STATUS.md)): HDMI scanout through direct KMS, deploy
and rollback in all four paths, recovery to stock with no display attached,
60-minute soaks, the 13-step OS v3 parity suite, and the automated half of
this checklist. That automated half is `tests/device_bench_auto.py`: the HDMI
latch oracle, MIDI CC 20–24 to knobs, notes, clock and transport,
disconnect/reconnect, and a render smoke over the mode catalog. Re-run it after
any engine change:

```sh
python3 tests/device_bench_auto.py --host DEVICE_IP --output local/bench-auto-NNN
```

Keep headless, emulated and physical results separate. Never set the
hardware-validated flag from headless, software-rendered or short workflow
checks alone.

## 1. Before you start

- Keep the original card untouched as recovery media and work on the prepared
  spare. Boot stock first and confirm stock video, audio capture, knobs,
  buttons and MIDI are healthy; stop if they are not.
- Record the card's clone ID, the deployed release, and the boot selection.
- Connect the display before the platform starts and keep it connected. The
  engine picks its mode from the display's EDID at start.
- If you observe through an HDMI→USB capture dongle, keep exactly one streamer
  running on it for the whole session: the dongle asserts hot-plug only while
  it streams, and two capture clients collide. A uniform (0,0,0) capture means
  no TMDS signal; a uniform (7,7,7) capture means sync with blanked pixels.
  `tools/vidctl_watch.sh` logs `HDMI_VID_CTL` on the device: `0xc0000000` or
  `0xc0080000` is healthy, and bit 25 (`0xc2000000`) must never appear. See
  [HDMI display issue](HDMI-DISPLAY-ISSUE.md).
- Before timing anything, put the live service on a light scene at about
  60 fps (`./eyesyctl status --host DEVICE_IP`). The engine routes OSC `/key`
  events to the settings menu while it is open (key 1 exits), so a menu left
  open blocks mode switching.
- **Check the button matrix is quiet.** With the engine idle and nothing
  pressed, watch `scenes/` for a few minutes. A spurious matrix transition on
  the save bit arrives as a key 8 press/release pair and writes a scene; a
  held one deletes the loaded scene. The CM3+ bench spare has produced bursts
  of 2–9 spurious saves within 20 s. Any nonzero rate fails the save/delete
  checks and any check that counts scenes. Candidates are an `eyesyhw` restart,
  temperature, or a marginal ribbon contact. Removing stray scene files is
  safe: the engine re-scans `scenes/` within a second.

## 2. Physical controls and settings

- Turn all five knobs through their range and confirm the HUD sliders and the
  mode respond on the right knob.
- Press every button: mode and scene navigation, save, screenshot, trigger, OSD
  and Persist. Check the shift functions (palette cycling, in-place scene
  update, hold Save to delete, sequencer record and play, Shift + Knob 1 gain).
- Recall a scene and confirm soft takeover: a knob does nothing until it
  crosses its saved value.
- In the menu, change the trigger source (audio, MIDI note, combined,
  quarter-note MIDI clock) and confirm each behaves as configured. Exit and
  confirm the setting persists across an engine restart.
- With physical MIDI equipment, repeat notes, CC 20–24, clock
  start/continue/stop, and a cable disconnect/reconnect.
- Treat a stuck control, a wrong knob mapping, an unsafe scene recall, or a
  service conflict as a fail, and return to stock before further work. Record
  a short video or written result plus `status.json` and `engine.log`.

## 3. Known stereo signal

- Feed a left-only signal, then right-only, then matched stereo, through the
  line input.
- Capture `audio_available`, `audio_source`, the sample rate, left/right RMS,
  the sequence counter and the dropped-frame count from `status.json`.
- Confirm a stereo-reactive mode responds to the intended channel, and that
  silence or stale input reads as silence. Record the signal setup and
  screenshots.

## 4. Real display

- On a real HDMI display (not only the capture dongle), confirm image,
  orientation and frame pacing.
- Measure HDMI-visible latency from a physical control or a trigger to the
  change on screen.

## 5. Cold-boot recovery

The recovery path is proven while the device stays powered: with no display,
the engine fails its start check, systemd's start limit trips, and
`OnFailure` starts stock. What remains is the cold-boot half:

1. With the platform owning boot, disconnect the display and restart the
   platform service. Confirm the fallback leaves stock running.
2. Reconnect the display and power-cycle the instrument by hand.
3. Confirm it boots into the platform with live output, a healthy
   `HDMI_VID_CTL`, and a hardware renderer in `./eyesyctl status`.

For every check, capture command output, the selected release and service
state, and the journal. A retained platform `status.json` can be stale after a
fallback to stock; prove stock with `eyesypy.service` active and visible stock
output instead.
