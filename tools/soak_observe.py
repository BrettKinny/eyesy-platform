#!/usr/bin/env python3
"""Observe-only soak driver for the eyesy platform.

Samples status.json + thermal at a fixed interval and cycles modes via OSC
/key events (key 5 = next mode). NEVER signals, restarts, or kills the
engine -- that is soak_guard.py's job, and ROADMAP item 4 forbids it here.

    sudo -n python3 soak_observe.py --duration 3600 --interval 5 \
        --output /sdcard/eyesy-platform/experiments/soak-<date> --mode-seconds 120
"""
import argparse, json, os, socket, struct, sys, time


def osc_key(port, key, down):
    msg = b"/key\x00\x00\x00\x00" + b",ii\x00" + struct.pack(">ii", key, 1 if down else 0)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg, ("127.0.0.1", port))


def read_status(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=3600)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--osc-port", type=int, default=4000)
    ap.add_argument("--storage", default="/sdcard/eyesy-platform")
    ap.add_argument("--output", required=True)
    ap.add_argument("--mode-seconds", type=float, default=120.0,
                    help="seconds per mode before advancing (0 = no switching)")
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)
    status_path = os.path.join(args.storage, "status.json")
    samples_path = os.path.join(args.output, "samples.jsonl")
    started = time.monotonic()
    next_switch = started + args.mode_seconds
    n = 0
    with open(samples_path, "a", buffering=1) as out:
        while time.monotonic() - started < args.duration:
            now = time.monotonic()
            status = read_status(status_path)
            try:
                with open("/sys/class/thermal/thermal_zone0/temp") as f:
                    temp = int(f.read().strip()) / 1000.0
            except OSError:
                temp = None
            sample = {"t": round(now - started, 2),
                      "temperature_c": temp,
                      "status": status}
            out.write(json.dumps(sample) + "\n")
            n += 1
            if args.mode_seconds and now >= next_switch:
                osc_key(args.osc_port, 5, True)
                time.sleep(0.2)
                osc_key(args.osc_port, 5, False)
                next_switch = now + args.mode_seconds
            time.sleep(max(0.0, args.interval - (time.monotonic() - now)))
    print(json.dumps({"samples": n, "wall_seconds": time.monotonic() - started}))


if __name__ == "__main__":
    sys.exit(main())
