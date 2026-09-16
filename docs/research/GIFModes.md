# GIF/Animated-Image Modes on V3D GLES2 — Research & Recommendation

**Scope:** how to play and render GIF (and by extension short animated) content on the
`eyesy` platform — Raspberry Pi CM3+ `vc4-kms-v3d` V3D 2.1, direct-KMS GLES2 engine,
Lua scene API. Evidence cited against the repo.

**Recommendation (TL;DR):** **Offline pre-processing is the primary path.** Decode the GIF to a
flattened PNG-frame sequence **on the workstation at package/asset-build time**, ship it inside
the mode folder (modes/ is already packaged wholesale into the immutable release), and play it
back with the *existing* `image()` / `draw_image()` primitives — or a tiny engine helper on top.
The GPU cost is a texture blit per frame (tier-A territory); the CPU cost is a handful of lazy
upload events on load; GIF source rates (< ~30 fps) replay at 60 fps by frame-hold with zero
decode on the device. It needs **no** on-device codec, no Lua decode effort, and survives the
read-only rootfs (content rides in the release payload, already shipped to `/sdcard`).

Do **not** chase Lua-side GIF decoding (impossible today: the API has no raw-pixel texture-upload
primitive) and treat on-device video decode (mp4/webm) as a separate, heavier follow-up that
requires engine work and GStreamer thread plumbing.

---

## 0. Platform facts that bound every option

Grounding (file → evidence):

