#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Pixel-level reduced render-target regression (desktop build container)."""

import subprocess
import tempfile
import struct
import zlib
from pathlib import Path

ROOT = Path("/workspace")
ENGINE = ROOT / "engine/bin/engine"
SHADERS = {
    "gl": """varying vec2 uv; uniform vec2 u_resolution; void main(){ vec2 p=gl_FragCoord.xy/u_resolution; vec3 c=p.x<.5 ? (p.y<.5?vec3(1,0,0):vec3(0,1,0)) : (p.y<.5?vec3(0,0,1):vec3(1,1,0)); gl_FragColor=vec4(c,1.0); }""",
    "uv": """varying vec2 uv; void main(){ vec2 p=uv; vec3 c=p.x<.5 ? (p.y<.5?vec3(1,0,0):vec3(0,1,0)) : (p.y<.5?vec3(0,0,1):vec3(1,1,0)); gl_FragColor=vec4(c,1.0); }""",
}


def pixel(path, x, y):
    d = path.read_bytes()
    pos = 8
    raw = b""
    w = h = 0
    bpp = 4
    while pos < len(d):
        n = struct.unpack(">I", d[pos : pos + 4])[0]
        typ = d[pos + 4 : pos + 8]
        body = d[pos + 8 : pos + 8 + n]
        pos += 12 + n
        if typ == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
            bpp = 3 if body[9] == 2 else 4
        if typ == b"IDAT":
            raw += body
    packed = zlib.decompress(raw)
    stride = w * bpp
    rows = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        f = packed[pos]
        pos += 1
        cur = bytearray(packed[pos : pos + stride])
        pos += stride
        for i in range(stride):
            a = cur[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                cur[i] = (cur[i] + a) & 255
            elif f == 2:
                cur[i] = (cur[i] + b) & 255
            elif f == 3:
                cur[i] = (cur[i] + ((a + b) // 2)) & 255
            elif f == 4:
                q = a + b - c
                pa = abs(q - a)
                pb = abs(q - b)
                pc = abs(q - c)
                cur[i] = (cur[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(cur)
        prev = cur
    return tuple(rows[y][x * bpp : x * bpp + 3])


def run(mode, store):
    cmd = [
        "xvfb-run",
        "-a",
        "-s",
        "-screen 0 1280x720x24",
        str(ENGINE),
        "--mode",
        str(mode),
        "--storage",
        str(store),
        "--frames",
        "2",
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
    if p.returncode:
        raise AssertionError(p.stdout)
    return next((store / "grabs").glob("*.png"))


def main():
    with tempfile.TemporaryDirectory(prefix="eyesy-target-") as td:
        root = Path(td)
        modes = []
        for variant, SHADER in SHADERS.items():
            for name, body in [
                ("full", """shader=e.shader("gradient.frag")"""),
                ("target", """shader=e.shader("gradient.frag"); target=e.target(320,180)"""),
            ]:
                draw = (
                    "e.draw_shader(shader,0,0,0)"
                    if name == "full"
                    else "e.begin_target(target); e.draw_shader(shader,0,0,0); e.color(1,1,1); e.rect(40,40,20,20); e.end_target(); e.draw_target(target,0,0,1280,720); e.color(1,0,1); e.rect(0,0,10,10)"
                )
                mode = root / (variant + "-" + name)
                mode.mkdir()
                modes.append(mode)
                (mode / "gradient.frag").write_text(SHADER)
                (mode / "main.lua").write_text(
                    "local e=eyesy; return {api_version=1,setup=function(ctx) "
                    + body
                    + " end,draw=function(ctx) "
                    + draw
                    + " end}"
                )
        images = [run(m, root / ("store-" + m.name)) for m in modes]
        pts = [
            (320, 180, (255, 0, 0)),
            (960, 180, (0, 0, 255)),
            (320, 540, (0, 255, 0)),
            (960, 540, (255, 255, 0)),
        ]
        for mode, im in zip(modes, images):
            for x, y, want in pts:
                got = pixel(im, x, y)
                if max(abs(got[i] - want[i]) for i in range(3)) > 12:
                    raise AssertionError((mode.name, x, y, want, got))
        for target_image in (images[1], images[3]):
            if pixel(target_image, 5, 5) != (255, 0, 255):
                raise AssertionError("parent projection was not restored after target")
            if pixel(target_image, 200, 200) != (255, 255, 255):
                raise AssertionError("inner target primitive was misplaced")
        for a, b in ((0, 1), (2, 3)):
            for p in pts:
                if pixel(images[a], *p[:2]) != pixel(images[b], *p[:2]):
                    raise AssertionError("target differs from full render")
    print("Render target pixel regression passed")


if __name__ == "__main__":
    main()
