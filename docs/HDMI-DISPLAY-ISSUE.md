# HDMI black-screen investigation

Status: **root cause identified at register level (2026-09-14)**. Xorg display
sessions put the BCM2837 HDMI transmitter into a state the vc4 driver never
undoes; every sink sees sync with blanked pixels until the next power cycle.
Stock SDL/KMSDRM and the firmware splash are unaffected. Boot ownership is
currently stock for a safe power-on; the platform display path is blocked
pending the fix below.

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
   holds engine content (xshot: non-black ratio 1.0).
3. Xorg stopped, stock restarted on the same boot: `VID_CTL` **stays
   `0xc2000000`**, output still dead. This is yesterday's "persists until
   reboot" — it is a latched hardware bit, not a wedge the next client can
   clear.
4. Power cycle → stock-first boot → visible again.

Implementation status (2026-09-15): Option A is implemented and passed
validation V1 on hardware. `engine/src/kms_window.{h,cpp}` (engine flag
`--kms`) drives direct GBM/EGL scanout with kernel-EDID modes only
(`KMS: connector HDMI-A mode "1280x720" 1280x720@60 clock 74250 flags 0x5
type 0x40`); `deploy/eyesy-platform.service` runs the engine with `--kms`,
no Xorg. V1 evidence (one boot, no power cycle between steps): stock
visible → stop stock → engine live on VC4 V3D 2.1 at ~60.4 fps with its OSD
readable through the capture dongle ("EYESY | starter | 59.7 fps") → kill
engine → stock visible again; `HDMI_VID_CTL` bit 25 never set across 788
oracle samples (`tools/vidctl_watch.sh`, zero `0xc2000000`), log at
`evidence/reports/vidctl-kms-test.txt`, frames in
`evidence/reports/hdmi-dongle-stream/`. V2 (platform-owned cold boot via the
deployed service) remains: package, deploy, flip boot ownership, one power
cycle.

V2 passed the same night: boot ownership flipped to the platform and the
device cold-booted into `dev-cf8b1ee8013f` — firmware splash visible, then
the engine continuously (frames archived as `v2_*` in
`evidence/reports/hdmi-dongle-stream/`), `VID_CTL=0xc0000000`, 60.4 fps on
`VC4 V3D 2.1`, no Xorg process. The black-screen bug is closed for the
platform path; remaining HDMI-gate work is physical controls, mode
switching, and latency on the deployed service.

Exactly one trigger boundary is known: any Xorg session on the card trips the
latch (observed with glamor and with `AccelMethod none`/llvmpipe, 720p and
1080p, boot-time and RandR-time commits); stock SDL as first client, kernel
fbcon before X, and the firmware splash do not. What *inside* Xorg trips it is
not yet bisected (see next-session protocol). `HDMI_TX_PHY_CTL_0`
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
degenerate blob is what latches bit 25 is the first experiment of the next
session (D1 step 3 below).

## Secondary Xorg defects found along the way

- **Composite EINVAL at initial config**: with both HDMI and Composite
  connected, Xorg computes Composite-1 at 720x576i (PAL) while the cmdline
  forces `vc4.tv_norm=NTSC`; the combined commit fails with
  `(EE) modeset(0): failed to set mode: Invalid argument` and X silently
  keeps the screen on composite at 480i. With HDMI-only (composite reported
  disconnected at probe) initial config takes HDMI cleanly at 1280x720.
- **Leftover `10-eyesy-720p.conf`**: the 2026-09-13 wrap-up recorded this file
  as removed; the removal silently failed on the read-only root and the file
  (mtime Sep 13 07:43) forced `AccelMethod none` → llvmpipe (14–20 fps at
  720p instead of VC4 V3D hardware GL). It is a confounder for every Xorg
  experiment and must be neutralized (config isolation) or actually removed
  before the bisect.
- RandR quirks: only one CRTC exposes possible outputs (0x41), so lighting
  HDMI requires reusing that CRTC; `GetScreenResources` (non-current) is the
  only client path that forces a server re-probe after hotplug.

## Observer chain qualification (this was half the battle)

- The HDMI→USB dongle's **HPD line is coupled to its USB state**: it asserts
  HPD only while its UVC pipeline streams. With no client, USB autosuspend
  (2 s idle on the workstation) drops HPD, the kernel loses the EDID, and
  display clients fall back to composite. Every capture window must keep a
  streamer open; `power/control=on` on the dongle's USB device is the
  durable fix (needs sudo on the workstation).
- Dongle output decoded: uniform `(0,0,0)` = no TMDS; uniform `(7,7,7)` =
  sync present but pixels blanked (the latched state); real content means
  lock. Yesterday's "dongle only locks around power-on" was this signature
  misread.
- HPD/EDID flapping explains the morning's boot behavior: X probed during an
  HPD-down window, saw HDMI disconnected with no modes, and put the screen on
  composite — a black HDMI screen with no latch required. The user's "boots
  into black screen" is a **stack of two causes**: composite fallback from
  HPD-down probes at boot *and* the VID_CTL latch whenever X does take HDMI.
- Frame indices from the 1 fps PNG stream are not wall-clock aligned (the
  fps filter emits bursts); archive evidence by pixel-content scan, not index.

## Remediation plan (curated from the slow-model consult)

Decision sequence:

1. **Interim (now, done)**: boot ownership = stock; platform display ships
   nowhere until fixed. Device currently boots into working stock.
