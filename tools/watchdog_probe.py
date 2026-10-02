#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Bounded spare-card watchdog experiment; never changes production units/boot."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from release import check_clone

UNIT = "eyesy-independent-watchdog-probe.service"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, **kwargs):
    return subprocess.run(
        args, check=True, text=True, capture_output=True, timeout=20, **kwargs
    ).stdout.strip()


def properties():
    output = run("systemctl", "show", UNIT, "-p", "MainPID", "-p", "NRestarts", "-p", "ActiveState")
    return dict(line.split("=", 1) for line in output.splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clone-id", required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--mode", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check_clone(args.clone_id)
    engine, mode, output = args.engine.resolve(), args.mode.resolve(), args.output.resolve()
    require(engine.is_file() and (mode / "main.lua").is_file(), "engine/mode unavailable")
    require(not args.output.is_symlink() and not output.exists(), "output must be a new non-symlink path")
    require(output.is_relative_to(Path("/sdcard/eyesy-platform/experiments")), "output outside experiments")
    require(run("systemctl", "is-active", "eyesypy.service") == "active", "stock service is not active")
    require(
        run("systemctl", "show", UNIT, "-p", "LoadState", "--value") == "not-found",
        "probe unit already exists",
    )
    run("install", "-d", "-o", "music", "-g", "music", str(output))
    result = {"hardware_acceptance": False, "probe": "independent-offscreen-watchdog"}
    launch_attempted = False
    try:
        launch_attempted = True
        run(
            "systemd-run",
            "--unit=" + UNIT,
            "--collect",
            "--uid=music",
            "--property=Type=notify",
            "--property=WatchdogSec=3",
            "--property=TimeoutStartSec=15",
            "--property=TimeoutStopSec=2",
            "--property=TimeoutAbortSec=2",
            "--property=Restart=on-failure",
            "--property=RestartSec=1",
            "--property=RuntimeMaxSec=60",
            "--property=LimitCORE=0",
            str(engine),
            "--offscreen",
            "--mode",
            str(mode),
            "--frames",
            "1800",
            "--storage",
            str(output),
        )
        deadline = time.monotonic() + 10
        while not (output / "status.json").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("Initial heartbeat missing")
            time.sleep(0.2)
        before = properties()
        pid = int(before["MainPID"])
        require(pid > 1 and before["ActiveState"] == "active", str(before))
        injected = time.monotonic()
        run("systemctl", "kill", "--kill-whom=main", "--signal=STOP", UNIT)
        deadline = injected + 15
        while True:
            state = properties()
            if int(state["MainPID"]) > 1 and int(state["MainPID"]) != pid and int(state["NRestarts"]) >= 1:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Watchdog did not restart stopped engine")
            time.sleep(0.3)
        result.update(before=before, after=state, restart_seconds=time.monotonic() - injected)
        # A new PID alone is insufficient: require its status file to advance.
        time.sleep(1.2)
        first = json.loads((output / "status.json").read_text())
        time.sleep(1.2)
        second = json.loads((output / "status.json").read_text())
        require(second["frame"] > first["frame"] and not second["error"], str((first, second)))
        require("VC4" in second["renderer"], str(second))
        result.update(passed=True, resumed_frame=second["frame"], renderer=second["renderer"])
    finally:
        primary_exception = sys.exc_info()[0]
        cleanup_error = None
        if launch_attempted:
            try:
                run("systemctl", "stop", UNIT)
            except Exception as exc:
                cleanup_error = str(exc)
        try:
            result["stock_active_after"] = run("systemctl", "is-active", "eyesypy.service") == "active"
        except Exception as exc:
            result["stock_active_after"] = False
            cleanup_error = cleanup_error or str(exc)
        result["passed"] = bool(result.get("passed")) and result["stock_active_after"] and not cleanup_error
        if cleanup_error:
            result["cleanup_error"] = cleanup_error
        try:
            (output / "watchdog-report.json").write_text(json.dumps(result, indent=2) + "\n")
        except Exception as exc:
            # Never mask a launch/restart/cleanup exception with report I/O.
            result["report_error"] = str(exc)
            if primary_exception is None:
                raise
    print(json.dumps(result, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
