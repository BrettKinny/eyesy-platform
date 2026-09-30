# Development clone and deployment

The platform targets a CM3+ EYESY running EYESY OS v3.0 (Raspbian Bookworm, with
the `vc4-kms-v3d,composite` and `wm8731-spi` overlays). To read those details
from your unit without changing anything, run
`./eyesyctl doctor --host DEVICE_IP`. It uses the stock web editor's file-read
API.

ARM releases carry the matching Debian build's `libstdc++.so.6` and
`libgcc_s.so.1` privately under `libs/`. The binary uses
`$ORIGIN/libs:$ORIGIN`, not the launch directory, to find bundled libraries.
This resolves a reproduced stock/build C++ runtime incompatibility without
replacing Raspbian system libraries. `build --arm` extracts the matching pair
from its container; package creation requires their build-provenance hashes.
SDK patches, source hashes, package inventory, and container identity are also
recorded. GPU/audio libraries still come from the device's provisioned OS.

## Prepare the spare card

Keep the original card intact. The selected recovery strategy is a verified clone
of its complete offline disk image. A separately flashed EYESY v3.0 spare can also
preserve the original, but is not a clone of its user data; record that distinction.

Identify source and destination using `lsblk -o NAME,SIZE,MODEL,SERIAL,TRAN,MOUNTPOINTS`.
Never infer the target from `/dev/sdb` or capacity. Unmount source partitions before
imaging; verify the image hash and byte-for-byte written content before using the
spare. This repository deliberately does not auto-select or overwrite block devices.

With the spare's root partition mounted at an explicit path, run:

```sh
sudo python3 tools/prepare_clone.py --root /EXACT/MOUNT/ROOT --public-key /PATH/TO/KEY.pub
```

This checks the filesystem and EYESY installation, installs one public key, enables
SSH, creates host keys when absent, and records `/etc/eyesy-development-clone` with
a UUID. It refuses broad paths and symlinked SSH destinations. Preserve its receipt.
Unmount cleanly, boot the spare, connect it to Wi-Fi, verify stock controls/video,
then verify the SSH host fingerprint before accepting it on the workstation.

## Build and stage

```sh
./eyesyctl bootstrap --arm
./eyesyctl build --arm
./eyesyctl modes sync
./eyesyctl package --arm
python3 tools/release.py dist/dev-<payload-id>-armhf.tar.gz --architecture armhf  # actual name printed by `package`
```

The ARM SDK has a small checked-in patch to select GLES2 explicitly and avoid the
legacy Broadcom header. The stock kernel/overlays stay intact. The build runs under
ARM emulation in a Bookworm container; no compiler is installed on the instrument.

Provision only the prepared spare:

```sh
./eyesyctl provision --host DEVICE_IP --clone-id UUID_FROM_RECEIPT
```

This installs the runtime libraries the engine links against and installs the
platform's systemd units, disabled. It records the package inventory before and
after, and backs up anything it replaces. It then attempts to restore the prior
root mount mode. It does not stop stock video.

The provisioner also still installs the Xorg packages, and writes an
`Xwrapper.config`, from the platform's earlier X-based display path. The current
service never starts X. It draws with direct KMS, because on this board any Xorg
session leaves HDMI blanked until the next power cycle; see
[HDMI display issue](HDMI-DISPLAY-ISSUE.md). The provisioner also removes the
legacy `/etc/X11/xorg.conf.d/10-eyesy-720p.conf` if an earlier run left it.

On the first spare-card provision, the read-only remount failed immediately after
apt, and a controlled reboot restored `ro,noatime`. Treat this cleanup limitation
as unresolved, not a successful read-only restoration. Stock boot and the disabled
platform services were verified.

The current provisioner refuses active/enabled platform services, symlinked write
destinations, and existing provision backups. A repeated invocation will not
overwrite the first inventory, including after an interrupted attempt. Review the
saved state before planning a repair; do not delete backups just to bypass this
guard. These newer checks are locally tested, not a second live apt qualification.

