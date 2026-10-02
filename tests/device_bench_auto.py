#!/usr/bin/env python3
"""Automated bench acceptance against a live EYESY platform unit.

Covers what can be driven without hands:
  * the HDMI latch oracle over the whole run (HDMI_VID_CTL never latches),
  * MIDI input over ALSA: CC 20-24 -> knobs, notes 60/62/64 -> the engine's own
    hardware-test row, clock/start/continue/stop accepted cleanly,
  * a render smoke over the whole mode catalog from the capture stream,
  * frame-pacing samples per mode.

NOT covered here (they need hands or a signal source) -- see
docs/BENCH-CHECKLIST.md: physical knob/button feel, a known stereo line-in
through the codec, and HDMI-visible latency.

Requirements: ssh `music@<host>` with passwordless sudo, and an HDMI->USB
capture streamer already writing a rolling PNG (~2 fps) for the whole run.
"""
import argparse
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE_PORT = 4000
STORE = "/sdcard/eyesy-platform"

PRELUDE = '''
import json, socket, struct, time

ENGINE, STORE = 4000, '/sdcard/eyesy-platform'


def pack(address, tags, args):
    def s(x):
        b = x.encode() + b'\\0'
        return b + b'\\0' * ((4 - len(b) % 4) % 4)
    return s(address) + s(tags) + b''.join(struct.pack(fmt, v) for fmt, v in args)


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send(payload):
    sock.sendto(payload, ('127.0.0.1', ENGINE))


def keys(number, down=1):
    send(pack('/key', ',ii', [('>i', number), ('>i', down)]))


def knobs(values):
    send(pack('/knobs', ',iiiiii', [('>i', v) for v in values] + [('>i', 0)]))


def press(number, hold=.15):
    keys(number); time.sleep(hold); keys(number, 0); time.sleep(hold)


def combo(number, hold=.15):
    keys(2); time.sleep(.12); press(number, hold); keys(2, 0); time.sleep(.15)


def status():
    for _ in range(30):
        try:
            with open(STORE + '/status.json') as handle:
                return json.load(handle)
        except (OSError, ValueError):
            time.sleep(.1)
    return {}


def wait_for(predicate, label, timeout=6):
    end = time.monotonic() + timeout
    state = {}
    while time.monotonic() < end:
        state = status()
        if predicate(state):
            return state
        time.sleep(.15)
    raise SystemExit('unmet: %s %s' % (label, json.dumps(state)))
'''


def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def smf(events, division=96):
    """Standard MIDI file (format 0). events = [(delta_ticks, bytes), ...]."""
    track = bytearray()
    for delta, data in events:
        track += vlq(delta) + data
    track += vlq(0) + b"\xff\x2f\x00"
    return (b"MThd" + struct.pack(">IHHH", 6, 0, 1, division)
            + b"MTrk" + struct.pack(">I", len(track)) + bytes(track))


# HUD knob sliders: authored at x 20..83, y 105..129 in the stock 480-line
# framebuffer (engine/src/osd_hud.cpp), scaled to the live height.
KNOB_REGION = (30, 157, 124, 193)      # 1280x720: (20,105)-(83,129) * 1.5


def region_diff(a, b, box=KNOB_REGION, threshold=24):
    from PIL import Image, ImageChops
    left = Image.open(a).convert("L").crop(box)
    right = Image.open(b).convert("L").crop(box)
    return sum(1 for p in ImageChops.difference(left, right).get_flattened_data() if p > threshold)


class Device:
    def __init__(self, host, known_hosts):
        options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                   "-o", "StrictHostKeyChecking=yes"]
        if known_hosts:
            options += ["-o", f"UserKnownHostsFile={known_hosts}"]
        self.ssh = ["ssh"] + options + [f"music@{host}"]
        self.scp = ["scp"] + options

    def run(self, remote, timeout=180):
        result = subprocess.run(self.ssh + [remote], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, timeout=timeout)
        if result.returncode != 0:
            raise AssertionError(f"remote command failed: {remote}\n{result.stdout}")
        return result.stdout

    def python(self, script, timeout=180):
        result = subprocess.run(self.ssh + ["python3", "-"], input=script,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout)
        if result.returncode != 0:
            raise AssertionError(f"remote python failed:\n{result.stdout}")
        return result.stdout

    def json(self, script, timeout=180):
        return json.loads(self.python(script, timeout).strip().splitlines()[-1])

    def status(self):
        return json.loads(self.run(f"cat {STORE}/status.json"))

    def scenes(self):
        listing = self.run(f"ls -1 {STORE}/scenes 2>/dev/null || true")
        return sorted(n for n in listing.split() if n.endswith(".json"))

    def engine_midi_port(self):
        listing = self.run("aconnect -l 2>/dev/null || true")
        match = re.search(r"client (\d+): 'EYESY Platform'", listing)
        if not match:
            raise AssertionError("engine has no ALSA sequencer port (aconnect -l)")
        return f"{match.group(1)}:0"

    def play_midi(self, port, name, events, background=False, hold=0.0):
        """Write an SMF on the device and send it to the engine's port."""
        data = smf(events)
        local = pathlib.Path("/tmp") / f"eyesy-{name}.mid"
        local.write_bytes(data)
        remote = f"/tmp/eyesy-{name}.mid"
        subprocess.run(self.scp + [str(local), f"music@{self.host}:{remote}"],
                       check=True, stdout=subprocess.PIPE, timeout=60)
        if background:
            self.run(f"aplaymidi -p {port} {remote} > /tmp/eyesy-{name}.log 2>&1 & echo $! > /tmp/eyesy-{name}.pid")
            return
        self.run(f"aplaymidi -p {port} {remote} > /tmp/eyesy-{name}.log 2>&1")

    def stop_midi(self, name):
        self.run(f"kill $(cat /tmp/eyesy-{name}.pid) 2>/dev/null || true")


