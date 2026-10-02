#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Renderer integration checks for palette registration and creative modes."""

import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path("/workspace")
ENGINE = ROOT / "engine/bin/engine"

# Self-contained stand-ins for the creative mode shapes (mode packs are separate
# repos and may be absent): a palette-tinted shader drawn through a reduced
# target, indexed meshes in 3D, and ping-pong feedback targets.
CREATIVE = {
    "shader-target": (
        """local e = eyesy
local shader, half
return {api_version=1,
  setup=function(ctx)
    e.define_palette("glow", {{0.01,0.02,0.08}, {0.04,0.55,0.65}, {0.62,1.0,0.72}})
    half = e.target(640, 360)
    shader = e.shader("glow.frag")
  end,
  draw=function(ctx)
    local r, g, b = e.palette("glow", ctx.time * 0.1)
    e.begin_target(half)
    e.draw_shader(shader, ctx.time, ctx.audio.rms_left, 0.5, {tint={r,g,b}, width=0.6})
    e.end_target()
    e.color(1, 1, 1)
    e.draw_target(half, 0, 0, ctx.width, ctx.height)
  end}""",
        {
            "glow.frag": """varying vec2 uv;
uniform float u_time;
uniform float u_energy;
uniform float width;
uniform vec3 tint;
void main() {
    float band = exp(-abs(uv.y - 0.5 - 0.2 * sin(uv.x * 6.0 + u_time)) * (4.0 + width * 8.0));
    gl_FragColor = vec4(tint * band * (0.7 + u_energy), 1.0);
}"""
        },
    ),
    "indexed-mesh": (
        """local e = eyesy
local strip, facets, points, quads, indices = nil, nil, {}, {}, {}
return {api_version=1,
  setup=function(ctx)
    strip, facets = e.new_mesh(), e.new_mesh()
    for i=1,128 do points[i] = {0,0,0} end
    for i=1,16 do
      quads[i], quads[16+i] = {0,0,0}, {0,0,0}
      local n, j = i % 16 + 1, (i-1)*6
      indices[j+1], indices[j+2], indices[j+3] = i, 16+i, n
      indices[j+4], indices[j+5], indices[j+6] = 16+i, 16+n, n
    end
  end,
  draw=function(ctx)
    e.clear(0.01, 0.01, 0.03)
    e.depth(false) e.push() e.translate(ctx.width/2, ctx.height/2, 0) e.rotate(ctx.time*20, 0, 1, 0)
    for i=1,128 do local p = points[i]
      p[1], p[2], p[3] = (i/128-0.5)*1100, (ctx.audio.left[i*4] or 0)*120, math.sin(i*0.1+ctx.time)*120 end
    e.color(e.palette("sunset", ctx.time*0.03)) e.update_mesh(strip, points) e.draw_mesh(strip)
    for i=1,16 do local p = points[i*8]
      quads[i][1], quads[i][2], quads[i][3] = p[1], p[2]-30, p[3]+30
      quads[16+i][1], quads[16+i][2], quads[16+i][3] = p[1], p[2]+30, p[3]-30 end
    local r, g, b = e.palette("mint", ctx.time*0.04)
    e.color(r, g, b, 0.2) e.update_mesh(facets, quads, indices) e.draw_mesh(facets)
    e.pop()
  end}""",
        {},
    ),
    "feedback": (
        """local e = eyesy
local front, back
return {api_version=1,
  setup=function(ctx) front, back = e.target(ctx.width, ctx.height), e.target(ctx.width, ctx.height) end,
  draw=function(ctx)
    e.begin_target(back)
    e.clear(0.004, 0.006, 0.016)
    e.push() e.translate(ctx.width/2, ctx.height/2) e.rotate(math.sin(ctx.time)*2.5) e.scale(1.01, 1.01)
    e.color(1, 1, 1, 0.9) e.draw_target(front, -ctx.width/2, -ctx.height/2)
    e.pop()
    e.color(e.palette("ember", ctx.time*0.04))
    e.circle(ctx.width/2 + math.cos(ctx.time*1.3)*260, ctx.height/2, 40 + ctx.audio.rms_left*60)
    e.end_target()
    e.color(1, 1, 1) e.draw_target(back, 0, 0)
    front, back = back, front
  end}""",
        {},
    ),
}


