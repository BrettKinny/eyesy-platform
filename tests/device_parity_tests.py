#!/usr/bin/env python3
"""End-to-end parity checks against a live EYESY platform unit.

Drives the *deployed* engine over OSC from the device itself, reads its
`status.json`, inspects scene/config files, watches the hardware LED socket, and
snapshots the HDMI capture stream at every step.

Requirements:
  * ssh access as `music@<host>` with passwordless sudo (used to bounce
    `eyesyhw` for the LED phase),
  * an HDMI->USB capture streamer already writing a rolling PNG (~2 fps). The
    dongle asserts HDMI HPD only while its UVC pipeline streams, so the streamer
    MUST stay up for the whole run: if it stops, the kernel drops EDID and the
    instrument's output goes black (uniform 0,0,0 frames).

Usage:
    tests/device_parity_tests.py --host <device-ip> \
        --frames local/hdmi/latest.png --output local/reports/device-parity-<label>
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE_PORT = 4000
LED_PORT = 4001
STORE = '/sdcard/eyesy-platform'

# Shared device-side helpers: OSC senders plus a status reader. Each step script
# appends its own actions and prints a JSON result.
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


def wait_for(predicate, label, timeout=5):
    end = time.monotonic() + timeout
    state = {}
    while time.monotonic() < end:
        state = status()
        if predicate(state):
            return state
        time.sleep(.15)
    raise SystemExit('unmet: %s %s' % (label, json.dumps(state)))
'''


class Device:
    def __init__(self, host, known_hosts):
        self.host = host
        options = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                   '-o', 'StrictHostKeyChecking=yes']
        if known_hosts:
            options += ['-o', f'UserKnownHostsFile={known_hosts}']
        self.ssh = ['ssh'] + options + [f'music@{host}']
        self.scp = ['scp'] + options

    def run(self, remote):
        result = subprocess.run(self.ssh + [remote], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=120)
        if result.returncode != 0:
            raise AssertionError(f'remote command failed: {remote}\n{result.stdout}')
        return result.stdout

    def python(self, script, timeout=180):
        result = subprocess.run(self.ssh + ['python3', '-'], input=script,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout)
        if result.returncode != 0:
            raise AssertionError(f'remote python failed:\n{result.stdout}')
        return result.stdout

    def json(self, script, timeout=180):
        return json.loads(self.python(script, timeout).strip().splitlines()[-1])

    def status(self):
        return json.loads(self.run(f'cat {STORE}/status.json'))

    def wait(self, predicate, label, timeout=6):
        end = time.monotonic() + timeout
        state = {}
        while time.monotonic() < end:
            state = self.status()
            if predicate(state):
                return state
            time.sleep(.2)
        raise AssertionError(f'{label} not reached: {json.dumps(state)}')

    def scenes(self):
        listing = self.run(f'ls -1 {STORE}/scenes 2>/dev/null || true')
        return sorted(name for name in listing.split() if name.endswith('.json'))

    def read_scene(self, name):
        return json.loads(self.run(f'cat {STORE}/scenes/{name}'))

    def config(self):
        return json.loads(self.run(f'cat {STORE}/config.json'))


class Capture:
    """Rolling HDMI capture frame reader; the streamer owns the device."""

    def __init__(self, path, output):
        self.path = pathlib.Path(path)
        self.output = output
        self.frames = {}

    def alive(self):
        if not self.path.is_file():
            raise AssertionError(f'capture file missing: {self.path}')
        # A fully black frame (no TMDS) compresses to ~4 KB; live content is
        # tens of KB. This also proves the streamer is still running.
        if self.path.stat().st_size < 10000:
            raise AssertionError('capture stream looks blank; is the streamer up?')
        return True

    def snapshot(self, label):
        self.alive()
        for _ in range(20):
            data = self.path.read_bytes()
            if data.startswith(b'\x89PNG\r\n\x1a\n') and data.endswith(b'IEND\xaeB`\x82'):
                break
            time.sleep(.1)          # the streamer rewrites in place
        else:
            raise AssertionError(f'{label}: capture frame never settled')
        target = self.output / f'{label}.png'
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.frames[label] = digest
        return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--frames', type=pathlib.Path, default=ROOT / 'local/hdmi/latest.png')
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--known-hosts', type=pathlib.Path,
                        default=ROOT / 'local/eyesy_known_hosts')
    args = parser.parse_args()
    if args.output.exists():
        sys.exit('--output must not already exist')
    args.output.mkdir(parents=True)
    known_hosts = args.known_hosts if args.known_hosts.is_file() else None
    device = Device(args.host, known_hosts)
    capture = Capture(args.frames, args.output)
    report = {'host': args.host, 'steps': {}}

    def record(step, state, frame=None):
        report['steps'][step] = {
            'status': {k: state.get(k) for k in
                       ('release', 'mode', 'fps', 'mode_errors', 'synthesizing',
                        'audio_synthesizing', 'led', 'sequencer', 'sequencer_frames',
                        'menu_screen', 'menu_row', 'diagnostics', 'fg_palette',
                        'bg_palette', 'palette_count', 'video_mode', 'hud_draw_calls')},
            'frame': frame,
        }
        print(f'{step}: {report["steps"][step]["status"]}')

    # 0. Baseline: the released instrument must be idle and rendering.
    baseline = device.wait(
        lambda s: s.get('mode') == 'starter' and s.get('menu_screen') == -1
        and s.get('sequencer') == 'stopped' and s.get('fps', 0) > 40, 'idle baseline')
    assert baseline['mode_errors'] == 0, baseline
    assert baseline['hud_draw_calls'] == 9, baseline
    assert baseline['led'] == 7, baseline
    print(f"  release: {baseline['release']}  renderer: {baseline['renderer']}")
    record('01-idle', baseline, capture.snapshot('01-idle'))

    # 1. Trigger button: the engine replaces the input with the undulating tone.
    tone = device.json(PRELUDE + '''
keys(10)                       # hold the trigger
state = wait_for(lambda s: s.get('audio_synthesizing') and s.get('audio_rms_left', 0) > .3,
                 'trigger tone')
keys(10, 0)
print(json.dumps(state))
''')
    assert tone['audio_synthesizing'] is True and tone['audio_rms_left'] > .3, tone
    assert abs(tone['audio_rms_left'] - tone['audio_rms_right']) < 1e-6, 'tone must be mono'
    record('02-trigger-tone', tone, capture.snapshot('02-trigger-tone'))
    released = device.wait(lambda s: not s.get('audio_synthesizing'), 'tone release')

    # 2. Sequencer: arm, record from a knob move, then play.
    recording = device.json(PRELUDE + '''
combo(10)                      # Shift + Trigger arms
knobs([500, 500, 900, 500, 500])
state = wait_for(lambda s: s.get('sequencer') == 'recording', 'recording')
for value in (700, 400, 800, 300, 600, 350):
    knobs([500, 500, value, 500, 500])
    time.sleep(.1)
print(json.dumps(wait_for(lambda s: s.get('sequencer_frames', 0) > 3, 'frames')))
''')
    assert recording['led'] == 1, recording
    recorded_frames = recording['sequencer_frames']
    record('03-recording', recording, capture.snapshot('03-recording'))

    playing = device.json(PRELUDE + '''
combo(9)                       # Shift + Screenshot plays
print(json.dumps(wait_for(lambda s: s.get('sequencer') == 'playing', 'playing')))
''')
    assert playing['led'] == 3, playing
    assert playing['sequencer_frames'] >= recorded_frames, playing
    record('04-playing', playing, capture.snapshot('04-playing'))

    # 3. Saving while playing stores the sequence with the scene.
    before_save = device.scenes()
    saved_state = device.json(PRELUDE + '''
press(8)                       # quick press: saves on release
state = wait_for(lambda s: s.get('sequencer') == 'playing' and s.get('sequencer_frames', 0) > 3,
                 'sequence still playing')
print(json.dumps(state))
''')
    after_save = device.scenes()
    created = [name for name in after_save if name not in before_save]
    assert created, (before_save, after_save)
    scene_name = created[-1]
    scene = device.read_scene(scene_name)
    assert scene['mode'] == 'starter', scene
    assert scene['knob_sequence'] and len(scene['knob_sequence']) > 3, scene.keys()
    assert isinstance(scene['auto_clear'], bool) and 'fg_palette' in scene, scene.keys()
    assert saved_state['sequencer'] == 'playing', saved_state
    report['scene'] = {'name': scene_name, 'sequence_frames': len(scene['knob_sequence'])}
    record('05-save-with-sequence', saved_state)

    # 4. Recall restores the running sequence.
    recalled = device.json(PRELUDE + '''
combo(9)                       # stop playback
wait_for(lambda s: s.get('sequencer') == 'stopped', 'stopped')
press(6); press(7)             # step away and back onto the saved scene
print(json.dumps(wait_for(lambda s: s.get('sequencer') == 'playing', 'sequence restored')))
''')
    assert recalled['sequencer'] == 'playing', recalled
    record('06-recall-restores-sequence', recalled)

    # 5. Shift + Save updates in place; a stopped sequence is dropped.
    update = device.json(PRELUDE + '''
combo(9)                       # stop playback
wait_for(lambda s: s.get('sequencer') == 'stopped', 'stopped')
before = status().get('auto_clear')
press(3)                       # toggle persist
toggled = wait_for(lambda s: s.get('auto_clear') != before, 'persist toggle')
combo(8)                       # Shift + Save updates the loaded scene
time.sleep(.5)
print(json.dumps({'before': before, 'after': toggled.get('auto_clear')}))
''')
    assert update['before'] != update['after'], update
    updated = device.read_scene(scene_name)
    assert updated['auto_clear'] == update['after'], (updated['auto_clear'], update)
    assert 'knob_sequence' not in updated, 'stopped sequence must be dropped on update'
    assert device.config()['schema_version'] == 1
    record('07-update-in-place', device.status())

    # 6. Hold Save deletes the loaded scene, then recalls the slot it left.
    deleted = device.json(PRELUDE + '''
keys(8)
time.sleep(1.6)                # past the 1 s delete window
keys(8, 0)
time.sleep(.6)
print(json.dumps(status()))
''')
    remaining = device.scenes()
    assert scene_name not in remaining, (scene_name, remaining)
    # The deleted slot recalls its neighbour; playback must follow that scene's
    # own contents. (This bench unit's button matrix can emit spurious key-8
    # transitions, each pair saving a scene, so the file count is not asserted.)
    loaded = device.wait(lambda s: s.get('scene') != scene_name, 'slot recalled after delete')
    assert loaded['scene_index'] < loaded['scene_count'] or loaded['scene_count'] == 0, loaded
    if loaded['scene']:
        target = device.read_scene(f"{loaded['scene']}.json")
        assert (loaded['sequencer'] == 'playing') == bool(target.get('knob_sequence')), (
            loaded['sequencer'], target.keys())
    else:
        assert loaded['sequencer'] == 'stopped', loaded
    record('08-hold-save-deletes', deleted)

    # 7. Palette cycling on Shift + Mode/Scene.
    palettes = device.json(PRELUDE + '''
start = status()
count = start['palette_count']
combo(4)
prev_fg = wait_for(lambda s: s['fg_palette'] == (start['fg_palette'] - 1) % count, 'prev fg')
combo(5)
wait_for(lambda s: s['fg_palette'] == start['fg_palette'], 'next fg')
combo(7)
next_bg = wait_for(lambda s: s['bg_palette'] == (start['bg_palette'] + 1) % count, 'next bg')
combo(6)
wait_for(lambda s: s['bg_palette'] == start['bg_palette'], 'prev bg')
print(json.dumps({'start': start, 'prev_fg': prev_fg, 'next_bg': next_bg,
                  'end': status()}))
''')
    assert palettes['start']['palette_count'] > 10, palettes
    assert palettes['end']['fg_palette'] == palettes['start']['fg_palette'], palettes
    assert palettes['end']['bg_palette'] == palettes['start']['bg_palette'], palettes
    record('09-palette-cycling', palettes['prev_fg'])

    # 8. Configuration menu: every sub-screen, live diagnostics, persistence.
    menu = device.json(PRELUDE + '''
combo(1)                       # Shift + OSD opens the menu
wait_for(lambda s: s.get('menu_screen') == 0, 'menu home')
screens = {}
for index, row in enumerate((0, 1, 2, 3)):
    if row:
        for _ in range(row):
            press(7)
    press(8)                   # enter the sub-screen
    screens[row] = wait_for(lambda s: s.get('menu_screen') == row + 1,
                            'screen %d' % (row + 1))['menu_screen']
    press(1)                   # back to the home list
    wait_for(lambda s: s.get('menu_screen') == 0, 'home')
# Video screen: pick a mode, then put it back to Auto (leave no preference).
press(8); wait_for(lambda s: s.get('menu_screen') == 1, 'video')
press(7); press(8)
press(1); press(1)             # home, exit
wait_for(lambda s: s.get('menu_screen') == -1, 'menu closed')
print(json.dumps({'screens': screens, 'config': json.load(open(STORE + '/config.json'))}))
''')
    assert menu['screens'] == {'0': 1, '1': 2, '2': 3, '3': 4}, menu
    assert menu['config']['video_mode'] == '1280x720@60', menu['config']
    record('10-menu-screens', device.status())

    diagnostics = device.json(PRELUDE + '''
combo(1)
wait_for(lambda s: s.get('menu_screen') == 0, 'menu home')
for _ in range(3):
    press(7)
press(8)                       # Hardware test
wait_for(lambda s: s.get('menu_screen') == 4, 'test screen')
time.sleep(.5)                 # let the rows arm against live hardware
knobs([900, 150, 500, 500, 500])
time.sleep(.3)
knobs([900, 150, 800, 500, 500])
for _ in range(3):
    press(3)                   # three button presses
state = wait_for(lambda s: s.get('diagnostics', {}).get('pots')
                 and s['diagnostics'].get('buttons'), 'diagnostics', timeout=8)
keys(10)                       # synthesised tone drives the audio row
state = wait_for(lambda s: s['diagnostics'].get('audio'), 'audio row', timeout=6)
keys(10, 0)
press(1); press(1)             # home, exit
wait_for(lambda s: s.get('menu_screen') == -1, 'menu closed')
print(json.dumps(state))
''')
    assert diagnostics['diagnostics']['pots'], diagnostics
    assert diagnostics['diagnostics']['buttons'], diagnostics
    assert diagnostics['diagnostics']['audio'], diagnostics
    # No MIDI source is attached to the bench unit; the row must stay honest.
    assert diagnostics['diagnostics']['midi'] is False, diagnostics
    record('11-hardware-test', diagnostics, capture.snapshot('11-hardware-test'))

    # Leave the video preference as found (Auto follows the EDID).
    restored = device.json(PRELUDE + '''
combo(1)
wait_for(lambda s: s.get('menu_screen') == 0, 'menu home')
press(8)                       # Video screen
press(8)                       # first row is Auto (EDID)
press(1); press(1)
wait_for(lambda s: s.get('menu_screen') == -1, 'menu closed')
print(json.dumps(json.load(open(STORE + '/config.json'))))
''')
    assert restored['video_mode'] == '', restored
    report['config'] = restored

    # 9. LED protocol on the daemon's own port (eyesyhw is bounced to free it).
    led = device.json(PRELUDE + '''
import subprocess

run = lambda args: subprocess.run(args, check=False, capture_output=True)
run(['sudo', '-n', 'systemctl', 'stop', 'eyesyhw'])
try:
    watch = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    watch.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    watch.bind(('127.0.0.1', 4001))
    watch.settimeout(.05)
    codes = []

    def drain(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data, _ = watch.recvfrom(1024)
            except socket.timeout:
                continue
            if data.startswith(b'/led') and len(data) >= 16:
                codes.append(struct.unpack('>i', data[-4:])[0])

    drain(.5)
    combo(10)                  # armed
    drain(.5)
    knobs([500, 500, 900, 500, 500])
    drain(.5)
    for value in (700, 400, 800, 300):
        knobs([500, 500, value, 500, 500])
        time.sleep(.1)
    drain(.5)
    combo(9)                   # playing
    drain(.5)
    combo(9)                   # stopped
    drain(1.0)
    print(json.dumps({'codes': codes, 'final': status().get('led')}))
finally:
    run(['sudo', '-n', 'systemctl', 'start', 'eyesyhw'])
''')
    first = {}
    for index, code in enumerate(led['codes']):
        first.setdefault(code, index)
    assert all(code in first for code in (6, 1, 3, 7)), led
    ordered = [first[code] for code in (6, 1, 3, 7)]
    assert ordered == sorted(ordered), led
    assert led['final'] == 7, led
    report['led_codes'] = led['codes']
    daemon = device.run('systemctl is-active eyesyhw').strip()
    assert daemon == 'active', f'eyesyhw left down: {daemon}'
    record('12-led-protocol', device.status())

    # 10. Frames must differ between states (the capture is genuinely live).
    idle, recording_frame = capture.frames['01-idle'], capture.frames['03-recording']
    assert idle != recording_frame, 'capture frames do not track engine state'
    assert capture.frames['03-recording'] != capture.frames['04-playing'], 'sequencer states look alike'

    # 11. Idle again, with the instrument left as found.
    final = device.json(PRELUDE + '''
for _ in range(4):
    if status().get('sequencer') == 'stopped':
        break
    combo(9)
keys(10, 0); keys(2, 0)
time.sleep(.5)
print(json.dumps(status()))
''')
    assert final['sequencer'] == 'stopped', final
    assert final['menu_screen'] == -1, final
    assert final['led'] == 7 and final['mode_errors'] == 0, final
    record('13-final-idle', final, capture.snapshot('13-final-idle'))

    report['frames'] = capture.frames
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Device parity checks passed; frames and summary in {args.output}')


if __name__ == '__main__':
    main()
