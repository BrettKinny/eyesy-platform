#!/usr/bin/env python3
"""Create a RandR mode with explicit CEA sync flags and switch HDMI-1 to it.

The stock EDID-derived RandR modes reach the kernel with empty names and zero
sync flags (see /sys/kernel/debug/dri/0/state), which sync-strict HDMI sinks
refuse to lock. This script builds the same 720p60 CEA timing with explicit
PHSYNC|PVSYNC (0x5) flags via RRCreateMode, adds it to HDMI-1, and reconfigures
the HDMI CRTC at that mode. Usage on the device:

    DISPLAY=:1 PYTHONPATH=/tmp/xlib-vendor python3 rr_flags.py [--revert ID]
"""
import sys
from Xlib import X, display
import Xlib.ext.randr as rr_ext
from Xlib.ext.randr import RandR_ModeInfo

MODE_NAME = b'720pCEA'
PHSYNC, PVSYNC = 0x1, 0x4
FIELDS = dict(id=0, width=1280, height=720, dot_clock=74250000,
              h_sync_start=1390, h_sync_end=1430, h_total=1650, h_skew=0,
              v_sync_start=725, v_sync_end=730, v_total=750,
              name_length=len(MODE_NAME), flags=PHSYNC | PVSYNC)


def as_int(v):
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def fetch(d, root):
    res = root.xrandr_get_screen_resources()  # forces server re-probe
    ct = as_int(res.config_timestamp)
    outputs = {}
    for oid in res.outputs:
        oi = d.xrandr_get_output_info(oid, ct)
        if as_int(oi.status) != 0:
            continue
        nm = oi.name.decode() if isinstance(oi.name, bytes) else oi.name
        outputs[nm] = (as_int(oid), oi)
    return res, ct, outputs


def main():
    revert = None
    for a in sys.argv[1:]:
        if a.startswith('--revert='):
            revert = int(a.split('=', 1)[1], 0)

    d = display.Display(':1')
    root = d.screen().root

    if revert:
        # Remove the test mode again (mode must be unused).
        res, ct, outputs = fetch(d, root)
        try:
            d.xrandr_delete_output_mode(outputs['HDMI-1'][0], revert)
            d.xrandr_destroy_mode(revert)
            print('reverted mode 0x%x' % revert)
        except Exception as e:
            print('revert failed: %s' % e)
        return

    blob = RandR_ModeInfo.to_binary(**FIELDS)
    print('modeinfo packed: %d bytes' % len(blob))

    res, ct, outputs = fetch(d, root)
    hdmi_id, oi = outputs['HDMI-1']
    crtc = as_int(oi.crtc)
    print('HDMI-1 output 0x%x currently on crtc 0x%x' % (hdmi_id, crtc))
    if not crtc:
        print('FATAL: HDMI-1 has no CRTC; run rr_hdmi.py --apply first', file=sys.stderr)
        sys.exit(2)

    r = root.xrandr_create_mode(FIELDS, MODE_NAME)
    new_id = as_int(r.mode)
    print('created mode 0x%x ("%s") flags=0x%x' % (new_id, MODE_NAME.decode(), PHSYNC | PVSYNC))
    d.xrandr_add_output_mode(hdmi_id, new_id)
    print('added to HDMI-1')

    # add_output_mode bumps the config timestamp; refetch before reconfiguring.
    res2, ct2, outputs2 = fetch(d, root)
    hdmi_id2 = as_int(outputs2['HDMI-1'][0])
    try:
        r2 = d.xrandr_set_crtc_config(crtc, ct2, 0, 0, new_id, rr_ext.Rotate_0, [hdmi_id2])
        print('set_crtc_config status=%s (0 = success)' % as_int(r2.status))
    except Exception as e:
        print('set_crtc_config failed: %s' % e)
        sys.exit(3)
    print('HDMI-1 now on explicit-flag mode 0x%x' % new_id)
    print('revert with: rr_flags.py --revert=0x%x' % new_id)


if __name__ == '__main__':
    main()