#!/usr/bin/env python3
"""Integration checks against the compiled renderer; run inside the build container."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path("/workspace")
ENGINE = ROOT / "engine/bin/engine"


def run(mode, storage, frames=60, replay=None, expected=0):
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
    if replay:
        command += ["--replay", str(replay)]
    result = subprocess.run(command, timeout=25, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != expected:
        raise AssertionError(f"{mode}: expected {expected}, got {result.returncode}\n{result.stdout}")
    return json.loads(report.read_text())


def main():
    with tempfile.TemporaryDirectory(prefix="eyesy-graphics-") as temp:
        temp = Path(temp)
        broken = temp / "modes/broken"
        broken.mkdir(parents=True)
        (broken / "main.lua").write_text(
            'return {api_version=1,draw=function(ctx) error("intentional draw failure") end}'
        )
        result = run(broken, temp / "broken", expected=2)
        assert "intentional draw failure" in result["error"]
        assert result["mode_errors"] == 1
        (broken / "main.lua").write_text("this is not lua!")
        result = run(broken, temp / "syntax", expected=2)
        assert result["error"]
        (broken / "main.lua").write_text("return {api_version=99,draw=function() end}")
        result = run(broken, temp / "version", expected=2)
        assert "api_version" in result["error"]
        (broken / "main.lua").write_text("return {api_version=1,draw=function() eyesy.pop() end}")
        result = run(broken, temp / "underflow", expected=2)
        assert "underflow" in result["error"]
        # Non-string error values (error({})) must surface as a message, not a crash,
        # whether raised while loading or from a scene restore.
        (broken / "main.lua").write_text("error({})")
        result = run(broken, temp / "table-error", expected=2)
        assert "table value" in result["error"], result
        (broken / "main.lua").write_text(
            "return {api_version=1,draw=function() end,restore=function() error({}) end}"
        )
        (temp / "restore/scenes").mkdir(parents=True)
        (temp / "restore/scenes/scene-0.json").write_text(
            json.dumps({"schema_version": 1, "mode": "broken", "parameters": {}, "state": {}})
        )
        replay = temp / "restore-replay.json"
        replay.write_text(json.dumps([{"frame": 1, "type": "hardware_key", "key": 7}]))
        result = run(broken, temp / "restore", replay=replay, expected=2)
        assert "table value" in result["error"], result
        hashes = []
        for iteration in range(2):
            storage = temp / f"replay-{iteration}"
            result = run(ROOT / "modes/starter", storage, replay=ROOT / "tests/fixtures/replay.json")
            assert not result["error"] and result["mode_errors"] == 0
            scenes = list((storage / "scenes").glob("*.json"))
            assert len(scenes) == 1
            scene = json.loads(scenes[0].read_text())
            assert abs(scene["parameters"]["size"] - 0.2875) < 1e-6
            image = next((storage / "grabs").glob("*.png"))
            hashes.append(hashlib.sha256(image.read_bytes()).hexdigest())
        assert hashes[0] == hashes[1], "replayed images differ"
        # Persist polarity: ctx.auto_clear must reach the mode with the right
        # polarity, and a persist-off run must actually trail differently.
        polarity = temp / "persist"
        for name, expected in (("on", "true"), ("off", "false")):
            folder = polarity / name
            folder.mkdir(parents=True)
            (folder / "main.lua").write_text(
                "return {api_version=1, draw=function(ctx)\n"
                f'  assert(ctx.auto_clear == {expected}, "auto_clear polarity")\n'
                "  if ctx.auto_clear then eyesy.clear(0,0,.1)\n"
                "  else eyesy.color(0,0,.1,.08) eyesy.rect(0,0,ctx.width,ctx.height) end\n"
                "  eyesy.color(1,1,1)\n"
                "  eyesy.circle(80 + (ctx.time * 900) % 1100, 360, 60)\n"
                "end}"
            )
            replay = polarity / f"{name}-replay.json"
            replay.write_text(
                json.dumps([] if name == "on" else [{"frame": 0, "type": "hardware_key", "key": 3}])
            )
            store = polarity / f"{name}-store"
            result = run(folder, store, frames=90, replay=replay)
            assert not result["error"] and result["mode_errors"] == 0, result
        on_grab = next((polarity / "on-store" / "grabs").glob("*.png"))
        off_grab = next((polarity / "off-store" / "grabs").glob("*.png"))
        assert on_grab.read_bytes() != off_grab.read_bytes(), "persist changed nothing"
        # The same polarity must hold for the public starter and for a 3D mesh
        # mode (depth off, rotated audio waveforms, decayed rather than cleared).
        mesh = temp / "modes/mesh"
        mesh.mkdir(parents=True)
        (mesh / "main.lua").write_text("""local e = eyesy
