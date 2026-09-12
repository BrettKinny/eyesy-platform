# Headless GPU probe

`tools/headless_gpu_probe.cpp` is a standalone EGL surfaceless/GLES2 check. It
does not require Xorg, GLFW, a display, or HDMI. Build it directly (including
inside the ARM Bookworm build container):

```sh
g++ -std=c++17 -O2 tools/headless_gpu_probe.cpp -o build/headless-gpu-probe-armhf -lEGL -lGLESv2
build/headless-gpu-probe-armhf --frames 60
```

The probe creates a 1280x720 pbuffer, compiles and links a GLES2 gradient
shader, checks exact clear and bounded gradient readbacks, then runs a bounded
number of `glDrawArrays` + `glFinish` frames. It prints one JSON object with
renderer/vendor/version, dimensions, frame count, p50/p95 microsecond timings,
correctness, and software-renderer detection. It exits nonzero for incorrect
readback or software renderers. `--allow-software` is intended only for
desktop/CI smoke tests (for example, llvmpipe); it does not make a device pass.

This is an offscreen driver/GPU test only. Passing it proves neither HDMI
scanout, compositor/Xorg integration, audio, input, nor EYESY engine
performance. Run on the prepared clone with the appropriate `render` group;
do not run it against the stock card.
