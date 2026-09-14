# OpenFrameworks offscreen window (ARM)

`engine/src/offscreen_window.{h,cpp}` provides `createOffscreenWindow(width,
height)` when compiled with `TARGET_OPENGLES`. It creates a surfaceless EGL
GLES2 pbuffer, installs the normal OF programmable renderer, and exposes the
usual OF event/renderer lifecycle without X11, GLFW, stdin, or scanout.

The engine selects this backend with `--offscreen`. The factory registers the
window with OF's main loop before setup; the entry point then runs the app through
it. ARM linking includes EGL/GLESv2. Desktop builds intentionally reject this
flag: desktop headless previews instead use Xvfb. OF event timing targets 60 fps;
the offscreen backend finishes GPU work before swapping so benchmark frames do
not just measure command submission.

The host draws modes into a canvas FBO. Modes may use one inner target at a time.
`tools/of-fbo-surface.patch` preserves the parent surface through OF view-stack
push/pop, avoiding the nested-target orientation bug reproduced by the pixel
tests. Shader geometry and `u_resolution` use the active target's dimensions.

Native CM3+ mode rendering, capture plumbing, and an independent watchdog restart
have been exercised with this backend. It does not prove HDMI output,
Xorg/compositor behavior, physical controls, musical response, or display
latency. Refer to the dated reports rather than extrapolating simple probe
performance.

## Direct KMS scanout window (ARM)

`engine/src/kms_window.{h,cpp}` provides `createKmsWindow()` for the same
TARGET_OPENGLES builds. It opens `/dev/dri/card0`, acquires DRM master,
creates a GBM XRGB8888 scanout surface, binds EGL on V3D, selects a mode
strictly from the kernel connector's EDID-derived list (named and flagged —
client-constructed mode blobs are forbidden on this hardware; see the
HDMI display issue notes), and drives vsync'd page flips. Entry point flag:
`--kms`. The mode actually chosen is logged (name, flags, type, clock) for
bench evidence. Close deliberately leaves the last scanout CRTC enabled, as
stock SDL/KMSDRM does.