## Check the package on the device

Before activating a release, run it on the device's GPU without touching the
display:

```sh
./eyesyctl headless-test dist/dev-<payload-id>-armhf.tar.gz \
  --host DEVICE_IP --clone-id UUID_FROM_RECEIPT \
  --mode starter --frames 600 --output local/device-test-001
```

This renders offscreen on the real VC4 GPU with synthetic audio while stock keeps
running. It then retrieves the report, the log and screenshots. Confirm that the
renderer is `VC4 V3D 2.1` (never `llvmpipe`), and that the run has no mode
errors. See [headless development](HEADLESS-DEVELOPMENT.md).

Do not use `tools/probe_device.sh`. It is the older first-hardware probe, and it
starts Xorg, which triggers the HDMI blanking described above.

## Activate

Connect the display before you deploy, and keep it connected. If you use an
HDMI capture dongle, keep its stream running. The engine picks its mode from the
display's EDID when it starts. If no display is present, the engine fails its
start check, and the fallback unit hands the instrument back to stock. A start
with the display missing can also leave output degraded until the engine
restarts with the display present.

```sh
./eyesyctl deploy dist/dev-<payload-id>-armhf.tar.gz --host DEVICE_IP --clone-id UUID_FROM_RECEIPT
./eyesyctl status --host DEVICE_IP
./eyesyctl logs --host DEVICE_IP
./eyesyctl rollback --host DEVICE_IP --clone-id UUID_FROM_RECEIPT --target stock
```

Activation checks clone ID, board, archive structure, checksums, architecture, and
shared-library availability before switching services, including the actual ELF
machine/class of `eyesy-engine` (a forged manifest cannot pass). Releases are
immutable; activation stages a new directory and atomically switches a symlink.
The candidate `active.env` is installed before starting its service;
`previous.json` is committed after health is proven. Health
requires advancing frames from the expected release and a GPU renderer. Failed
activation stops the candidate and restores the previous symlink and environment,
or starts stock if there was no prior platform release.

To manually select the last known-good platform release, use
`./eyesyctl rollback --host DEVICE_IP --clone-id UUID_FROM_RECEIPT --target previous`.
Use `--target stock` for stock recovery (also the default target). If you later
deploy the same archive after a rollback to stock, deployment selects the
installed release again, after verifying its checksum. The CLI invokes the
guarded release helper over SSH and reports failed service starts. A missing or
tampered `previous.json` is a hard error when selecting the previous release.

If the engine keeps failing, systemd stops restarting it. `OnFailure` then runs
`eyesy-platform-fallback.service`, which waits briefly for the platform to
recover and otherwise starts stock.

## Boot selection

Deployment and rollback switch the running service; they do not change what
starts at boot. A freshly provisioned card still boots into stock. To make the
platform start at boot, run these commands on the device. The root filesystem is
read-only, so remount it read-write first, then restore it:

```sh
sudo mount -o remount,rw /
sudo systemctl disable eyesypy.service
sudo systemctl enable eyesy-platform.service
sudo mount -o remount,ro /
```

To hand boot back to stock, reverse the two `systemctl` lines. Services conflict,
so only one engine owns the display at a time.

The stock web editor still controls `eyesypy`, not the Lua platform. Don't use
its start/stop buttons while the platform is running. Mode development uses
local editing and SSH deployment.

## Hardware acceptance still required

Deployment, rollback in all four paths, unattended recovery to stock, and
60-minute soaks have been exercised on hardware; see
[implementation status](STATUS.md). What remains needs a person at the bench:

- Physical knob and button feel.
- A known stereo signal on the line input, to check channel separation and
  response.
- HDMI display latency on a real display.
- Cold-boot recovery: one power cycle after a no-display failure.

The [bench checklist](BENCH-CHECKLIST.md) covers these. No `hardware_validated`
release flag should be set based on desktop/emulated tests.
