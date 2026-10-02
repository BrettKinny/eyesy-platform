#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Guard one identified experiment PID when the device lacks memory cgroups."""

import argparse
import json
import os
from pathlib import Path
import signal
import time
import math


def identity(pid):
    try:
        # comm may contain spaces or parentheses; fields after its last ')' start at state.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (FileNotFoundError, IndexError, ValueError):
        return None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_telemetry(rss, temperature):
    if rss < 0 or rss > 1 << 40 or not math.isfinite(temperature) or temperature < -50 or temperature > 150:
        raise ValueError("insane process telemetry")
    return rss, temperature


def reading(pid):
    lines = Path(f"/proc/{pid}/status").read_text().splitlines()
    rss = next(int(line.split()[1]) * 1024 for line in lines if line.startswith("VmRSS:"))
    temperature = float(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    return validate_telemetry(rss, temperature)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clone-id", required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=6000)
    args = parser.parse_args()
    require(1 < args.pid and 1 <= args.duration <= 7200, "invalid pid or duration")
    require(
        json.loads(Path("/etc/eyesy-development-clone").read_text())["clone_id"] == args.clone_id,
        "clone identity mismatch",
    )
    require("Compute Module 3 Plus" in Path("/proc/device-tree/model").read_text(), "wrong board")
    require(Path(f"/proc/{args.pid}/exe").resolve() == args.engine.resolve(), "engine identity mismatch")
    require(not args.output.is_symlink() and args.output.is_dir(), "output must be an existing directory")
    output = args.output.resolve()
    require(output.is_relative_to(Path("/sdcard/eyesy-platform/experiments")), "output outside experiments")
    original = identity(args.pid)
    require(original is not None, "target process is unavailable")
    try:
        pidfd = os.pidfd_open(args.pid)
    except (AttributeError, OSError) as exc:
        raise RuntimeError("pidfd support is required") from exc
    started = time.monotonic()
    reason = "process exited"
    guard_triggered = False
    peak_rss, peak_temperature = 0, 0
    failure = None

    def stop_target():
        def matches():
            try:
                return (
                    identity(args.pid) == original
                    and Path(f"/proc/{args.pid}/exe").resolve() == args.engine.resolve()
                )
            except FileNotFoundError:
                # A terminated but not-yet-reaped process may retain stat while
                # its /proc/PID/exe magic link has already disappeared.
                return False

        if matches():
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                time.sleep(3)
                if matches():
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass

    try:
        require(identity(args.pid) == original, "target identity changed during setup")
        require(
            Path(f"/proc/{args.pid}/exe").resolve() == args.engine.resolve(),
            "engine identity changed during setup",
        )
        with (output / "guard-samples.jsonl").open("x") as samples:
            while identity(args.pid) == original:
                try:
                    rss, temperature = reading(args.pid)
                except (FileNotFoundError, StopIteration):
                    if identity(args.pid) != original:
                        break
                    raise
                elapsed = time.monotonic() - started
                peak_rss, peak_temperature = max(peak_rss, rss), max(peak_temperature, temperature)
                samples.write(
                    json.dumps({"elapsed": elapsed, "rss_bytes": rss, "temperature_c": temperature}) + "\n"
                )
                samples.flush()
                if rss > 256 * 1024 * 1024 or temperature >= 80 or elapsed >= args.duration:
                    reason = (
                        "RSS limit"
                        if rss > 256 * 1024 * 1024
                        else "temperature limit"
                        if temperature >= 80
                        else "duration limit"
                    )
                    guard_triggered = True
                    stop_target()
                    break
                time.sleep(5)
    except Exception as exc:
        failure = str(exc)
        reason = "guard error"
        guard_triggered = True
        try:
            stop_target()
        except OSError as stop_error:
            failure += "; target stop failed: " + str(stop_error)
    finally:
        os.close(pidfd)
    result = {
        "pid": args.pid,
        "reason": reason,
        "target_exit_status": None,
        "guard_triggered": guard_triggered,
        "wall_seconds": time.monotonic() - started,
        "peak_rss_bytes": peak_rss,
        "peak_temperature_c": peak_temperature,
        "rss_limit_bytes": 256 * 1024 * 1024,
        "temperature_limit_c": 80,
    }
    if failure:
        result["error"] = failure
    (output / "guard-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if reason == "process exited" and not guard_triggered else 1


if __name__ == "__main__":
    raise SystemExit(main())
