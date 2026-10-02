# HDMI black-screen investigation

Status: **root cause identified at register level (2026-09-14) and fixed
(2026-09-15).** Xorg display sessions put the BCM2837 HDMI transmitter into a
state the vc4 driver never undoes; every sink sees sync with blanked pixels
until the next power cycle. Stock SDL/KMSDRM and the firmware splash are
unaffected. The platform now draws through its own direct KMS backend with no
Xorg anywhere in the display path, and boots into a working platform. This page
is the record of the investigation; the Xorg-era device tools it mentions have
since been removed from the repo.

## Root cause (measured)

`HDMI_VID_CTL` (vc4 debugfs `hdmi_regs`) is the discriminator, confirmed across
two boots, three display clients (stock SDL, Xorg, kernel fbcon), and two
modes (720p60, 1080p60):

- `0xc0080000` = ENABLE|UNDERFLOW_ENABLE|CLRRGB (BIT 23) — output visible.
- `0xc2000000` = BIT 25 set, CLRRGB lost — TMDS sync alive, pixels blanked.

BIT 25 is **not defined anywhere in the downstream kernel** `vc4_regs.h`
(defined VID_CTL bits: 31, 30, 29, 28, 27, 24, 23, 18, 16). The driver only
read-modify-writes this register (enable path ORs ENABLE/CLRRGB/
UNDERFLOW_ENABLE/FRAME_COUNTER_RESET/BLANK_INSERT_EN; disable path ORs CLRRGB
then clears ENABLE), so once bit 25 latches, every later modeset preserves it.
Only the firmware re-init at power-on restores `0xc0080000`.

Same-boot sequence on 2026-09-14, all through the same capture chain:

1. Stock boots first: `VID_CTL=0xc0080000`, stock's moving pattern visible.
2. Platform (Xorg) starts: `VID_CTL=0xc2000000`, output dead though the CRTC
   reports `enable=1 active=1` at exact CEA timings and the X framebuffer
   holds engine content (read back with an X framebuffer capture tool, since
   removed: non-black ratio 1.0).
3. Xorg stopped, stock restarted on the same boot: `VID_CTL` **stays
   `0xc2000000`**, output still dead. This explains the 2026-09-13 observation
   that the fault "persists until reboot": it is a latched hardware bit, not a
   wedge the next client can clear.
4. Power cycle → stock-first boot → visible again.

