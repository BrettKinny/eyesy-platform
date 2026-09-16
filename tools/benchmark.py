#!/usr/bin/env python3
"""Bounded renderer experiments. Run under a real display or xvfb-run explicitly.

Renderer identity is recorded; software-rendered measurements are never labelled
as target GPU performance. Each run gets isolated persistent evidence/storage.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def memory_summary(samples, warmup):
    retained = [s for s in samples if s['elapsed'] >= warmup]
    if len(retained) < 6:
        return {'qualified': False, 'reason': 'fewer than six post-warmup samples'}
    width = max(1, len(retained) // 5)
    first = statistics.median(s['rss_bytes'] for s in retained[:width])
    last = statistics.median(s['rss_bytes'] for s in retained[-width:])
    return {'qualified': True, 'samples': len(retained),
            'first_window_median_bytes': first, 'last_window_median_bytes': last,
            'delta_bytes': last - first,
            'peak_bytes': max(s['rss_bytes'] for s in retained)}


def temperature_c():
    """Optional local SoC reading; never confuse missing telemetry with zero."""
    try:
        value = float(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
        return value if math.isfinite(value) and -20 <= value <= 150 else None
    except (OSError, ValueError):
        return None


def select_modes(root, names=None):
    """Resolve mode selection without silently dropping explicit names."""
    root = root.resolve()
    if names:
        modes = [(root / name).resolve() for name in names]
        missing = [name for name, mode in zip(names, modes)
                   if not mode.is_relative_to(root) or not (mode / 'main.lua').is_file()]
        if missing:
            raise ValueError('Missing selected mode(s): ' + ', '.join(missing))
    else:
        modes = [p.resolve() for p in sorted(root.iterdir()) if (p / 'main.lua').is_file()]
    modes = [p for p in modes if (p / 'main.lua').is_file()]
    if not modes or any(not p.is_relative_to(root) for p in modes):
        raise ValueError('Select existing modes inside modes-root')
    return modes


def mode_files(root, modes, include_catalog=False):
    root = root.resolve()
    # The engine discovers siblings of each initial mode, even when callers
    # select a nested path inside modes-root.
    selected = sorted({mode for parent in {p.parent for p in modes}
                       for mode in select_modes(parent)}) if include_catalog else modes
    files = [p for mode in selected for p in sorted(mode.rglob('*')) if p.is_file()]
    if any(not p.resolve().is_relative_to(root) for p in files):
        raise ValueError('Mode file resolves outside modes-root')
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def sample_failed(status):
    return bool(status.get('error') or status.get('shader_warning') or
                status.get('mode_errors', 0) > 0)


def experiment(engine, mode, folder, frames, switch_every, timeout, warmup, offscreen=False, require_gpu=False, replay=None):
    folder.mkdir(parents=True, exist_ok=False)
    report = folder / 'report.json'
    command = [str(engine), '--mode', str(mode), '--storage', str(folder),
               '--frames', str(frames), '--switch-every', str(switch_every),
               '--report', str(report)]
    if replay is not None: command += ['--replay', str(replay)]
    if offscreen: command.append('--offscreen')
    started = time.monotonic()
    samples, last_frame = [], -1
    timed_out = False
    with (folder / 'engine.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > timeout:
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    break
                try:
                    status = json.loads((folder / 'status.json').read_text())
                    if status['frame'] != last_frame:
                        last_frame = status['frame']
                        samples.append({'elapsed': elapsed, **status,
                                        'temperature_c': temperature_c()})
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(.25)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    final = json.loads(report.read_text()) if report.exists() else {}
    renderer = final.get('renderer', '')
    software = any(s in renderer.lower() for s in ('llvmpipe', 'softpipe', 'swrast'))
    sampled_failure = any(sample_failed(sample) for sample in samples)
    passed = (process.returncode == 0 and not timed_out and bool(renderer)
              and final.get('frame', 0) >= frames and not final.get('error')
              and not final.get('shader_warning') and final.get('mode_errors', 0) == 0
              and not sampled_failure)
    if require_gpu and software: passed = False
    result = {'mode': mode.name, 'command': command, 'returncode': process.returncode,
              'timed_out': timed_out, 'wall_seconds': time.monotonic() - started,
              'passed': passed, 'renderer': renderer, 'software_renderer': software,
              'hardware_acceptance': False, 'final': final,
            'memory': memory_summary(samples, warmup), 'samples': samples}
    temperatures = [s['temperature_c'] for s in samples if s.get('temperature_c') is not None]
    result['temperature_peak_c'] = max(temperatures) if temperatures else None
    (folder / 'experiment.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, default=ROOT / 'engine/bin/engine')
    parser.add_argument('--modes-root', type=Path, default=ROOT / 'modes')
    parser.add_argument('--modes', nargs='*', help='Default: all modes')
    parser.add_argument('--output', type=Path, required=True, help='New evidence directory')
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--switch-every', type=int, default=0)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--replay', type=Path, help='Optional engine input replay (JSON) passed to each run')
    parser.add_argument('--warmup', type=float, default=3)
    parser.add_argument('--offscreen', action='store_true', help='ARM EGL pbuffer backend, no X server')
    parser.add_argument('--require-gpu', action='store_true', help='Fail software renderer experiments')
    args = parser.parse_args()
    if (args.frames <= 0 or args.switch_every < 0 or args.timeout <= 0
            or not math.isfinite(args.timeout) or not math.isfinite(args.warmup)
            or args.warmup < 0):
        parser.error('Use positive frames/timeout and nonnegative switch interval/warmup')
    root = args.modes_root.resolve()
    try:
        modes = select_modes(root, args.modes)
    except ValueError as error:
        parser.error(str(error))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runs = []
    for i, mode in enumerate(modes):
        result = experiment(args.engine.resolve(), mode, output / f'{i:02d}-{mode.name}',
                            args.frames, args.switch_every, args.timeout, args.warmup,
                            args.offscreen, args.require_gpu, args.replay)
        runs.append(result)
        print(json.dumps({k: result[k] for k in
                          ('mode', 'passed', 'renderer', 'wall_seconds', 'memory')}), flush=True)
    summary = {'schema_version': 1, 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'engine_sha256': hashlib.sha256(args.engine.read_bytes()).hexdigest(),
               'mode_files': mode_files(root, modes, args.switch_every > 0),
               'display': os.environ.get('DISPLAY'), 'hardware_acceptance': False,
               'passed': all(r['passed'] for r in runs),
               'runs': [{k: v for k, v in r.items() if k != 'samples'} for r in runs]}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