local mesh, points = nil, {}
return {api_version=1,
  setup=function(ctx) mesh = e.new_mesh() for i=1,256 do points[i]={0,0,0} end end,
  draw=function(ctx)
    if ctx.auto_clear then e.clear(0.02,0.02,0.04)
    else e.color(0.02,0.02,0.04,0.08) e.rect(0,0,ctx.width,ctx.height) end
    e.depth(false) e.push() e.translate(ctx.width/2, ctx.height/2, 0) e.rotate(20+ctx.time*40, 0, 1, 0)
    for channel=1,2 do
      local wave = channel==1 and ctx.audio.left or ctx.audio.right
      for i=1,256 do local p=points[i]
        p[1],p[2],p[3] = (i/256-0.5)*1080, wave[i*4]*150+(channel-1.5)*180, math.sin(i/25+ctx.time)*200 end
      e.color(e.palette(0.3*channel)) e.update_mesh(mesh, points) e.draw_mesh(mesh)
    end
    e.pop()
  end}""")
        for pilot in (ROOT / "modes/starter", mesh):
            pilot_hashes = []
            for name, events in (("on", []), ("off", [{"frame": 0, "type": "hardware_key", "key": 3}])):
                replay = temp / f"{pilot.name}-persist-{name}.json"
                replay.write_text(json.dumps(events))
                store = temp / f"{pilot.name}-persist-{name}"
                result = run(pilot, store, frames=90, replay=replay)
                assert not result["error"] and result["mode_errors"] == 0, result
                pilot_hashes.append(
                    hashlib.sha256(next((store / "grabs").glob("*.png")).read_bytes()).hexdigest()
                )
            assert pilot_hashes[0] != pilot_hashes[1], f"{pilot.name} ignored persist"
        # Instrument HUD (Phase 4): the overlay draws on the composited window
        # and must never leak into the mode render, at a fixed draw-call cost.
        hud_dir = temp / "hud"
        hud_dir.mkdir(parents=True)
        (hud_dir / "main.lua").write_text(
            "return {api_version=1, draw=function(ctx) eyesy.clear(0,0,0) "
            "eyesy.color(1,1,1) eyesy.circle(640,360,120) end}"
        )
        hud = {}
        for name, events in (("on", []), ("off", [{"frame": 0, "type": "hardware_key", "key": 1}])):
            replay = hud_dir / f"{name}-replay.json"
            replay.write_text(json.dumps(events))
            store = hud_dir / name
            result = run(hud_dir, store, frames=90, replay=replay)
            assert not result["error"] and result["mode_errors"] == 0, result
            assert result["fps"] > 25, ("HUD slowed the engine", result["fps"])
            hud[name] = (
                result,
                hashlib.sha256(next((store / "grabs").glob("*.png")).read_bytes()).hexdigest(),
            )
        assert hud["on"][0]["hud_draw_calls"] == 9, hud["on"][0]["hud_draw_calls"]
        assert hud["off"][0]["hud_draw_calls"] == 0, hud["off"][0]["hud_draw_calls"]
        assert hud["on"][1] == hud["off"][1], "HUD leaked into the mode render"
        print(
            "Graphics tests passed: Lua errors, syntax, API versions, matrix cleanup, scenes, "
            "deterministic images, persist polarity"
        )


if __name__ == "__main__":
    main()