Exactly one trigger boundary is known: any Xorg session on the card trips the
latch (observed with glamor and with `AccelMethod none`/llvmpipe, 720p and
1080p, boot-time and RandR-time commits); stock SDL as first client, kernel
fbcon before X, and the firmware splash do not. What *inside* Xorg trips it was
never bisected (see [Open questions](#open-questions)). `HDMI_TX_PHY_CTL_0`
(0x8c→0x8e) and one `RAM_PACKET` slot also flip under X but **recover** when
stock re-modesets — symptoms, not the kill.

### Strongly correlated, causality unproven

Xorg's committed KMS modes on this system are degenerate: every blob reaches
the kernel with an **empty mode name and `flags=0x0`** (per
`/sys/kernel/debug/dri/0/state`; DRM_MODE_FMT is name, vrefresh, clock,
h…, v…, flags, type). Even a mode created via RRCreateMode with explicit
`flags=0x5` and a name arrives flag-less. Stock's working 720p60 blob is
named `"1280x720"` with `flags=0x40`, and the dongle locks to it — treat the
**stock blob as the oracle**, not the CEA spec value 0x5. Whether the
degenerate blob is what latches bit 25 would be the first experiment of a
bisect (D1 step 3 below). The platform sidesteps the question by never
constructing a mode blob.

## The fix: direct KMS scanout

`engine/src/kms_window.{h,cpp}` (engine flag `--kms`) drives direct GBM/EGL
scanout with kernel-EDID modes only (`KMS: connector HDMI-A mode "1280x720"
1280x720@60 clock 74250 flags 0x5 type 0x40`), and
`deploy/eyesy-platform.service` runs the engine with `--kms` and no Xorg. See
[display backends](DISPLAY-BACKENDS.md).

Validated on hardware on 2026-09-15:

- **V1** (one boot, no power cycle between steps): stock visible → stop stock →
  engine live on `VC4 V3D 2.1` at ~60.4 fps with its OSD readable through the
  capture dongle ("EYESY | starter | 59.7 fps") → stop engine → stock visible
  again. `HDMI_VID_CTL` bit 25 never set across 788 oracle samples
  (`tools/vidctl_watch.sh`, zero `0xc2000000`). This was also the first
  hardware-GL run: the Xorg path had been stuck on llvmpipe at 14–20 fps.
- **V2** (deployed service, platform-owned cold boot): the device cold-booted
  into the platform release — firmware splash visible, then continuous engine
  output, `VID_CTL=0xc0000000`, 60.4 fps on `VC4 V3D 2.1`, no Xorg process.

## Secondary Xorg defects found along the way

- **Composite EINVAL at initial config**: with both HDMI and Composite
  connected, Xorg computes Composite-1 at 720x576i (PAL) while the cmdline
  forces `vc4.tv_norm=NTSC`; the combined commit fails with
  `(EE) modeset(0): failed to set mode: Invalid argument` and X silently
  keeps the screen on composite at 480i. With HDMI-only (composite reported
  disconnected at probe) initial config takes HDMI cleanly at 1280x720.
- **Leftover `10-eyesy-720p.conf`**: a removal recorded on 2026-09-13 had
  silently failed on the read-only root, and the file forced
  `AccelMethod none` → llvmpipe (14–20 fps at 720p instead of VC4 V3D hardware
  GL). It confounded every Xorg experiment. The provisioner now removes it and
  verifies the removal.
- RandR quirks: only one CRTC exposes possible outputs (0x41), so lighting
  HDMI requires reusing that CRTC; `GetScreenResources` (non-current) is the
  only client path that forces a server re-probe after hotplug.

## Observer chain qualification

Half of the investigation was qualifying the capture chain itself:

- The HDMI→USB dongle's **HPD line is coupled to its USB state**: it asserts
  HPD only while its UVC pipeline streams. With no client, USB autosuspend
  (2 s idle on the workstation) drops HPD, the kernel loses the EDID, and
  display clients fall back to composite. Every capture window must keep a
  streamer open; `power/control=on` on the dongle's USB device is the
  durable fix (needs root on the workstation).
- Dongle output decoded: uniform `(0,0,0)` = no TMDS; uniform `(7,7,7)` =
  sync present but pixels blanked (the latched state); real content means
  lock. An earlier reading that "the dongle only locks around power-on" was
  this signature misread.
- HPD/EDID flapping explains the early boot behaviour: X probed during an
  HPD-down window, saw HDMI disconnected with no modes, and put the screen on
  composite — a black HDMI screen with no latch required. The reported symptom,
  "boots into a black screen", was a **stack of two causes**: composite
  fallback from HPD-down probes at boot *and* the VID_CTL latch whenever X did
  take HDMI.
- Frame indices from the 1 fps PNG stream are not wall-clock aligned (the
  fps filter emits bursts); locate evidence by pixel content, not index.

## Remediation options considered

1. **Interim** (2026-09-14, superseded): boot ownership returned to stock so
   the instrument powered on into a working display while the fix was built.
2. **Option A — chosen and shipped**: remove Xorg from the scanout path and
   give the engine a direct KMS/GBM (+EGL on V3D) scanout backend. The stock
   SDL path proved direct KMS safe on this hardware, and a userspace-only fix
   deploys through the existing transactional release tooling.
3. **Option C** (not pursued): find and fix what inside Xorg trips the latch
   (degenerate blobs are the prime suspect). Upstreamable, but Xorg keeps
   several other hazards here (composite mode choice, HPD fallback, llvmpipe)
   and the scope is unknown.
4. **Option B** (rescue only, not pursued): a kernel patch clearing or
   forcing VID_CTL on enable. It needs a kernel build and deploy the appliance
   doesn't have, and writing an undocumented bit needs proof it's safe and
   clearable first.

## Open questions

None of these block the platform. They matter only for an upstreamable fix to
Xorg or the vc4 driver.

### What inside Xorg trips the latch

A bisect protocol, never run. Preconditions for every experiment: dongle
streamer running continuously (HPD), HDMI-only, non-black moving test pattern,
VID_CTL logged at 5–20 Hz (the register read is the latch oracle, not the PNG
stream), X configs hashed.

**D1 — one cold power cycle, stop at first latch** (stock-first boot):

| Step | Action | Latch means |
|---|---|---|
| 0 | Cold boot into stock, 60 s | bench not ready — abort |
| 1 | Stop stock cleanly | stock teardown trips it |
| 2 | Direct-KMS client, known-good 720p60 | direct KMS handoff unsafe (V1 has since shown it is safe) |
| 3 | Same mode/blob but Xorg-style: empty name, flags=0 | degenerate blob is causal |
| 4 | Bare Xorg (no engine/WM/GL client, clean config) 60 s | Xorg's initial commit trips it → go D2 |
| 5 | RandR modesets on/off/auto while Xorg healthy | RandR commit path trips it |
| 6 | Full-screen continuous-updating X client, no GL | scanout traffic/underflow trips it |
| 7 | The engine under Xorg | full stack required |
| 8 | Restore 10-eyesy-720p.conf and repeat | leftover config was required to reproduce |

**D2** (only if step 4 latched): replay Xorg's captured KMS state one variable
at a time via a direct-KMS test client (mode blob → fb format/modifier → plane
geometry → CRTC props → connector props → cursor), and strace/ftrace Xorg
during D1 to capture its exact commits.

### Unmeasured

- **Warm reboot vs power cycle**: does `systemctl reboot` clear the latch?
  (The device is power-cycled by hand, so this was never needed.)
- **Register-write recovery**: with the latch set, does writing VID_CTL back
  to `0xc0080000` restore output? debugfs is read-only, so this needs
  `/dev/mem` or a kernel patch. Bench-only, and risky.
- Whether stock's `flags=0x40` blob vs the EDID-declared `0x5` matters
  (EDID DTDs declare positive/positive sync for 720p60/1080p60; the dongle
  accepts 0x40 fine).

## Bench method (2026-09-14)

- Workstation: one `ffmpeg -f v4l2 … -vf fps=1` process wrote the dongle stream
  to PNGs for the whole observation window; two UVC clients on the dongle
  collide fatally (one streamer at a time).
- Analysis: per-frame mean/max pixel stats; content = mean > 10 with
  structure; bursts located by content scan. The archive (the dongle's EDID,
  register dumps, KMS snapshots, the dongle stream) is kept privately.
- Device tools at the time (since removed from the repo): a RandR
  inspect/apply helper with mode override and CRTC fallback, an explicit-flag
  mode creator, and the X framebuffer capture tool, all run from `/tmp` with a
  vendored python-xlib.
- Device facts: `/` is read-only (remount read-write for
  `systemctl enable/disable`); the device clock drifts about two days at boot
  until it syncs (trust `uptime -s` after sync, not journal timestamps);
  `systemctl restart` on the Xorg-era platform raced vt2/DRM master (stop,
  wait for Xorg to exit, then start).

## Historical: the 2026-09-13 first activation

The first live activation passed machine-side health (advancing frames, VC4
renderer, audio capture) but no image reached the display through the capture
chain. Two service defects were found and fixed along the way: X's default
DPMS blanking (`-s -dpms` server flags) and an `eyesyhw` `Requires=` that tore
the service down on a boot race (`Wants=`). Every "black" observation from that
day is explained by the latched VID_CTL bit plus the then-unqualified observer
chain (HPD flapping); the reading that stock was "visible only from clean
boots" was the latch being absent on stock-first boots.
