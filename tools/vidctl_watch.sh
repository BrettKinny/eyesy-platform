#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause
# Logs the vc4 HDMI_VID_CTL register ~10 Hz with timestamps, to a local file.
# The latch oracle for HDMI display work: 0xc0080000 = healthy scanout,
# 0xc2000000 (bit 25) = sync-with-blanked-pixels, persists until power cycle.
# See docs/HDMI-DISPLAY-ISSUE.md.
#
# Usage: tools/vidctl_watch.sh HOST > local/reports/vidctl-<label>.txt
# Stop with Ctrl-C. Runs a device-side loop over one ssh connection.

set -euo pipefail
HOST="${1:?usage: tools/vidctl_watch.sh HOST}"
cd "$(dirname "$0")/.."
exec ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile=local/eyesy_known_hosts "music@${HOST}" \
    'while true; do
         printf "%s %s\n" "$(date +%s.%N)" \
             "$(sudo -n grep VID_CTL /sys/kernel/debug/dri/0/hdmi_regs | grep -o "0x[0-9a-f]*")";
         sleep 0.1;
     done'