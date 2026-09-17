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

Stage a verified ARM package on the prepared card. The platform display path is
now direct KMS (engine flag `--kms`): no Xorg runs, the engine takes DRM master
and selects a kernel-EDID mode itself. A live activation health check must show
advancing frames plus a hardware renderer (`VC4 V3D 2.1`, never llvmpipe).

Before any headless benchmark or tier gate, confirm the live service is on a
tier-A scene at ~60 fps (`./eyesyctl status`): a heavy GPU neighbour inflates
every offscreen p50 by 5-7 ms (measured 2026-09-17). Note the engine routes OSC
`/key` events to the settings menu while it is open — key 1 exits — so a stuck
menu silently blocks mode switching and neighbour control.

The HDMI→USB capture dongle is a qualified A/B observer when its UVC pipeline
streams continuously (its HPD line follows its streaming state; without a
client it asserts no HPD and the device sees no display — the engine fails
its probe and the fallback restores stock, which is correct behavior). Keep
exactly one streamer on the dongle (two UVC clients collide fatally) and use
`tools/vidctl_watch.sh` as the latch oracle: `HDMI_VID_CTL 0xc0080000` or
`0xc0000000` is healthy; `0xc2000000` (bit 25) means Xorg-class damage — with
the Xorg path removed this must never appear. Treat a uniform-gray capture
(7,7,7) as "sync present, pixels blanked" and uniform black (0,0,0) as no
TMDS. See [HDMI display issue](HDMI-DISPLAY-ISSUE.md).

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
./eyesyctl package --arm
python3 tools/release.py dist/dev-<payload-id>-armhf.tar.gz --architecture armhf
./eyesyctl deploy dist/dev-<payload-id>-armhf.tar.gz --host DEVICE_IP --clone-id UUID_FROM_RECEIPT
./eyesyctl status --host DEVICE_IP
./eyesyctl logs --host DEVICE_IP
```
Capture archive/clone identity, deploy output, status heartbeat, renderer, mode,
and service logs. Confirm candidate `active.env`, advancing frames, GPU renderer,
and the expected boot selection (stock during gating; platform after the V2
platform-owned boot has passed).

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
