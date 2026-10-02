# Display backends

The ARM engine (`TARGET_OPENGLES`) has two windows besides the desktop GLFW
one: a direct KMS scanout window, which the deployed service uses, and an
offscreen window for running modes on the device GPU without touching the
display. Neither uses X11. A standalone GPU probe checks the driver on its own.

## Direct KMS scanout (`--kms`)

`engine/src/kms_window.{h,cpp}` provides `createKmsWindow()`. It opens
`/dev/dri/card0`, takes DRM master, creates a GBM XRGB8888 scanout surface,
binds EGL on V3D, and drives vsync'd page flips. `deploy/eyesy-platform.service`
runs the engine with `--kms`.

The mode is chosen strictly from the kernel connector's EDID-derived list,
preferring an HDMI connector over composite. The engine never constructs its
own mode blob: on this hardware, the Xorg sessions that committed degenerate
blobs were also the ones that left HDMI blanked (see
[HDMI display issue](HDMI-DISPLAY-ISSUE.md)). An operator preference
(`--video-mode WIDTHxHEIGHT[@RATE]`, set from the menu's Video screen) is
honoured only when the EDID list offers a matching mode. Otherwise the engine
takes 1280x720 at 55–65 Hz, and if the display offers no such mode it falls
back to the first EDID mode, reporting the fallback on stderr and in
`status.json` (`mode_fallback`). The chosen mode is logged with its name,
flags, type and clock.

If no display is connected, or it reports no modes, the engine fails at start
with a message saying so. On close it deliberately leaves the last scanout CRTC
enabled, as stock SDL/KMSDRM does.

## Offscreen (`--offscreen`)

`engine/src/offscreen_window.{h,cpp}` provides `createOffscreenWindow(width,
height)`. It creates a surfaceless EGL GLES2 pbuffer, installs the normal
openFrameworks programmable renderer, and runs the usual openFrameworks event
and renderer lifecycle without GLFW, stdin or scanout. The window is registered
with the openFrameworks main loop before setup. The backend finishes GPU work
before swapping, so benchmark frame times measure rendering rather than command
submission.

`eyesyctl headless-test` and `tools/benchmark.py` use this backend to run a
packaged mode on the real VC4 GPU while the instrument keeps running; see
[headless development](HEADLESS-DEVELOPMENT.md). Desktop builds reject
`--offscreen`; desktop headless previews use Xvfb instead.

Offscreen results cover mode rendering, frame cost and capture plumbing. They
do not cover HDMI output, physical controls, musical response or display
latency. Offscreen frame times are also shared-load numbers: the live service
and any other GPU work keep running alongside (see the measurement notes in
[scene library](SCENE-LIBRARY.md#measuring-on-the-device)).

## Render targets inside a window

In every backend the host draws modes into a canvas FBO, and modes may use one
inner target at a time. `tools/of-fbo-surface.patch` makes openFrameworks keep
the parent surface across view-stack push/pop, which fixes the nested-target
vertical inversion the pixel tests reproduced. Shader geometry and
`u_resolution` use the active target's dimensions.

The ARM SDK also gets `tools/of-kms.patch`, which stops openFrameworks
including the legacy Broadcom `bcm_host.h` firmware header on a KMS system and
adjusts the ARM platform defines. `tools/of-kms-link.patch` trims the ARM link
line.

## Headless GPU probe

`tools/headless_gpu_probe.cpp` is a standalone EGL surfaceless/GLES2 check that
needs no display. Build it directly, including inside the ARM build container:

```sh
g++ -std=c++17 -O2 tools/headless_gpu_probe.cpp -o build/headless-gpu-probe-armhf -lEGL -lGLESv2
build/headless-gpu-probe-armhf --frames 60
```

The probe creates a 1280x720 pbuffer, compiles and links a GLES2 gradient
shader, checks exact clear and bounded gradient readbacks, then runs a bounded
number of `glDrawArrays` + `glFinish` frames. It prints one JSON object with
renderer, vendor and version, dimensions, frame count, p50/p95 microsecond
timings, correctness, and software-renderer detection. It exits nonzero for an
incorrect readback or a software renderer. `--allow-software` is for
desktop/CI smoke tests (for example on llvmpipe); it does not make a device
pass.

Passing the probe shows the driver and GPU work. It says nothing about scanout,
audio, input or engine performance. Run it on the prepared development card as
a user in the `render` group, not on your original card.
