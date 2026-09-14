#!/usr/bin/env python3
"""Inspect (and with --apply, reconfigure) RandR outputs of the platform X session.

Read-only mode lists screen size/range, outputs with connection state, crtcs,
and the HDMI-1 mode table. `--apply` moves the single lit output from
Composite-1 onto HDMI-1 at 1280x720@60: grow the RandR screen, light a free
CRTC on HDMI-1, then disable the composite CRTC. Mode 0/None is never forced
onto an output; the composite CRTC is only disabled after HDMI is lit.

Usage on the device (python-xlib staged at /tmp/xlib-vendor after each boot):

    DISPLAY=:1 PYTHONPATH=/tmp/xlib-vendor python3 rr_hdmi.py [--apply]
"""
import sys
from Xlib import X, display
import Xlib.ext.randr as rr

APPLY = '--apply' in sys.argv
TARGET_W, TARGET_H, TARGET_REFRESH = 1280, 720, 60.0
for a in sys.argv[1:]:
    if a.startswith('--mode='):
        spec = a.split('=', 1)[1]
        try:
            res, rate = spec.split('@')
            w, h = res.lower().split('x')
            TARGET_W, TARGET_H = int(w), int(h)
            TARGET_REFRESH = float(rate)
        except Exception:
            print('bad --mode, want WxH@R', file=sys.stderr)
            sys.exit(2)
def as_int(v):
    """Normalize python-xlib id objects (Card32Obj and friends) to int."""
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def refresh(m):
    return m.dot_clock / float(m.h_total * m.v_total)


def fetch(d, root):
    res = root.xrandr_get_screen_resources()  # non-current: forces server re-probe
    ct = as_int(res.config_timestamp)
    blob = getattr(res, 'mode_names', None)
    if blob is None:
        blob = res.names  # GetScreenResourcesCurrent reply field name
    modes = {}
    off = 0
    for m in res.modes:
        nm = blob[off:off + m.name_length]
        try:
            nm = nm.decode()
        except AttributeError:
            pass
        off += m.name_length
        modes[as_int(m.id)] = (nm, m)
    outputs = {}
    for oid in res.outputs:
        oi = d.xrandr_get_output_info(oid, ct)
        if as_int(oi.status) != 0:
            continue
        nm = oi.name
        try:
            nm = nm.decode()
        except AttributeError:
            pass
        outputs[nm] = (as_int(oid), oi)
    return res, ct, modes, outputs


def show(d, root, res, ct, modes, outputs):
    s = d.screen()
    print('screen: %dx%d  config_timestamp=%d' % (s.width_in_pixels, s.height_in_pixels, ct))
    try:
        sr = root.xrandr_get_screen_size_range()
        print('size range: %dx%d .. %dx%d' % (as_int(sr.min_width), as_int(sr.min_height),
                                               as_int(sr.max_width), as_int(sr.max_height)))
    except Exception as e:
        print('size range: unavailable (%s)' % e)
    for name, (oid, oi) in sorted(outputs.items()):
        print('output %-12s id=0x%x connection=%d crtc=0x%x modes=%d preferred=%d'
              % (name, oid, as_int(oi.connection), as_int(oi.crtc), len(list(oi.modes)), as_int(oi.num_preferred)))
    for cid in res.crtcs:
        ci = d.xrandr_get_crtc_info(cid, ct)
        bound = [n for n, (oid, _) in outputs.items() if as_int(oid) in [as_int(o) for o in ci.outputs]]
        print('crtc 0x%-8x x=%-4d y=%-4d %dx%d mode=0x%-8x outputs=%s possible=%d'
              % (as_int(cid), as_int(ci.x), as_int(ci.y), as_int(ci.width), as_int(ci.height),
                 as_int(ci.mode) or 0, bound, len(list(ci.possible_outputs))))


