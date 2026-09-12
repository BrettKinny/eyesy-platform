# Next bench-session acceptance checklist

This is a test plan, not an acceptance claim. Existing headless evidence includes
the CLI workflow, offscreen GPU path, capture plumbing, and replay tests; it does not
qualify HDMI scanout, physical controls/MIDI, audio wiring, or full deployment.

## 1. Stock baseline

- Keep the original card untouched as recovery media. Boot stock on the prepared
  spare and confirm stock video, editor access, audio capture,
  physical knobs/buttons, and MIDI behavior.
- Record card identity, boot selection, display orientation, and any existing
  service status before touching the prepared development card.
- Stop immediately and restore stock operation if baseline controls, video, or
  audio are not healthy.

## 2. HDMI, GPU, audio, and recovery probe

Stage a verified ARM package and the existing `tools/probe_device.sh` on the
prepared card. Its invocation is:

```sh
sudo bash /PATH/TO/probe_device.sh UUID_FROM_RECEIPT /PATH/TO/verified/eyesy-engine
```

The script starts a bounded X session, stops stock Python, and attempts to restore
it on exit. Do not manually stop stock first. Before the first bench invocation,
review the script and arrange an independent timed stock-restoration unit, as
used for the headless capture experiment: shell traps alone cannot survive SIGKILL
or power loss. Keep a verified SSH session available. This display probe has not
yet been live-qualified; do not treat the command as unattended-safe acceptance.

Capture the probe output, renderer identity, measured display mode, codec capture,
clean exit, and return to stock. Verify HDMI image, orientation, frame pacing,
left/right audio levels, and that a failed or interrupted probe does not leave
stock video stopped. Stop and roll back to stock on a missing display, wrong
renderer, audio-open failure, or failure to recover the stock service.

## 3. Physical input and settings

- With the platform preview/test path running, exercise all five knobs, trigger,
  scene save/recall, mode navigation, OSD, and settings changes.
- Verify soft takeover after scene recall and confirm the selected trigger source
  (audio, MIDI note, combined, or quarter-note MIDI clock) behaves as configured.
- Exercise physical MIDI note, CC 20–24, clock start/continue/stop, and cable
  disconnect/reconnect. Capture a short video or written result plus any
  `status.json`/`engine.log` evidence available.
- Treat any stuck control, wrong knob mapping, unsafe scene recall, or service
  conflict as a fail; return to stock before further activation work.

## 4. Known stereo signal

- Feed a controlled left-only signal, then right-only signal, then matched stereo
  signal through the known audio path.
- Use the existing headless/WAV workflow where useful, but confirm the physical
  codec path: capture `audio_available`, `audio_source`, sample rate, left/right
  RMS, sequence, and dropped-frame fields from `status.json`.
- Confirm stereo-mesh/reference modes respond to the intended channel and that
  silence/stale input becomes silence. Record signal setup and screenshots.

## 5. Production activation and rollback

Only after the preceding gates pass, use the existing CLI workflow:

```sh
./eyesyctl deploy dist/RELEASE-armhf.tar.gz --host DEVICE_IP --clone-id UUID_FROM_RECEIPT
./eyesyctl status --host DEVICE_IP
./eyesyctl logs --host DEVICE_IP
```

Capture archive/clone identity, deploy output, status heartbeat, renderer, mode,
and service logs. Confirm candidate `active.env`, advancing frames, GPU renderer,
and unchanged stock boot selection.

Previous-release recovery requires two distinct, healthy releases to have been
activated in sequence. First activation alone has no previous platform release;
that missing-history error is expected and must not be bypassed. Then exercise
both recovery cases on the prepared card:

```sh
./eyesyctl rollback --host DEVICE_IP --clone-id UUID_FROM_RECEIPT --target previous
./eyesyctl rollback --host DEVICE_IP --clone-id UUID_FROM_RECEIPT --target stock
```

For each, capture command output, selected symlink/environment state, journal,
and proof that the expected service is running. A retained platform `status.json`
can be stale after stock recovery; require `eyesypy.service` active and visible
stock output rather than using that file as proof. Stop and
restore stock if activation health fails, a renderer is software, a heartbeat
does not advance, or either rollback cannot recover deterministically.

## 6. Latency and soak distinctions

- Measure HDMI-visible latency, physical control feel, and display orientation;
  these are not covered by desktop or offscreen evidence.
- Run the planned 60-minute reference-mode soak and 500-switch memory-growth
  measurement, recording frame timing, RSS, errors, shader warnings, dropped
  audio frames, and temperature when available.
- Keep headless results, emulated/desktop results, and physical acceptance
  results separate. Do not set a hardware-validated release flag from headless,
  software-rendered, or short workflow checks alone.
