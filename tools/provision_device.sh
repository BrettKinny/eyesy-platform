#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# Install prerequisites ONLY on the identified development clone. Run via sudo.
set -euo pipefail
if [[ $EUID != 0 || $# != 1 ]]; then
    echo 'Usage: sudo bash provision_device.sh CLONE_ID' >&2
    exit 2
fi
python3 - "$1" <<'PY'
import json, sys
from pathlib import Path
marker_path = Path('/etc/eyesy-development-clone')
if marker_path.is_symlink():
    raise SystemExit('Refusing symlinked clone marker')
marker = json.loads(marker_path.read_text())
if marker.get('clone_id') != sys.argv[1]:
    raise SystemExit('Clone identity mismatch')
if 'Compute Module 3 Plus' not in Path('/proc/device-tree/model').read_text():
    raise SystemExit('Wrong board')
if 'bookworm' not in Path('/etc/os-release').read_text():
    raise SystemExit('Wrong OS')
PY

# Do this before making the filesystem writable, updating packages, or replacing
# units.  Provisioning an already-running/enabled platform could interrupt the
# stock engine and would make the final "disabled" claim untrue.
for task_unit in eyesy-platform.service eyesy-platform-fallback.service; do
    if systemctl is-active --quiet "$task_unit"; then
        echo "Refusing provisioning while $task_unit is active" >&2
        exit 1
    fi
    if systemctl is-enabled --quiet "$task_unit"; then
        echo "Refusing provisioning while $task_unit is enabled" >&2
        exit 1
    fi
done

task_base=/sdcard/eyesy-platform
if [[ -L "$task_base" ]]; then
    echo 'Refusing symlinked platform root' >&2
    exit 1
fi
if [[ -e "$task_base" && ! -d "$task_base" ]]; then
    echo 'Refusing non-directory platform root' >&2
    exit 1
fi
task_backup_dir="$task_base/provision-backup"
if [[ -L "$task_backup_dir" ]]; then
    echo 'Refusing symlinked provision backup directory' >&2
    exit 1
fi
mkdir -p "$task_backup_dir"
if [[ -L "$task_backup_dir" ]]; then
    echo 'Refusing symlinked provision backup directory' >&2
    exit 1
fi

# A second run must never overwrite the inventory from an earlier run (including
# an interrupted run).  Leaving it intact makes the original state recoverable.
for task_backup in packages.before packages.after \
    eyesy-platform.service eyesy-platform-fallback.service; do
    if [[ -e "$task_backup_dir/$task_backup" || -L "$task_backup_dir/$task_backup" ]]; then
        echo "Refusing provisioning: existing backup $task_backup" >&2
        exit 1
    fi
done

# Check every privileged write destination before the first backup write or
# package operation.  In particular, never let install()/write_text() follow a
# pre-existing symlink.
for task_unit in eyesy-platform.service eyesy-platform-fallback.service; do
    task_unit_path="/etc/systemd/system/$task_unit"
    if [[ -L "$task_unit_path" ]]; then
        echo "Refusing symlinked unit destination $task_unit_path" >&2
        exit 1
    fi
done
dpkg-query -W > "$task_base/provision-backup/packages.before"
task_mount_options=$(findmnt -n -o OPTIONS /)
task_restore_ro=false
if [[ ,$task_mount_options, == *,ro,* ]]; then
    if ! mount -o remount,rw /; then
        echo 'ERROR: failed to remount root filesystem read-write' >&2
        exit 1
    fi
    task_restore_ro=true
fi
task_xorg_conf="/etc/X11/xorg.conf.d/10-eyesy-720p.conf"
if [[ -e "$task_xorg_conf" ]]; then
    rm -f "$task_xorg_conf" || {
        echo "ERROR: failed to remove $task_xorg_conf" >&2
        exit 1
    }
fi
if [[ -e "$task_xorg_conf" ]]; then
    echo "ERROR: failed to remove $task_xorg_conf" >&2
    exit 1
fi
cleanup() {
    local task_status=$?
    sync
    if $task_restore_ro && ! mount -o remount,ro /; then
        echo 'ERROR: failed to restore the root filesystem read-only; reboot before using the clone' >&2
        [[ $task_status == 0 ]] && task_status=1
    fi
    # An EXIT trap's return value does not replace the shell's original status.
    # Explicitly exit so a failed read-only restoration cannot report success.
    trap - EXIT
    exit "$task_status"
}
trap cleanup EXIT
apt-get update
apt-get install -y --no-install-recommends \
    libglfw3 libglew2.2 libfreeimage3 libfreetype6 libopenal1 libsndfile1 \
    liburiparser1 libpugixml1v5 librtaudio6 libpulse0 libgtk-3-0 \
    libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 libmpg123-0 \
    libluajit-5.1-2 libglut3.12 libxxf86vm1 libcurl4
task_script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
for task_unit in eyesy-platform.service eyesy-platform-fallback.service; do
    task_unit_path="/etc/systemd/system/$task_unit"
    task_unit_backup="$task_backup_dir/$task_unit"
    if [[ -L "$task_unit_path" ]]; then
        echo "Refusing symlinked unit destination $task_unit_path" >&2
        exit 1
    fi
    if [[ -e "$task_unit_path" ]]; then
        cp -a "$task_unit_path" "$task_unit_backup"
    fi
    install -m 644 "$task_script_dir/../deploy/$task_unit" "$task_unit_path"
done
chown music:music "$task_base"
systemctl daemon-reload
dpkg-query -W > "$task_base/provision-backup/packages.after"
echo 'Provisioned clone. Platform service remains disabled; stock engine has not been stopped.'
