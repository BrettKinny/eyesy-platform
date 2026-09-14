#!/usr/bin/env python3
"""Capture the live X framebuffer to /tmp/xshot.ppm for remote inspection.

Usage on the device (needs python-xlib on PYTHONPATH, e.g. a wheel extracted
to /tmp/xlib-vendor; /tmp is tmpfs so re-stage after every reboot):

    DISPLAY=:1 PYTHONPATH=/tmp/xlib-vendor python3 xshot.py

Prints size, per-channel means, sampled non-black ratio, and channel maxima,
then writes a P6 PPM of the root window. Used 2026-09-13 to prove the engine
was rendering into X's framebuffer while the HDMI capture chain showed black.
"""
import array
from Xlib import X, display

d = display.Display(':1')
root = d.screen().root
geo = root.get_geometry()
w, h = geo.width, geo.height
img = root.get_image(0, 0, w, h, X.ZPixmap, 0xffffffff)
data = img.data
if not isinstance(data, (bytes, bytearray)):
    data = bytes(data)
assert len(data) == w * h * 4, (len(data), w, h)

a = array.array('B', data)
# XR24 little-endian memory order: B, G, R, X
b = a[0::4]
g = a[1::4]
r = a[2::4]
rgb = array.array('B', bytes(w * h * 3))
rgb[0::3] = r
rgb[1::3] = g
rgb[2::3] = b

with open('/tmp/xshot.ppm', 'wb') as f:
    f.write(b'P6\n%d %d\n255\n' % (w, h))
    f.write(rgb.tobytes())

n = w * h
print('size', w, h)
print('mean_r %.2f mean_g %.2f mean_b %.2f' % (sum(r) / n, sum(g) / n, sum(b) / n))
print('nonblack_ratio %.4f' % (sum(1 for i in range(0, len(a), 4 * 61) if a[i] or a[i + 1] or a[i + 2]) / (len(a) / (4 * 61))))
print('max_r %d max_g %d max_b %d' % (max(r), max(g), max(b)))