def run(mode, storage, frames=4, expected=0):
    report = storage / "report.json"
    command = [
        "xvfb-run",
        "-a",
        "-s",
        "-screen 0 1280x720x24",
        str(ENGINE),
        "--mode",
        str(mode),
        "--storage",
        str(storage),
        "--frames",
        str(frames),
        "--report",
        str(report),
    ]
    result = subprocess.run(command, timeout=25, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != expected:
        raise AssertionError(f"{mode}: expected {expected}, got {result.returncode}\n{result.stdout}")
    return json.loads(report.read_text())


def mode(folder, body):
    folder.mkdir(parents=True)
    (folder / "main.lua").write_text(body)


def assert_error(root, temp, name, body, text):
    path = root / name
    mode(path, body)
    report = run(path, temp / name, expected=2)
    assert text in report["error"], (text, report["error"])


def main():
    with tempfile.TemporaryDirectory(prefix="eyesy-creative-") as scratch:
        scratch = Path(scratch)
        valid = scratch / "valid"
        mode(
            valid,
            """
local e = eyesy
return {api_version=1,
  setup=function(ctx)
    e.define_palette("test", {{0,0.2,1}, {1,0.4,0}})
  end,
  draw=function(ctx)
    local r,g,b=e.palette("test", 1.5)
    local cr,cg,cb=e.palette(0.25)
    if math.abs(r-0.5)>0.001 or math.abs(g-0.3)>0.001 or math.abs(b-0.5)>0.001 then error("palette interpolation") end
    if cr<0 or cg<0 or cb<0 or cr>1 or cg>1 or cb>1 then error("cosine palette range") end
  end}
""",
        )
        report = run(valid, scratch / "valid")
        assert not report["error"] and report["mode_errors"] == 0

        invalid = """return {api_version=1,setup=function(ctx) %s end,draw=function() end}"""
        assert_error(scratch, scratch, "unknown", invalid % 'eyesy.palette("missing", 0)', "unknown palette")
        assert_error(scratch, scratch, "too-few", invalid % 'eyesy.define_palette("x", {{1,0,0}})', "2..16")
        assert_error(
            scratch,
            scratch,
            "too-many-stops",
            invalid
            % 'eyesy.define_palette("x", {{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0}})',
            "2..16",
        )
        assert_error(
            scratch,
            scratch,
            "bad-stop",
            invalid % 'eyesy.define_palette("x", {{1,0},{0.5,0.5,0.5}})',
            "RGB triples",
        )
        assert_error(
            scratch, scratch, "nan", invalid % 'eyesy.define_palette("x", {{0/0,0,0},{1,1,1}})', "nonfinite"
        )
        assert_error(
            scratch,
            scratch,
            "inf",
            invalid % 'eyesy.define_palette("x", {{math.huge,0,0},{1,1,1}})',
            "nonfinite",
        )

        cap = (
            "local e=eyesy; return {api_version=1, setup=function() "
            + "".join('e.define_palette("p%d", {{0,0,0},{1,1,1}});' % i for i in range(29))
            + " end, draw=function() end}"
        )
        assert_error(scratch, scratch, "palette-cap", cap, "palette budget")
        targets = (
            "local e=eyesy; return {api_version=1, setup=function() "
            + "e.target(1280,720);" * 9
            + " end, draw=function() end}"
        )
        assert_error(scratch, scratch, "target-cap", targets, "target exceeds")

        for name, (body, assets) in CREATIVE.items():
            folder = scratch / "creative" / name
            mode(folder, body)
            for asset, text in assets.items():
                (folder / asset).write_text(text)
            report = run(folder, scratch / ("mode-" + name), frames=8)
            assert not report["error"] and report["mode_errors"] == 0, report
            assert report["resources"] <= 4, report["resources"]
    print("Creative tests passed: palette interpolation, compatibility, validation, cap, and modes")


if __name__ == "__main__":
    main()