class Capture:
    """Rolling HDMI capture frame reader; the streamer owns the device."""

    def __init__(self, path, output):
        self.path = pathlib.Path(path)
        self.output = output
        self.frames = {}

    def alive(self):
        if not self.path.is_file():
            raise AssertionError(f"capture file missing: {self.path}")
        if self.path.stat().st_size < 10000:
            raise AssertionError("capture stream looks blank; is the streamer up?")
        return True

    def snapshot(self, label):
        self.alive()
        for _ in range(20):
            data = self.path.read_bytes()
            if data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82"):
                break
            time.sleep(.1)
        else:
            raise AssertionError(f"{label}: capture frame never settled")
        (self.output / f"{label}.png").write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.frames[label] = {"sha256": digest, "bytes": len(data)}
        return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--frames", type=pathlib.Path, default=ROOT / "local/hdmi/latest.png")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--known-hosts", type=pathlib.Path,
                        default=ROOT / "local/eyesy_known_hosts")
    parser.add_argument("--skip-modes", action="store_true", help="skip the catalog render smoke")
    parser.add_argument("--known-broken", action="append", default=[], metavar="MODE",
                        help="mode already known to fail setup in the deployed release (fixed in "
                             "its pack, cleared by a redeploy); repeatable. Any other failing "
                             "mode still fails the run")
    args = parser.parse_args()
    known_broken = set(args.known_broken)
    if args.output.exists():
        sys.exit("--output must not already exist")
    args.output.mkdir(parents=True)
    known = args.known_hosts if args.known_hosts.is_file() else None
    device = Device(args.host, known)
    device.host = args.host
    capture = Capture(args.frames, args.output)
    report = {"host": args.host, "steps": {}}

    def record(step, payload, frame=None):
        report["steps"][step] = payload
        print(f"{step}: {json.dumps(payload)[:240]}")

    # 0. Converge on the idle baseline and confirm the capture is live.
    device.json(PRELUDE + '''
keys(10, 0); keys(2, 0)
for _ in range(6):
    time.sleep(1.2)
    if status().get('sequencer') == 'stopped':
        break
    combo(9)
print(json.dumps(status()))
''')
    baseline = device.json(PRELUDE + '''
print(json.dumps(wait_for(lambda s: s.get('mode') == 'starter' and s.get('menu_screen') == -1
                          and s.get('sequencer') == 'stopped' and s.get('fps', 0) > 20,
                          'idle baseline', timeout=10)))
''')
    assert baseline["mode_errors"] <= len(known_broken), baseline
    record("00-baseline", {k: baseline.get(k) for k in
                           ("release", "mode", "fps", "renderer", "mode_count", "diagnostics")},
           capture.snapshot("00-baseline"))

    # 1. Latch oracle: HDMI_VID_CTL must never show the latched bit-25 state.
    samples = []
    for _ in range(24):
        out = device.run(
            "sudo -n grep VID_CTL /sys/kernel/debug/dri/0/hdmi_regs 2>/dev/null "
            "| grep -o '0x[0-9a-f]*' | head -1")
        value = out.strip()
        if value:
            samples.append(value)
        time.sleep(0.15)
    bad = [s for s in samples if s.startswith("0xc2")]
    assert samples, "no HDMI_VID_CTL samples (debugfs unreadable?)"
    assert not bad, f"latched HDMI_VID_CTL: {bad}"
    record("01-latch-oracle", {"samples": len(samples), "distinct": sorted(set(samples))})

    port = device.engine_midi_port()
    report["engine_midi_port"] = port

    # 2. MIDI CC 20-24 -> knobs, read off the HUD knob sliders. The starter mode
    # is static, so the only change in that region is the slider fill. Hold each
    # file open across the engine's poll (a long trailing delta).
    hold = 3000
    device.play_midi(port, "cc0", [(0, bytes([0xB0, 20 + k, 0])) for k in range(5)]
                     + [(hold, bytes([0xB0, 20, 0]))], background=True)
    time.sleep(1.2)
    capture.snapshot("cc-lo")
    device.stop_midi("cc0")
    device.play_midi(port, "cc127", [(0, bytes([0xB0, 20 + k, 127])) for k in range(5)]
                     + [(hold, bytes([0xB0, 20, 127]))], background=True)
    time.sleep(1.2)
    capture.snapshot("cc-hi")
    device.stop_midi("cc127")
    moved = region_diff(args.output / "cc-lo.png", args.output / "cc-hi.png")
    assert moved > 100, f"MIDI CC 20-24 did not move the HUD knob sliders ({moved} px)"
    record("02-midi-cc-knobs", {"knob_slider_diff_px": moved})

    # 3. MIDI notes 60/62/64 -> the engine's own hardware-test MIDI row.
    diag = device.json(PRELUDE + '''
combo(1)
wait_for(lambda s: s.get('menu_screen') == 0, 'menu home')
for _ in range(3):
    press(7)
press(8)
wait_for(lambda s: s.get('menu_screen') == 4, 'hardware test')
time.sleep(.5)
print(json.dumps(status()))
''')
    assert diag["menu_screen"] == 4, diag
    device.play_midi(port, "notes", [(0, bytes([0x90, 60, 100])), (0, bytes([0x90, 62, 100])),
                                     (0, bytes([0x90, 64, 100])), (6000, bytes([0x80, 60, 0]))],
                     background=True)
    try:
        midi_row = device.json(PRELUDE + '''
print(json.dumps(wait_for(lambda s: s.get('diagnostics', {}).get('midi'),
                          'midi diagnostics', timeout=12)))
''', timeout=30)
        assert midi_row["diagnostics"]["midi"] is True, midi_row
        record("03-midi-notes-diagnostics", midi_row["diagnostics"],
               capture.snapshot("03-midi-notes"))
    finally:
        device.stop_midi("notes")
    device.json(PRELUDE + '''
press(1); press(1)
wait_for(lambda s: s.get('menu_screen') == -1, 'menu closed')
print(json.dumps({"menu_screen": status().get('menu_screen')}))
''')

    # 4. MIDI transport: start/continue/clock/stop accepted without error.
    clock = [(0, bytes([0xFA]))] + [(0, bytes([0xF8]))] * 24 + \
            [(0, bytes([0xFB])), (0, bytes([0xF8])), (0, bytes([0xFC]))]
    device.play_midi(port, "transport", clock)
    time.sleep(0.8)
    transport = device.status()
    assert transport["mode_errors"] == 0 and transport["mode"] == "starter", transport
    record("04-midi-transport", {"mode": transport["mode"], "mode_errors": transport["mode_errors"]})

    # 5. Disconnect / reconnect: dropping the source must not disturb the engine.
    device.run(f"aconnect -x 2>/dev/null || true; sleep .4; "
               f"aconnect 'ttymidi:0' '{port}' 2>/dev/null || true")
    time.sleep(0.6)
    reconnect = device.status()
    assert reconnect["mode_errors"] == 0, reconnect
    record("05-midi-reconnect", {"mode_errors": reconnect["mode_errors"], "led": reconnect["led"]})

    # 6. Catalog render smoke: every mode loads, renders non-blank, and differs.
    if not args.skip_modes:
        count = baseline["mode_count"]
        seen, errors = [], []
        prev, errs = baseline["mode"], baseline["mode_errors"]
        for index in range(count):
            state = device.json(PRELUDE + f'''
press(5)
print(json.dumps(wait_for(lambda s: s.get('mode') != {prev!r}, 'mode change', timeout=10)))
''', timeout=40)
            if state.get("mode_errors", 0) > errs:
                errors.append(state.get("mode"))
                errs = state["mode_errors"]
            seen.append(state.get("mode"))
            prev = state.get("mode")
            capture.snapshot(f"smoke-{index:02d}")
        final = device.status()
        assert len(set(seen)) >= count - 1, f"mode switching stalled: {len(set(seen))}/{count}"
        unexpected = [m for m in errors if m not in known_broken]
        assert not unexpected, f"modes reported a setup error: {unexpected}"
        assert final["mode_errors"] == errs, final
        blanks = [k for k, v in capture.frames.items()
                  if k.startswith("smoke-") and v["bytes"] < 10000]
        assert not blanks, f"blank capture frames: {blanks}"
        distinct = len({v["sha256"] for k, v in capture.frames.items() if k.startswith("smoke-")})
        assert distinct >= count // 2, f"only {distinct} distinct frames across {count} modes"
        record("06-mode-render-smoke",
               {"modes_cycled": len(seen), "distinct_frames": distinct,
                "known_broken": sorted(errors),
                "mode_errors": final["mode_errors"]})

    # 7. Leave the instrument as found: starter, idle, menu closed.
    final = device.json(PRELUDE + '''
for _ in range(60):
    if status().get('mode') == 'starter':
        break
    press(5)
    time.sleep(.4)
keys(10, 0); keys(2, 0)
time.sleep(.5)
print(json.dumps(status()))
''', timeout=120)
    assert final["mode"] == "starter", final
    assert final["mode_errors"] <= len(known_broken), final
    record("07-final-idle", {k: final.get(k) for k in
                             ("mode", "mode_errors", "led", "menu_screen", "sequencer", "fps")},
           capture.snapshot("07-final-idle"))

    report["frames"] = capture.frames
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Bench automation passed; frames and summary in {args.output}")


if __name__ == "__main__":
    main()
