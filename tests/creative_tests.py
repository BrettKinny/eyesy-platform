#!/usr/bin/env python3
"""Renderer integration checks for palette registration and creative modes."""
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path('/workspace')
ENGINE = ROOT / 'engine/bin/engine'

def run(mode, storage, frames=4, expected=0):
    report = storage / 'report.json'
    command = ['xvfb-run', '-a', '-s', '-screen 0 1280x720x24', str(ENGINE),
               '--mode', str(mode), '--storage', str(storage), '--frames', str(frames),
               '--report', str(report)]
    result = subprocess.run(command, timeout=25, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    if result.returncode != expected:
        raise AssertionError(f'{mode}: expected {expected}, got {result.returncode}\n{result.stdout}')
    return json.loads(report.read_text())

def mode(folder, body):
    folder.mkdir(parents=True)
    (folder / 'main.lua').write_text(body)

def assert_error(root, temp, name, body, text):
    path = root / name
    mode(path, body)
    report = run(path, temp / name, expected=2)
    assert text in report['error'], (text, report['error'])

def main():
    with tempfile.TemporaryDirectory(prefix='eyesy-creative-') as scratch:
        scratch = Path(scratch)
        valid = scratch / 'valid'
        mode(valid, '''
local e = eyesy
return {api_version=1,
  setup=function(ctx)
    e.define_palette("test", {{0,0.2,1}, {1,0.4,0}})
  end,
  draw=function(ctx)
    local r,g,b=e.palette("test", 1.5)
    local cr,cg,cb=e.palette(0.25)
    if math.abs(r-0.5)>0.001 or math.abs(g-0.3)>0.001 or math.abs(b-0.5)>0.001 then error("palette interpolation") end
    if cr<0 or cg<0 or cb<0 or cr>1 or cg>1 or cb>1 then error("cosine palette range") end
  end}
''')
        report = run(valid, scratch / 'valid')
        assert not report['error'] and report['mode_errors'] == 0

        invalid = '''return {api_version=1,setup=function(ctx) %s end,draw=function() end}'''
        assert_error(scratch, scratch, 'unknown',
                     invalid % 'eyesy.palette("missing", 0)', 'unknown palette')
        assert_error(scratch, scratch, 'too-few',
                     invalid % 'eyesy.define_palette("x", {{1,0,0}})', '2..16')
        assert_error(scratch, scratch, 'too-many-stops',
                     invalid % 'eyesy.define_palette("x", {{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0},{1,0,0}})', '2..16')
        assert_error(scratch, scratch, 'bad-stop',
                     invalid % 'eyesy.define_palette("x", {{1,0},{0.5,0.5,0.5}})', 'RGB triples')
        assert_error(scratch, scratch, 'nan',
                     invalid % 'eyesy.define_palette("x", {{0/0,0,0},{1,1,1}})', 'nonfinite')
        assert_error(scratch, scratch, 'inf',
                     invalid % 'eyesy.define_palette("x", {{math.huge,0,0},{1,1,1}})', 'nonfinite')

        cap = ('local e=eyesy; return {api_version=1, setup=function() ' +
               ''.join('e.define_palette("p%d", {{0,0,0},{1,1,1}});' % i
                       for i in range(29)) + ' end, draw=function() end}')
        assert_error(scratch, scratch, 'palette-cap', cap, 'palette budget')
        targets = ('local e=eyesy; return {api_version=1, setup=function() ' +
                   'e.target(1280,720);' * 9 + ' end, draw=function() end}')
        assert_error(scratch, scratch, 'target-cap', targets, 'target exceeds')

        for name in ('aurora', 'prism-mesh', 'echo-feedback'):
            report = run(ROOT / 'modes' / name, scratch / ('mode-' + name), frames=8)
            assert not report['error'] and report['mode_errors'] == 0, report
            assert report['resources'] <= 4, report['resources']
    print('Creative tests passed: palette interpolation, compatibility, validation, cap, and modes')

if __name__ == '__main__':
    main()
