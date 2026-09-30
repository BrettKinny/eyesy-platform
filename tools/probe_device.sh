#!/bin/bash
# Bounded first-hardware probe; always restore stock video afterward.
# LEGACY: this probe runs the engine under Xorg. On the CM3+ any Xorg session
# leaves HDMI blanked until the next power cycle (docs/HDMI-DISPLAY-ISSUE.md).
# Use `eyesyctl headless-test` instead (docs/DEPLOYMENT.md).
set -euo pipefail
[[ $EUID == 0 && $# == 2 ]] || { echo 'Usage: sudo bash probe_device.sh CLONE_ID ENGINE'; exit 2; }
python3 - "$1" <<'PY'
import json, sys
from pathlib import Path
assert json.loads(Path('/etc/eyesy-development-clone').read_text())['clone_id'] == sys.argv[1]
assert 'Compute Module 3 Plus' in Path('/proc/device-tree/model').read_text()
PY
task_engine=$(realpath -- "$2")
[[ -x $task_engine ]]
ldd "$task_engine"
if ldd "$task_engine" | grep -q 'not found'; then exit 1; fi
task_probe=/sdcard/eyesy-platform/probe
install -d -o music -g music "$task_probe"
restore_stock() { systemctl start eyesypy.service; }
trap restore_stock EXIT
systemctl stop eyesypy.service
timeout --signal=TERM --kill-after=5s 75s runuser -u music -- \
    env XAUTHORITY=/tmp/eyesy-probe.Xauthority \
    xinit "$task_engine" --probe --fullscreen --audio-device auto --osc-port 4000 \
    --frames 600 --storage "$task_probe" --report "$task_probe/report.json" \
    -- :1 vt2 -nolisten tcp -logfile /tmp/eyesy-probe-Xorg.log
