#!/usr/bin/env python3
"""Run one verified ARM release mode on a prepared clone, offscreen only."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import uuid
import sys
from tools import release

ROOT = Path(__file__).resolve().parents[1]
SAFE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')

def run(args, **kwargs): return subprocess.run([str(x) for x in args], check=True, **kwargs)

def execute(archive, host, clone_id, mode, frames, output, ssh_options=None):
    manifest = release.verify(archive, 'armhf')
    if not SAFE.fullmatch(mode): raise ValueError('Mode must be a safe basename')
    if frames < 1 or frames > 3600: raise ValueError('Frames must be 1..3600')
    if not isinstance(manifest.get('files'), dict) or f'modes/{mode}/main.lua' not in manifest['files']:
        raise ValueError('Archive does not contain the selected mode')
    output = Path(output)
    if output.is_symlink(): raise ValueError('Output directory must not be a symlink')
    output = output.resolve()
    if output.exists(): raise ValueError('Output directory already exists')
    options = ssh_options or ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=yes']
    common = ['-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3']
    ssh = ['ssh'] + options + common + [f'music@{host}']; scp = ['scp'] + options + common
    marker = subprocess.check_output(ssh + ['cat /etc/eyesy-development-clone'], text=True, timeout=15)
    if json.loads(marker).get('clone_id') != clone_id: raise RuntimeError('Remote clone identity mismatch')
    model = subprocess.check_output(ssh + ['cat /proc/device-tree/model'], text=True, timeout=15)
    if 'Compute Module 3 Plus' not in model: raise RuntimeError('Remote board model mismatch')
    staging = subprocess.check_output(ssh + ['mktemp -d /tmp/eyesy-headless.XXXXXXXX'], text=True, timeout=15).strip()
    if not re.fullmatch(r'/tmp/eyesy-headless\.[A-Za-z0-9]+', staging): raise RuntimeError('Unexpected staging path')
    try:
        run(scp + [str(archive), f'music@{host}:{staging}/release.tar.gz'], timeout=120)
        run(scp + [str(ROOT / 'tools/release.py'), str(ROOT / 'tools/benchmark.py'), f'music@{host}:{staging}/'], timeout=120)
        root = manifest['release']; remote_release = f'{staging}/release'
        run(ssh + [shlex.join(['python3', staging+'/release.py', staging+'/release.tar.gz', '--architecture', 'armhf'])], timeout=120)
        run(ssh + ['mkdir ' + shlex.quote(remote_release) + ' && tar -xzf ' + shlex.quote(staging+'/release.tar.gz') + ' -C ' + shlex.quote(remote_release) + ' --strip-components=1'], timeout=120)
        experiment = f'/sdcard/eyesy-platform/experiments/headless-{uuid.uuid4().hex}'
        command = ['python3', staging+'/benchmark.py', '--engine', remote_release+'/eyesy-engine', '--modes-root', remote_release+'/modes', '--modes', mode, '--output', experiment, '--frames', str(frames), '--timeout', '120', '--offscreen', '--require-gpu']
        benchmark_error = None
        try:
            run(ssh + [shlex.join(command)], timeout=150)
        except Exception as exc:
            benchmark_error = exc
        output.mkdir(parents=True)
        try:
            run(scp + ['-r', f'music@{host}:{experiment}', str(output)], timeout=120)
        except Exception:
            if benchmark_error is not None: raise benchmark_error
            raise
        if benchmark_error is not None: raise benchmark_error
        return {'output': str(output), 'experiment': experiment, 'release': root, 'staging': staging}
    except Exception:
        print(f'Remote staging retained for inspection: {staging}', file=sys.stderr)
        raise
