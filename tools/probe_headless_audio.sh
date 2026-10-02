#!/bin/bash
# Run inside a transient systemd unit with RuntimeMaxSec and stock ExecStopPost.
# Only a fresh, explicitly identified spare is allowed. No boot selection changes.
set -euo pipefail
[[ $EUID == 0 && $# == 3 ]] || { echo 'Usage: sudo bash probe_headless_audio.sh CLONE_ID ENGINE NEW_REPORT_DIRECTORY'; exit 2; }
python3 - "$1" "$2" "$3" <<'PY'
import json, sys
from pathlib import Path
assert json.loads(Path('/etc/eyesy-development-clone').read_text())['clone_id'] == sys.argv[1]
assert 'Compute Module 3 Plus' in Path('/proc/device-tree/model').read_text()
assert Path(sys.argv[2]).is_file()
output = Path(sys.argv[3])
assert output.is_absolute() and output.resolve().is_relative_to(Path('/sdcard/eyesy-platform/experiments'))
assert not output.exists() and not output.is_symlink()
PY
task_engine=$(realpath -- "$2")
[[ -x $task_engine ]]
# The engine needs a mode; use the release's own starter beside the binary.
task_mode=$(dirname -- "$task_engine")/modes/starter
[[ -f $task_mode/main.lua ]] || { echo "No starter mode at $task_mode" >&2; exit 1; }
ldd "$task_engine"
if ldd "$task_engine" | grep -q 'not found'; then exit 1; fi
systemctl is-active --quiet eyesypy.service
install -d -o music -g music -- "$3"
restore_stock() { systemctl start eyesypy.service; }
trap restore_stock EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
systemctl stop eyesypy.service
timeout --signal=TERM --kill-after=5s 60s runuser -u music -- \
    "$task_engine" --offscreen --mode "$task_mode" --audio-device auto --osc-port 4000 \
    --frames 1200 --storage "$3" --report "$3/report.json"
python3 - "$3/report.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
assert report['audio_source'] == 'device', report
assert report['audio_available'] and report['audio_sequence'] > 10, report
assert report['frame'] >= 1200 and not report['error'], report
assert not any(x in report['renderer'].lower() for x in ('llvmpipe', 'softpipe', 'swrast')), report
print(json.dumps(report, indent=2))
PY