- **Renderer.** Direct-KMS/GBM window, EGL context `EGL_CONTEXT_CLIENT_VERSION 2`, an
  `ofGLProgrammableRenderer` initialized for GLSL ES 2 (`engine/src/kms_window.cpp:91-116`).
  Hardware is the BCM2837 `VC4 V3D 2.1` (GL string reported via `main.cpp`; `ROADMAP.md` "27 modes
  … direct KMS … `VC4 V3D 2.1` at ~60 fps").
- **Output.** 1280×720×60; KMS picks a `1280×720`/`55–65 Hz` mode and falls back to
  `connector->modes[0]` (`kms_window.cpp:253-264`). No Xorg in the display path.
- **Lua graphics surface** (`docs/API.md`): `image(relative_path)→handle` and
  `draw_image(handle,x,y,w,h)` are the **only** still-image primitives. `target(w,h)`
  (≤ 8, `GL_TEXTURE_2D`/`GL_RGBA`, depth) + `begin_target/end_target/draw_target`; `shader`
  + `draw_shader` samples only **render-target handles** as textures — images are *not*
  shader-samplable. There is **no** `new_texture`/`update_texture`/pixel-upload primitive.
- **Image loading** is `ofImage::load()` → openFrameworks' **FreeImage** decoder
  (`engine/src/runtime.cpp:609-618`). FreeImage reads PNG/JPG/TIFF/BMP/TGA/GIF — but `ofImage`
  is a *static* image: a `.gif` through `ofImage::load()` yields only the **first frame**.
- **Per-mode budget**: ≤ 32 images (`runtime.cpp:612`), ≤ 8 targets, ≤ 16 shaders,
  ≤ 8192 mesh vertices; `GL_MAX_TEXTURE_SIZE` is reported to Lua as
  `eyesy.capabilities.max_texture_size` (`runtime.cpp:230-236`). VC4 max texture is 4096.
- **Asset residence**: `image()`/`shader()` resolve relative to the **mode folder** and refuse
  `..` escapes (`runtime.cpp:119-122`). Assets ride with the mode.
- **Deployment**: `eyesyctl package` deep-copies the whole `modes/` tree (minus symlinks) into
  an immutable, hash-pinned release that `eyesyctl deploy` stages and atomically activates on
  `/sdcard` (`eyesyctl` `package()`; `docs/DEPLOYMENT.md`). Device root `/` is **read-only**
  (`provision_device.sh` remount dance); only `/tmp` (tmpfs) is a scratch area (`ROADMAP.md`
  "device tools restage after every boot (`/tmp` is tmpfs)").
- **Codec availability on device**: provision installs GStreamer runtimes
  (`libgstreamer1.0-0`, `libgstreamer-plugins-base1.0-0`) and `libmpg123` as **unversioned
  runtime deps of the OF stack** (`tools/provision_device.sh` `apt-get` line), but there is
  **no ffmpeg binary and no video-player binding** anywhere in the engine (grep of `engine/`
  for `ofVideoPlayer|videoPlayer|updateTexture|new_texture` → only the screenshot readback
  `canvas.readToPixels` in `main.cpp:270-273`).
- **Frame budget conventions** (`docs/SCENE-LIBRARY.md`): tier A ≤ 16.7 ms (60 fps), B ≤ 22.2,
  C ≤ 33.3. Blitting a texture is the cheapest op the pipeline offers (~1–2 ms in the pure-mesh
  tier), so GIF playback is fundamentally a tier-A problem once frames are resident.

Two conclusions follow directly:

1. **GIF is not decodable by a Lua mode today.** The API can place a *static* `ofImage`, but a
   mode cannot turn decoded pixels into a texture at runtime. Any "decode in Lua" option first
   requires an engine primitive to upload raw pixels (see §3).
2. **On-device decode (mp4/webm, and any GIF decode) is unsupported by the engine.** The
   GStreamer libs are present but unused; there is no `ofVideoPlayer`, no ffmpeg, no decode
   thread (see §4).

---

## 1. Recommended path — offline transcode to PNG frames, blit in engine (primary)

**How it works.** At content-build/packaging time — on the workstation, inside `eyesyctl` or a
`tools/` script — run the GIF through `ffmpeg`, `gifsicle`, or ImageMagick to emit a **sequence
of flattened (composited, true-color) PNG frames** into the mode folder, e.g.
`modes/<mode>/frames/f0001.png …`. Ship that folder in the normal release. The Lua mode:

```lua
-- setup(): pre-load all frames once (each ofImage uploads its GL texture lazily on first draw)
local n = 12                      -- say 12 frames
local frames = {}
for i = 1, n do frames[i] = eyesy.image(("frames/f%04d.png"):format(i)) end
local t0 = ctx.time

-- draw(): cycle frames at the GIF frame rate, hold between ticks
function draw(ctx)
    local i = math.floor((ctx.time - t0) * fps) % n + 1
    eyesy.draw_image(frames[i], 0, 0, 1280, 720)   -- or into an FBO for feedback/smear
end
```

**Why it wins.**

- **Zero on-device codec.** No GIF/LZW, no ffmpeg, no GStreamer in the picture on the device.
- **Cheap.** Per frame the GPU does one textured quad blit (~1–2 ms tier-A class). CPU cost is
  confined to `setup()`: `ofImage::load` decodes + lazily uploads; 12–32 small frames load in a
  fraction of a second. After that, playback is pointer arithmetic — no per-frame decode, no
  allocation. Current-frame switching among already-uploaded `ofImage`s is free.
- **60 fps from slow source.** GIF source rates (< ~30 fps) hold each frame for
  `ceil(60/source_fps)` output frames — a perfect 60 Hz cadence with no interpolation needed.
- **Survives the read-only rootfs.** Frames are part of the mode payload shipped to
  `/sdcard` in the immutable release (see §0 Deployment). No device-side writes required.
- **Reuses the existing API end-to-end.** Works against the *current* engine with *no* C++
  change. Blitting is exactly what `draw_image` (`runtime.cpp:619-622`) does.

**Cost / memory.** `n × w × h × 4` bytes of GPU texture (plus equal CPU backing while a frame is
alive). Realistic sizes, within the 32-image budget (`runtime.cpp:612`):

| Content | Frames | Res | GPU texture |
| --- | --- | --- | --- |
| Small icon loop | 16 | 160×90 | ~0.9 MB |
| Half-res source GIF | 24 | 480×270 | ~12.4 MB |
| 640×360 GIF loop | 32 | 640×360 | ~29.5 MB |
| Full 720p still-animation | 32 | 1280×720 | ~118 MB — ❌ too big for 32 slots |

So: keep content in 640×360 or below for blended/feedback scenes, or use fewer full-res frames.
V3D shares the muxed SDRAM; the milkdrop full-res composite already dominates the frame budget,
so be conservative at high res (`docs/SCENE-LIBRARY.md` milkdrop facts).

**Integration points.**

- New content: a `tools/gif_to_frames.sh` or a subcommand in `eyesyctl` that runs `ffmpeg` to
  flatten a GIF to `modes/<mode>/frames/f%04d.png` (and optionally downscale). Purely a
  content-build convenience — the *engine* needs nothing.
- Optional but cheap engine nicety (nice-to-have, not required for v1): a `gif(folder)`
  primitive in `runtime.cpp` next to `IMAGE_NEW` (`runtime.cpp:609-618`) that auto-discovers
  `frames/*.png`, pre-loads them, and gives the mode a single
  `draw_gif(handle, frame, x, y, w, h)` — this would enforce the 32-frame cap cleanly. On its
  own, a plain Lua table of handles is already sufficient.

**Risks / mitigations.**

- **Setup stall**: many large frames make mode-load slow. Mitigate by capping frames (the 32
  budget does this implicitly), downscaling, and pre-flattening to a small set. See §3 for
  lazy-loading if ever needed.
- **Budget collision with an existing heavy mode**: the 8-target / 32-image caps are per-mode
  (`ModeRuntime`), not global — a GIF mode keeps its own budget. No cross-mode conflict.
- **GIF cruft**: interlaced/transparent GIFs must be *flattened* (composited over a background)
  during the offline pass, or transparency leaks across the old frame. Flattening is a
  one-line ffmpeg job — do it offline, never at runtime.

---

## 2. C++/engine-side atlas & shader route (extension of §1)

If GIF art must be manipulated per-pixel (feedback smear, decay afterglow, displacement,
palette shift), blitting raw `ofImage`s is not enough because shaders cannot sample images —
they can only sample render-target textures (`runtime.cpp:677-681`, `textures` map → `fbos`).

Two ways to bridge:

- **FBO bridge (no C++ change).** Draw the current PNG frame into a scratch target, then pass
  that target into `draw_shader` as a named sampler (the mode already owns ≤ 8 targets; the
  design law in `docs/SCENE-LIBRARY.md` forbids adding light into the target you next sample).
  Cost: one extra full-res/blit pass per frame — still within tier B/C.
- **Texture-array from one packed atlas (needs a small C++ addition).** Generate one
  PNG spritesheet at build time; add an engine primitive to upload it as a `GL_TEXTURE_2D_ARRAY`
  (VC4 supports arrays up to GLES3; ES2 lacks them, so a single sheet + shader `uv` offset is the
  ES2-safe form). This exists only as a shader-side lookup, and is genuinely optional: the
  per-frame FBO bridge covers the same effects today.

For a first GIF mode, **ship §1 first**; add feedback only where the art needs it, via the FBO
bridge. A dedicated sprite-atlas primitive is only worth building once multiple GIF modes exist.

---

## 3. Lua-side GIF decoding — not feasible as-is (do not pursue without engine work)

The attraction: decode inside the mode, no build-time step. The reality on this platform:

- **No pixel-upload.** The entire API (see §0) has no primitive to turn a byte buffer into a
  texture. A pure-Lua GIF decoder (LZW + color-index expansion + per-frame compositing) would
  have *no way to present its output* to the renderer. This is a hard blocker, not a
  performance concern.
- **Even with a hypothetical `new_texture`/`update_texture`, the CPU budget is wrong.** Pure-Lua
  LZW deinterleave and pixel writes on a CM3+ ARM core cannot keep 60 fps; even 30 fps for a
  GIF-sized frame would consume most of the frame budget (`docs/SCENE-LIBRARY.md` tier C cap
  33.3 ms) before the GPU does anything. V3D is the fast path; the ARM core is the slow one.
- **The dependency would be hand-rolled**, fiddly LZW (variable code widths, sub-block framing,
  frame disposal modes) — real maintenance/spec risk for the only thing the offline path already
  solves at build time.

**Verdict:** skip Lua-side decode. If runtime GIF decode is ever wanted, it belongs in the
engine as an `ofImage`/FreeImage-based loader that composites frames during `setup`, not in Lua.
Covered by §1's `gif(folder)` idea.

---

## 4. Video-transcode route (GIF → mp4/webm + on-device decode) — heavier follow-up

If the art direction is actually **video** (camera footage, long loops larger than a 32-frame
budget, >500 frames), the honest answer is not GIF at all — transcode to `mp4` (H.264) or
`webm` and decode streams:

- **Nothing exists to build on.** No `ofVideoPlayer`, no ffmpeg binary, no decode thread in the
  engine (§0 Codec availability). The provisioned GStreamer libs are passive runtime deps.
- **Required engine work.** Add a decode path (offload thread or GStreamer `appsink`) pumping
  `ofPixels` → texture, plus a Lua `video(file)`/`draw_video()` binding mirroring `IMAGE_NEW` /
  `IMAGE_DRAW` (`runtime.cpp:609-622`). The audio-path precedent (`audio.cpp` WAV playback,
  `AudioInput::work()` thread + ring) is a good structural model for the decode-thread → render
  snapshot handoff (`core.h` `AudioRing`).
- **Latency & CPU risk on V3D.** Software H.264 decode at 720p60 on the CM3+ ARM core is the
  dominant risk; drop to 480p30 or hardware-assisted paths. Catch-up on a dropped frame then
  needs a clock/sequence discipline the current engine does not have.

**Verdict:** out of scope for "GIF modes." It is a distinct, larger project (a VIDEO-capability
engine release). Revisit only if the requirement is genuinely video-length content. The §1
PNG-frame path already handles the *animated-loop* use case that "add GIF support" almost always
means.

---

## 5. Precedent — what the original eyesy line / AV platforms do

- **Original `EYESY_OF` (openFrameworks + Lua) had a `VIDEO` example** that plays a `.mov` via
  OF's own player — i.e. the OF generation supported video-in as a first-class object because OF
  ships a player. That is the reference point for §4, *not* for GIF. (`03-of-lua-engine.md`:
  "**Video in**: a `VIDEO` example (plays a .mov) — the Python OS has no video input at all.").
- **Stock Python eyesy (`EYESY_OS` / `EYESY_Modes_OSv3`) has no GIF/video texture path** — its
  modes are procedural (pygame immediate drawing / vector); this project's Lua API is richer
  (it already has `image`, `shader`, `target`).
- **Current eyesy repo**: no GIF/animation/texture-array precedent exists today (grep across
  `modes/`, `engine/`, `docs/` finds no gif/animated/sprite/texture-array code; `images` are
  static `ofImage`s only — `runtime.h:43`, `runtime.cpp:609-622`). The nearest *temporal*
  precedent is the audio-compiled WAV input path (`audio.cpp`), which pre-processes content
  off-stage and replays it smoothly — the same spirit as §1.

The audio echo is telling: the platform already prefers **pre-baking content** (`--audio-wav`,
`local/overnight` fixtures, replay `.json` fixtures in `tests/`) over runtime codec work. GIF
frames are the visual analogue: bake the sequence, replay it.

---

## 6. Effort / risk summary

| Option | Effort | CPU on device | GPU cost | Memory | Integration point | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| **1. PNG frames + `image()`/`draw_image()`** *(recommended)* | S (build-time `tools/` script only; no engine change) | ~0/frame after load | ~1–2 ms blit | n×frames, ≤32×cap | `eyesyctl`/`tools/`; `runtime.cpp:612` cap | setup stall (mitigate: cap/downscale) |
| **2a. §1 + FBO-feedback bridge** *(no C++ change)* | S–M | ~0 | +1 pass | +1–2 targets (≤8) | `runtime.cpp:571-606` targets | composite-law discipline |
| **2b. Sprite-atlas / texture-array primitive** *(C++ addition)* | M | ~0 | ~1 pass | 1 texture | `runtime.cpp` near `IMAGE_NEW` | ES2 lacks arrays → offset-sheet emulation |
| **3. Lua decode** | L + engine blocker | ❌ (blocked: no pixel upload) | — | — | n/a | infeasible today |
| **4. mp4/webm on-device decode** | XL (engine GStreamer/thread/player) | high (soft H.264) | blit | 1–2 ring | new `video` binding | decode latency, 720p60 CPU |

**Recommended sequence:** land §1 as a single GIF mode (or a `gif` mode-template), driven by a
`tools/gif_to_frames.sh` asset step; add FBO-feedback (§2a) only where art demands; treat
sprite-atlas (§2b) as a later consolidation; do not pursue §3 or §4 for GIF-sized content.

---

## Sources

Repo-grounded (paths under the repo root):

- `docs/API.md` — Lua surface (image/draw_image/target/shader; no texture upload).
- `engine/src/runtime.cpp:119-122` (asset), `230-236` (capabilities), `571-606` (FBO/targets),
  `609-622` (IMAGE_NEW/IMAGE_DRAW + 32-image cap), `677-681` (shader sampler = targets only).
- `engine/src/runtime.h:43` (`images` are `ofImage`).
- `engine/src/kms_window.cpp:91-116,253-264` (KMS/EGL ES2, 720p60 mode pick).
- `engine/src/main.cpp:270-273` (screenshot readback; the only texture readback).
- `engine/src/audio.cpp` (WAV replay thread — structural precedent for §4).
- `eyesyctl` (`package()`: modes deep-copied, symlinks rejected; `deploy()`: immutable release).
- `tools/provision_device.sh` (read-only root remount dance; GStreamer/mpg123 as passive deps).
- `docs/DEPLOYMENT.md`, `docs/SCENE-LIBRARY.md` (tier budget, composite design law),
  `docs/CREATIVE.md`, `ROADMAP.md` (read-only `/tmp` tmpfs, VC4 V3D 2.1, 60 fps),
  `docs/03-of-lua-engine.md` (old OF `VIDEO` precedent).
