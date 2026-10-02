#!/usr/bin/env python3
"""Black-box runtime API robustness checks against the desktop engine."""

import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path("/workspace")
ENGINE = ROOT / "engine/bin/engine"


def run(mode, storage, expected=2):
    report = storage / "report.json"
    result = subprocess.run(
        [
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
            "3",
            "--report",
            str(report),
        ],
        timeout=25,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != expected:
        raise AssertionError(f"{mode}: expected {expected}, got {result.returncode}\n{result.stdout}")
    return json.loads(report.read_text())


def make(root, name, body):
    path = root / name
    path.mkdir()
    (path / "main.lua").write_text(body)
    return path


def main():
    with tempfile.TemporaryDirectory(prefix="eyesy-runtime-") as scratch:
        root = Path(scratch)
        malformed = [
            ("mesh-not-table", "eyesy.mesh(42)", "table"),
            # Non-table vertices must be rejected, not silently converted to 0.
            ("mesh-bad-vertex", "eyesy.mesh({{1, 2}})", "vertex"),
            (
                "update-bad-vertex",
                'local m=eyesy.new_mesh(); eyesy.update_mesh(m, {{"x", 2, 3}})',
                "mesh coordinate",
            ),
            ("target-dimensions", "eyesy.target(0, 720)", "target exceeds"),
            ("target-fraction", "eyesy.target(1.5, 720)", "integer"),
            ("shader-texture-id", 'local s=eyesy.shader("missing.frag")', "shader file missing"),
        ]
        for name, expression, expected_text in malformed:
            body = "return {api_version=1,setup=function() %s end,draw=function() end}" % expression
            report = run(make(root, name, body), root / ("storage-" + name))
            assert report["mode_errors"] == 1, report
            assert expected_text in report["error"], (name, report)
        callback = make(
            root,
            "callback-failure",
            """
return {api_version=1,
  setup=function(ctx) eyesy.target(64,64) end,
  draw=function(ctx) eyesy.begin_target(1) error("callback boom") end,
  teardown=function(ctx) error("teardown must not mask callback") end}
""",
        )
        report = run(callback, root / "storage-callback")
        assert report["mode_errors"] == 1 and "callback boom" in report["error"], report
    print("Runtime robustness tests passed: malformed graphics inputs and callback cleanup")


if __name__ == "__main__":
    main()
