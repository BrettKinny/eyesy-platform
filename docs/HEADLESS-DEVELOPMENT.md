# Develop without an HDMI screen

A screen is not required to edit modes, preview on the workstation, run packaged
Lua/GLES modes on the real EYESY GPU, or retrieve reports and screenshots. It is
still needed (or replaced by suitable HDMI capture equipment) for final scanout,
physical-control, and visual acceptance checks.

## Local loop

```sh
./eyesyctl build
./eyesyctl test --graphics
./eyesyctl preview starter --headless --frames 600
./eyesyctl preview starter --native
./eyesyctl preview milkdrop --headless --frames 600
```

`preview` finds modes in the mode-pack repos checked out beside this one (here
`milkdrop` from `eyesy-modes-milkdrop`), so it does not need a `modes sync`
first. `--headless` uses desktop software rendering: useful for correctness,
not CM3+ performance. Native desktop preview uses the workstation GPU after
`./eyesyctl prepare-native`. The [input workflow](INPUT-WORKFLOW.md) supports
repeatable WAV analysis and recorded control-event replay.

## Spare-card loop

Build the ARM engine when C++ or SDK patches change; mode-only edits only need a
fresh package. Preserve the original SD card and use the prepared development
card whose UUID and SSH host key have been verified.

```sh
./eyesyctl build --arm
./eyesyctl modes sync
./eyesyctl package --arm
./eyesyctl headless-test dist/RELEASE-armhf.tar.gz \
  --host DEVICE_IP --clone-id UUID_FROM_RECEIPT \
  --mode milkdrop --frames 600 --output local/device-test-001
```

Replace the archive, IP, and UUID with the actual values. The command verifies the
archive and card before staging, tests one mode with synthetic audio on the real
GPU, and copies the result folder into the new local output directory. Inspect
`summary.json`, `report.json`, `engine.log`, and `grabs/*.png`. A failed engine run
still attempts to retrieve diagnostics and exits nonzero. Temporary staging and
device experiment reports are retained for inspection; `/tmp` staging disappears
on reboot. Existing local output directories are refused.

This command does not use sudo, stop stock services, activate a release, or change
boot selection. It defaults to `local/eyesy_known_hosts` when available, otherwise
the normal SSH known-hosts file; `--known-hosts PATH` is explicit. It will not
silently trust a new or changed host key. Frames are limited to 1–3600 and the
engine experiment is capped at 120 seconds. Reports explicitly leave full
hardware acceptance false. Other GPU workloads, including stock video, remain
running, so timings are shared-load offscreen measurements; see
[measuring on the device](SCENE-LIBRARY.md#measuring-on-the-device) before
comparing numbers. `--replay PATH` passes a replay file through to the engine,
for example to select one preset inside a mode.

Both paths of the workflow have been exercised on a CM3+: a passing run
(verified upload, real VC4 rendering, local retrieval of the results) and a
deliberately broken draw callback, which returned engine exit 2 and CLI exit 1
while still retrieving the screenshot, log and reports. The backend behind
this command is described in [display backends](DISPLAY-BACKENDS.md).

## What still needs the bench

Display-service activation, rollback to the previous release or stock, and
unattended recovery have been exercised on hardware through the direct-KMS
service; see [implementation status](STATUS.md). What still needs a person is
in the [bench checklist](BENCH-CHECKLIST.md):

- Knob and button feel, and settings changes, on the physical controls.
- Known stereo input signals for channel separation, response, and signal quality.
- HDMI display latency on a real display.
- Cold-boot recovery after a no-display failure.
