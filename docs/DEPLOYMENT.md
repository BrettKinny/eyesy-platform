# Development clone and deployment

ARM releases carry the matching Debian build's `libstdc++.so.6` and
`libgcc_s.so.1` privately under `libs/`. The binary uses
`$ORIGIN/libs:$ORIGIN`, not the launch directory, to find bundled libraries.
This resolves a reproduced stock/build C++ runtime incompatibility without
replacing Raspbian system libraries. `build --arm` extracts the matching pair
from its container; package creation requires their build-provenance hashes.
SDK patches, source hashes, package inventory, and container identity are also
recorded. GPU/audio libraries still come from the device's provisioned OS.

No device was modified during initial desktop development. The original device was
identified through read-only editor requests at <device-ip> as a CM3+, EYESY v3.0,
Raspbian Bookworm, with `vc4-kms-v3d,composite` and `wm8731-spi` overlays.

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

This installs Xorg/runtime packages, saves package and Xwrapper configuration
records, installs disabled platform services, and attempts to restore the prior
root mount mode. It does not stop stock video. The first spare-card provision
completed, but immediate read-only remount failed after apt; a controlled reboot
restored `ro,noatime`. Treat this cleanup limitation as unresolved, not a successful
read-only restoration. Stock boot and disabled platform services were verified.

The current provisioner refuses active/enabled platform services, symlinked write
destinations, and existing provision backups. A repeated invocation will not
overwrite the first inventory, including after an interrupted attempt. Review the
saved state before planning a repair; do not delete backups just to bypass this
guard. These newer checks are locally tested, not a second live apt qualification.

Before full activation, run `eyesy-armhf --probe --fullscreen --audio-device auto`
in the new X session after stopping stock Python. Confirm GLES renderer identity,
720p60 output, codec capture, and clean return to stock. This is a physical gate;
emulated rendering does not satisfy it.

After that gate:

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
Use `--target stock` for stock recovery (also the default target). These commands
do not alter boot selection. The CLI invokes the guarded release helper over SSH
and reports failed service starts. A missing or tampered `previous.json` is a hard
error when selecting the previous release. Boot selection
remains stock until separately validated and enabled.

The stock web editor still controls `eyesypy`, not the Lua platform. Its start/stop
buttons should not be used during a platform test. Service conflicts enforce
exclusive ownership. Mode development uses local editing and SSH deployment.

## Hardware acceptance still required

- Minimal GPU/audio probe and confirmed 720p60 output.
- Physical knob/button, scene, screenshot, and error-recovery checks.
- 60-minute reference-mode soak and 500-switch memory-growth measurement.
- Interrupted transfer, failed activation, process hang, restart, and rollback tests.
- Real audio, physical MIDI, and captured display latency when equipment is available.

No `hardware_validated` release flag should be set based on desktop/emulated tests.