2. **Product fix — Option A**: remove Xorg from the scanout path; give the
   engine a direct KMS/GBM (+EGL on V3D) scanout backend. The stock SDL path
   proves direct KMS is safe on this hardware, and a userspace-only fix
   deploys through the existing transactional release tooling. A
   SDL2-KMSDRM-based presenter is an acceptable faster variant.
3. **Option C (opportunistic, after bisect)**: find/fix what inside Xorg
   trips the latch (degenerate blobs are the prime suspect). Upstreamable,
   but Xorg keeps several other hazards here (composite mode choice, HPD
   fallback, llvmpipe) and scope is unknown.
4. **Option B (rescue only)**: kernel patch clearing/forcing VID_CTL on
   enable. Requires kernel build/deploy the appliance doesn't have, and
   writing an undocumented bit needs proof it's safe and clearable first.

### Next-session protocol

Preconditions for every experiment: dongle streamer running continuously
(HPD), HDMI-only, non-black moving test pattern, VID_CTL logged at 5–20 Hz
(register read is the latch oracle, not the PNG stream), X configs hashed.

**D1 — one cold power cycle, stop at first latch** (stock-first boot):

| Step | Action | Latch means |
|---|---|---|
| 0 | Cold boot into stock, 60 s | bench not ready — abort |
| 1 | Stop stock cleanly | stock teardown trips it |
| 2 | Direct-KMS client, known-good 720p60 (needs a small cross-compiled libdrm test client; modetest/kmscube are not installed on the ro device) | direct KMS handoff unsafe — Option A at risk |
| 3 | Same mode/blob but Xorg-style: empty name, flags=0 | degenerate blob is causal (root cause nailed; Option A must never emit such blobs) |
| 4 | Bare Xorg (no engine/WM/GL client, clean config) 60 s | Xorg's initial commit trips it → go D2 |
| 5 | RandR modesets on/off/auto while Xorg healthy | RandR commit path trips it |
| 6 | Full-screen continuous-updating X client, no GL | scanout traffic/underflow trips it |
| 7 | Current engine under Xorg | full stack required |
| 8 | Restore 10-eyesy-720p.conf and repeat | leftover config was required to reproduce |

**D2** (only if step 4 latched): replay Xorg's captured KMS state one variable
at a time via the direct-KMS tool (mode blob → fb format/modifier → plane
geometry → CRTC props → connector props → cursor), strace/ftrace Xorg during
D1 to capture its exact commits.

**V1/V2 — Option A validation**: V1 = same-boot stock→platform→stock handoff
×3, VID_CTL good throughout, 10 min representative load, V3D (not llvmpipe);
V2 = platform-owned cold boot visible through the same chain, fallback
induced and stock visible after recovery. Power-cycle budget: 3–4 total.

### Open measurements before/while fixing

- **Warm reboot vs power cycle**: does `systemctl reboot` clear the latch?
  Health-gate/fallback design depends on it (device policy: user power-cycles).
- **Register-write recovery**: with the latch set, writing VID_CTL back to
  `0xc0080000` (debugfs is read-only; would need /dev/mem or a kernel patch)
  — determines if a userspace watchdog could un-wedge. Bench-only, risky.
- Bare-Xorg clean repro with the conf neutralized (isolates the llvmpipe/
  AccelMethod confound from "any Xorg trips it").
- Whether stock's `flags=0x40` blob vs the EDID-declared `0x5` matters
  (EDID DTDs declare positive/positive sync for 720p60/1080p60; the dongle
  accepts 0x40 fine — don't chase flags beyond the blob-causality test).

## Bench infrastructure (2026-09-14)

- Workstation: `ffmpeg -f v4l2 … -vf fps=1 /tmp/dongle/live/f%06d.png` hub
  process ("dongle-live") must run for the whole observation window; two UVC
  clients on the dongle collide fatally (one streamer at a time).
- Analysis: per-frame mean/max pixel stats; content = mean > 10 with structure;
  bursts located by content scan. Evidence archive: `evidence/reports/` (EDID
  `dongle-edid.bin`, register dumps `vc4-hdmi-regs-*.txt`, KMS snapshots,
  `hdmi-dongle-stream/`).
- Device tools (wiped by each boot, restage from repo): `tools/rr_hdmi.py`
  (RandR inspect/apply, mode override, CRTC fallback), `tools/rr_flags.py`
  (explicit-flag mode creation/revert), `tools/xshot.py` (X framebuffer
  truth), python-xlib wheel at `/tmp/xlib-vendor`.
- Device facts: `sudo -n` works; `/` is ro (remount-rw dance needed for
  `systemctl enable/disable`); device clock drifts ~2 days at boot (trust
  `uptime -s` after sync, not journal timestamps); `systemctl restart` on the
  platform races vt2/DRM master (stop, wait for Xorg exit, start).

## Historical: 2026-09-13 session summary

First live activation passed machine-side health (advancing frames, VC4
renderer, audio capture) but no image reached the display through the capture
chain; DPMS and `eyesyhw` `Requires=` defects were found and fixed
(`-s -dpms` server flags, `Wants=`). All of yesterday's "black" observations
are now explained by the latched VID_CTL bit plus the unqualified observer
chain (HPD flapping); yesterday's "stock visible only from clean boots"
reading was the latch being absent on stock-first boots.