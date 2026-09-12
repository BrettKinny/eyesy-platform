#!/usr/bin/env python3
"""Integration checks against the compiled renderer; run inside the build container."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path('/workspace')
ENGINE = ROOT / 'engine/bin/engine'

def run(mode, storage, frames=60, replay=None, expected=0):
    report = storage / 'report.json'
    command = ['xvfb-run', '-a', '-s', '-screen 0 1280x720x24', str(ENGINE), '--mode', str(mode),
               '--storage', str(storage), '--frames', str(frames), '--report', str(report)]
    if replay: command += ['--replay', str(replay)]
    result = subprocess.run(command, timeout=25, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != expected:
        raise AssertionError(f'{mode}: expected {expected}, got {result.returncode}\n{result.stdout}')
    return json.loads(report.read_text())

def main():
    with tempfile.TemporaryDirectory(prefix='eyesy-graphics-') as temp:
        temp = Path(temp)
        broken = temp / 'modes/broken'; broken.mkdir(parents=True)
        (broken / 'main.lua').write_text('return {api_version=1,draw=function(ctx) error("intentional draw failure") end}')
        result = run(broken, temp / 'broken', expected=2)
        assert 'intentional draw failure' in result['error']
        assert result['mode_errors'] == 1
        (broken / 'main.lua').write_text('this is not lua!')
        result = run(broken, temp / 'syntax', expected=2)
        assert result['error']
        (broken / 'main.lua').write_text('return {api_version=99,draw=function() end}')
        result = run(broken, temp / 'version', expected=2)
        assert 'api_version' in result['error']
        (broken / 'main.lua').write_text('return {api_version=1,draw=function() eyesy.pop() end}')
        result = run(broken, temp / 'underflow', expected=2)
        assert 'underflow' in result['error']
        hashes = []
        for iteration in range(2):
            storage = temp / f'replay-{iteration}'
            result = run(ROOT / 'modes/starter', storage, replay=ROOT / 'tests/fixtures/replay.json')
            assert not result['error'] and result['mode_errors'] == 0
            scenes = list((storage / 'scenes').glob('*.json'))
            assert len(scenes) == 1
            scene = json.loads(scenes[0].read_text())
            assert abs(scene['parameters']['size'] - 0.2875) < 1e-6
            image = next((storage / 'grabs').glob('*.png'))
            hashes.append(hashlib.sha256(image.read_bytes()).hexdigest())
        assert hashes[0] == hashes[1], 'replayed images differ'
        print('Graphics tests passed: Lua errors, syntax, API versions, matrix cleanup, scenes, deterministic images')

if __name__ == '__main__': main()