def main():
    d = display.Display(':1')
    root = d.screen().root
    res, ct, modes, outputs = fetch(d, root)
    show(d, root, res, ct, modes, outputs)
    if not APPLY:
        # Print the target mode table for HDMI-1 to confirm the plan.
        hdmi = outputs.get('HDMI-1')
        if hdmi:
            _, oi = hdmi
            print('HDMI-1 mode table:')
            for mid in oi.modes:
                nm, m = modes[as_int(mid)]
                tag = ''
                print('  %-24s %dx%d@%.1f dot=%d htot=%d vtot=%d%s'
                      % (nm, m.width, m.height, refresh(m), m.dot_clock, m.h_total, m.v_total, tag))
        return

    hdmi = outputs.get('HDMI-1')
    if hdmi is None or as_int(hdmi[1].connection) != 0:
        print('FATAL: HDMI-1 not present/connected', file=sys.stderr)
        sys.exit(2)
    hdmi_id, oi = hdmi

    target = None
    for mid in oi.modes:
        nm, m = modes[as_int(mid)]
        if m.width == TARGET_W and m.height == TARGET_H and abs(refresh(m) - TARGET_REFRESH) < 1.5:
            target = (as_int(mid), nm, m)
            break
    if target is None:
        print('FATAL: no %dx%d@%g mode on HDMI-1' % (TARGET_W, TARGET_H, TARGET_REFRESH), file=sys.stderr)
        sys.exit(2)
    t_id, t_name, t_m = target
    print('target mode: %s (0x%x) %dx%d@%.3f' % (t_name, t_id, t_m.width, t_m.height, refresh(t_m)))

    # Composite output: the connected non-HDMI output currently owning a crtc.
    comp_name = comp_id = comp_crtc = comp_cfg = None
    for name, (oid, o2) in outputs.items():
        if name != 'HDMI-1' and as_int(o2.connection) == 0 and as_int(o2.crtc):
            comp_name, comp_id, comp_crtc = name, as_int(oid), as_int(o2.crtc)
            ci = d.xrandr_get_crtc_info(comp_crtc, ct)
            comp_cfg = (as_int(ci.x), as_int(ci.y), as_int(ci.mode),
                        [as_int(o) for o in ci.outputs])
            print('current screen owner: %s (output 0x%x) on crtc 0x%x mode 0x%x'
                  % (comp_name, comp_id, comp_crtc, comp_cfg[2]))
            break

    # Grow the RandR screen first; refetch for the new config timestamp.
    s = d.screen()
    if s.width_in_pixels < TARGET_W or s.height_in_pixels < TARGET_H:
        print('setting screen size to %dx%d' % (TARGET_W, TARGET_H))
        root.xrandr_set_screen_size(TARGET_W, TARGET_H, 338, 190)
        res, ct, modes, outputs = fetch(d, root)
        hdmi_id = as_int(outputs['HDMI-1'][0])

    def reconfig(cid, x, y, mode, outs):
        """Refetch a fresh config_timestamp, then apply one crtc change."""
        res2, ct2, _, _ = fetch(d, root)
        try:
            return d.xrandr_set_crtc_config(cid, ct2, x, y, mode, rr.Rotate_0, outs)
        except Exception as e:
            print('crtc 0x%x request failed: %s' % (cid, e))
            return None

    free = []
    for c in res.crtcs:
        c = as_int(c)
        ci = d.xrandr_get_crtc_info(c, ct)
        if not (as_int(ci.mode) and list(ci.outputs)):
            free.append(c)

    lit = None
    for cid in [c for c in free if c != comp_crtc]:
        r = reconfig(cid, 0, 0, t_id, [hdmi_id])
        if r is not None and as_int(r.status) == 0:
            lit = cid
            print('HDMI-1 lit on crtc 0x%x' % cid)
            break
        print('crtc 0x%x refused: %s' % (cid, as_int(r.status) if r is not None else 'error'))

    if lit is None and comp_crtc is not None:
        # Free crtcs refused (vc4: only the active crtc exposes possible
        # outputs). Disable composite, then reuse its crtc for HDMI-1.
        print('free crtcs refused; disabling composite and reusing crtc 0x%x' % comp_crtc)
        r = reconfig(comp_crtc, 0, 0, 0, [])
        if r is None or as_int(r.status) != 0:
            print('FATAL: could not disable composite crtc 0x%x' % comp_crtc, file=sys.stderr)
            sys.exit(3)
        r = reconfig(comp_crtc, 0, 0, t_id, [hdmi_id])
        if r is not None and as_int(r.status) == 0:
            lit = comp_crtc
            print('HDMI-1 lit on composite crtc 0x%x' % comp_crtc)
        else:
            x, y, m, outs = comp_cfg
            rb = reconfig(comp_crtc, x, y, m, outs)
            restored = rb is not None and as_int(rb.status) == 0
            print('composite restore: %s' % ('ok' if restored else 'FAILED'))
            print('FATAL: HDMI-1 refused on every crtc; composite %s'
                  % ('restored' if restored else 'left DARK'), file=sys.stderr)
            sys.exit(3)

    if lit is None:
        # HDMI-1 may already own a CRTC (e.g. X put it there at initial
        # config). Reconfigure that CRTC in place at the target mode.
        oi2 = outputs.get('HDMI-1')
        h_crtc = as_int(oi2[1].crtc) if oi2 else 0
        if h_crtc:
            print('trying direct reconfigure of HDMI-1 crtc 0x%x' % h_crtc)
            r = reconfig(h_crtc, 0, 0, t_id, [hdmi_id])
            if r is not None and as_int(r.status) == 0:
                lit = h_crtc
                print('HDMI-1 reconfigured in place on crtc 0x%x' % h_crtc)

    if lit is None:
        print('FATAL: no crtc accepted HDMI-1', file=sys.stderr)
        sys.exit(3)

    if comp_crtc is not None and lit != comp_crtc:
        r = reconfig(comp_crtc, 0, 0, 0, [])
        print('composite crtc disabled: status=%s'
              % (as_int(r.status) if r is not None else 'error'))

    res, ct, modes, outputs = fetch(d, root)
    show(d, root, res, ct, modes, outputs)


if __name__ == '__main__':
    main()