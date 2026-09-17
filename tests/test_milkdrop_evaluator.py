#!/usr/bin/env python3
"""Evaluator tests: modes/milkdrop/lib/evaluator.lua (+ the seed presets).

Every case drives the real Lua module in a subprocess (luajit / lua5.1 / lua),
prints ``key<TAB>value`` rows, and is asserted here against values computed in
Python -- an independent implementation of the arithmetic -- rather than
against the evaluator itself.

Run directly (python3 tests/test_milkdrop_evaluator.py) or via unittest/pytest.
"""
import math
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import mode_packs  # noqa: E402  (importable only once ROOT is known)

MILKDROP = mode_packs.find('milkdrop')


def _find_lua():
    for name in ('luajit', 'lua5.1', 'lua5.3', 'lua'):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


LUA = _find_lua()


class Raw(str):
    """A Lua expression embedded verbatim (e.g. ``make_rand(7)``, ``0/0``)."""


def lua_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def lua_value(v):
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return lua_str(v)
    raise TypeError('cannot embed %r into Lua source' % (v,))


def lua_env(env):
    if not env:
        return '{}'
    fields = ['%s = %s' % (k, lua_value(v)) for k, v in env.items()]
    return '{ ' + ', '.join(fields) + ' }'


PRELUDE = '''\
package.path = __MILKDROP__ .. "/?.lua;" .. package.path
local ev = require("lib.evaluator")

-- Park-Miller LCG mirroring the Python lcg() helper: reproducible [0,1).
local function make_rand(seed)
  local s = seed % 2147483647
  if s <= 0 then s = s + 2147483646 end
  return function()
    s = (s * 16807) % 2147483647
    return s / 2147483647
  end
end

local function fmt(v)
  if type(v) ~= "number" then return "!" .. type(v) end
  if v ~= v then return "!nan" end
  if v == math.huge or v == -math.huge then return "!inf" end
  return string.format("%.17g", v)
end

local function rad_of(x, y)
  local dx, dy = x - 0.5, y - 0.5
  return math.sqrt(dx * dx + dy * dy)
end

local atan2 = math.atan2 or math.atan
local function ang_of(x, y)
  return atan2(y - 0.5, x - 0.5)
end

local function compile_ok(code)
  local f, err = ev.compile(code)
  if not f then error(tostring(err)) end
  return f
end
'''.replace('__MILKDROP__', lua_str(str(MILKDROP)))


RUN_ONE = '''\
local function main()
  local f, err = ev.compile(__CODE__)
  if not f then print("status\terror"); print("message\t" .. tostring(err)); return end
  if type(f) ~= "function" then print("status\tnot-a-function"); return end
  local env = __ENV__
  local r, rerr = f(env)
  if not r then print("status\truntime"); print("message\t" .. tostring(rerr)); return end
  print("status\tok")
  for k, v in pairs(r) do print("v\t" .. k .. "\t" .. fmt(v)) end
end
main()
'''

POINTS = '''\
local function main()
  local f, err = ev.compile(__CODE__)
  if not f then print("status\terror"); print("message\t" .. tostring(err)); return end
  local pts = __PTS__
  local written = { "d", "r2", "a2", "m", "q" }
  for i = 1, #pts do
    local x_before = pts[i].x
    local r, rerr = f(pts[i])
    if not r then print("status\truntime"); print("message\t" .. tostring(rerr)); return end
    if pts[i].x ~= x_before then print("mutated\t" .. i .. "\tx") end
    for _, name in ipairs(written) do
      if pts[i][name] ~= nil then print("mutated\t" .. i .. "\t" .. name) end
    end
    for k, v in pairs(r) do print("v\t" .. i .. "\t" .. k .. "\t" .. fmt(v)) end
  end
  print("status\tok")
end
main()
'''

# Determinism probe seeds: 11 twice proves reproducibility, and the two LARGE
# seeds matter because the Park-Miller LCG's first draw from a small seed is
# ~1e-4, so an init that quantizes it (`int(13*rand(1))`) collides for small
# seeds even though it is genuinely seed-driven. The engine seeds with large
# values, so the large pair mirrors it.
DET_SEEDS = (11, 11, 12, 1234567890, 987654321)


def init_determinism_failure(name, det):
    """Why a preset's per_frame_init is not seed-deterministic, or None.

    ``det`` maps seed -> [run, run] of {'draws': n, 'values': <full result
    table>}. An init that never draws from the seed (a steady-state preset) is
    legitimate, so seed sensitivity is only required once the init consumes
    the seed; an init that draws but never varies with it is a failure.
    """
    probes = sorted(set(DET_SEEDS))
    if sorted(det) != probes:
        return '%s: missing determinism rows' % name
    repeat = DET_SEEDS[0]
    if len(det[repeat]) != 2:
        return '%s: expected two runs with seed %d' % (name, repeat)
    if det[repeat][0]['values'] != det[repeat][1]['values']:
        return '%s: same seed gave different init results' % name
    values = {seed: det[seed][0]['values'] for seed in probes}
    draws = det[repeat][0]['draws']
    if draws == 0 and len(set(values.values())) != 1:
        return '%s: init ignored the seed but its result changed' % name
    if draws > 0 and len(set(values.values())) == 1:
        return '%s: init drew from the seed but never changed with it' % name
    return None

PRESET_REPORT = '''\
local function main()
  local presets = require("presets.presets")
  print("count\t" .. #presets)

  local state = {
    bass = 0.62, mid = 0.41, treb = 0.33,
    bass_att = 0.5, mid_att = 0.4, treb_att = 0.3,
    time = 2.5, fps = 60, frame = 150, progress = 0.12,
  }
  for j = 1, 32 do state["q" .. j] = 0 end

  for i, p in ipairs(presets) do
    print("field\t" .. i .. "\tname\t" .. tostring(p.name))
    print("field\t" .. i .. "\twarp\t" .. tostring(p.warp_archetype))
    print("field\t" .. i .. "\tcomp\t" .. tostring(p.comp_archetype))
    print("field\t" .. i .. "\twave_mode\t" .. tostring(p.wave_mode))
    print("field\t" .. i .. "\tdecay\t" .. tostring(p.decay))
    print("field\t" .. i .. "\tq\t" .. tostring(p.q and #p.q or 0))
    print("field\t" .. i .. "\twaves\t" .. tostring(p.waves and #p.waves or 0))
    print("field\t" .. i .. "\tshapes\t" .. tostring(p.shapes and #p.shapes or 0))
    print("field\t" .. i .. "\tsectors\t" .. tostring(p.warp_params and p.warp_params.sectors or 0))
    print("field\t" .. i .. "\tsamples\t"
      .. tostring(p.waves and p.waves[1] and p.waves[1].samples or 0))
    print("field\t" .. i .. "\tper_pixel_len\t" .. tostring(p.per_pixel and #p.per_pixel or 0))

    local codes = {
      { "per_frame_init", p.per_frame_init },
      { "per_frame", p.per_frame },
      { "per_pixel", p.per_pixel },
    }
    for j, w in ipairs(p.waves or {}) do
      codes[#codes + 1] = { "waves[" .. j .. "]", w.t1 }
    end
    for _, c in ipairs(codes) do
      local f, err = ev.compile(c[2])
      print("code\t" .. i .. "\t" .. c[1] .. "\t" .. (f and "ok" or tostring(err)))
    end

    local st = {}
    for k, v in pairs(state) do st[k] = v end
    for j = 1, 32 do st["q" .. j] = (p.q and p.q[j]) or 0 end
    st._rand = make_rand(11)

    local init, ierr = ev.run(st, p.per_frame_init)
    if not init then
      print("run\t" .. i .. "\tinit-error\t" .. tostring(ierr))
    else
      for k, v in pairs(init) do st[k] = v end
      for k, v in pairs(init) do print("init\t" .. i .. "\t" .. k .. "\t" .. fmt(v)) end
      local frame, ferr = ev.run(st, p.per_frame)
      if not frame then
        print("run\t" .. i .. "\tframe-error\t" .. tostring(ferr))
      else
        for k, v in pairs(frame) do st[k] = v end
        print("run\t" .. i .. "\tok")
        for k, v in pairs(frame) do print("out\t" .. i .. "\t" .. k .. "\t" .. fmt(v)) end

        local w = p.waves and p.waves[1]
        if w then
          local prev = { x = 0.5, y = 0.5 }
          for s = 0, 7 do
            local u = s / 7
            local pt = {}
            for k, v in pairs(st) do if k ~= "_rand" then pt[k] = v end end
            pt.sample, pt.x, pt.y = u, u, 0.5
            pt.rad, pt.ang = rad_of(u, 0.5), ang_of(u, 0.5)
            pt.value1, pt.value2 = prev.x, prev.y
            local out, oerr = ev.run(pt, w.t1)
            if not out then
              print("run\t" .. i .. "\tpoint-error\t" .. tostring(oerr))
              break
            end
            prev = out
            for k, v in pairs(out) do
              print("pt\t" .. i .. "\t" .. s .. "\t" .. k .. "\t" .. fmt(v))
            end
          end
        end

        if p.per_pixel and #p.per_pixel > 0 then
          local px, py = 0.9, 0.3
          local pt = {}
          for k, v in pairs(st) do if k ~= "_rand" then pt[k] = v end end
          pt.x, pt.y = px, py
          pt.rad, pt.ang = rad_of(px, py), ang_of(px, py)
          local out, oerr = ev.run(pt, p.per_pixel)
          if not out then
            print("run\t" .. i .. "\tpixel-error\t" .. tostring(oerr))
          else
            for k, v in pairs(out) do
              print("pixel\t" .. i .. "\t" .. k .. "\t" .. fmt(v))
            end
          end
        end
      end
    end
  end

  for i, p in ipairs(presets) do
    for _, seed in ipairs({ __DET_SEEDS__ }) do
      local draws = 0
      local base = make_rand(seed)
      local st = { bass = 0.2, _rand = function() draws = draws + 1 return base() end }
      for j = 1, 32 do st["q" .. j] = 0 end
      local r, err = ev.run(st, p.per_frame_init)
      -- the whole result table (every name the init wrote), not a fixed name
      -- list: an init that seeds q2/q3 or wedges must show up here
      local names = {}
      for k in pairs(r or {}) do names[#names + 1] = k end
      table.sort(names)
      local parts = {}
      for _, n in ipairs(names) do parts[#parts + 1] = n .. "=" .. fmt(r[n]) end
      print("det\t" .. i .. "\t" .. seed .. "\tdraws=" .. draws
        .. "\t" .. (err and ("!" .. tostring(err)) or table.concat(parts, " ")))
    end
  end
end
main()
'''


def run_lua(body, timeout=120):
    script = PRELUDE + '\n' + body
    proc = subprocess.run([LUA, '-'], input=script, text=True,
                          capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError('lua (%s) exited %d\nstdout:\n%s\nstderr:\n%s'
                             % (LUA, proc.returncode, proc.stdout, proc.stderr))
    return proc.stdout


def parse_rows(stdout):
    return [line.split('\t') for line in stdout.splitlines() if line.strip()]


def run_code(code, env=None):
    """compile + one call. Returns (status, results-or-message)."""
    body = RUN_ONE.replace('__CODE__', lua_str(code)).replace('__ENV__', lua_env(env))
    status, payload = None, {}
    for row in parse_rows(run_lua(body)):
        if row[0] == 'status':
            status = row[1]
        elif row[0] == 'message':
            payload = row[1]
        elif row[0] == 'v':
            payload[row[1]] = float(row[2]) if row[2][0] != '!' else row[2]
    return status, payload


def lcg(seed, count=1):
    """Park-Miller LCG, the same stream make_rand() produces in Lua."""
    s = seed % 2147483647
    if s <= 0:
        s += 2147483646
    out = []
    for _ in range(count):
        s = (s * 16807) % 2147483647
        out.append(s / 2147483647.0)
    return out


def i32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


class LuaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if LUA is None:
            raise unittest.SkipTest('no Lua interpreter (luajit/lua5.1/lua) on PATH')
        if MILKDROP is None:
            raise unittest.SkipTest('eyesy-modes-milkdrop pack not present beside this repo')

    def check(self, code, expected, env=None):
        got = self.results(code, env)
        for key, want in expected.items():
            self.assertIn(key, got, '%r produced no %r' % (code, key))
            self.close(got[key], want, '%r -> %s' % (code, key))
        return got

    def results(self, code, env=None):
        status, payload = run_code(code, env)
        self.assertEqual(status, 'ok', 'compile/run of %r failed: %s' % (code, payload))
        return payload

    def close(self, actual, expected, label):
        self.assertIsInstance(actual, float,
                              '%s is not a number (got %r)' % (label, actual))
        self.assertAlmostEqual(actual, expected, delta=1e-9 * max(1.0, abs(expected)),
                               msg=label)


class ArithmeticTests(LuaCase):
    CASES = [
        ('v = 2 + 3 * 4', 14.0),
        ('v = (2 + 3) * 4', 20.0),
        ('v = 10 - 2 - 3', 5.0),
        ('v = 8 / 4 / 2', 1.0),
        ('v = 1 + 2 * 3 ^ 2', 19.0),
        ('v = 2 + 3 * 4 - 6 / 2', 11.0),
        ('v = -2 * 3 + 1', -5.0),
        ('v = 2 * -3', -6.0),
        ('v = 7 % 4', 3.0),
        ('v = 12 % 4', 0.0),
        ('v = 100 / 8', 12.5),
        ('v = -(2 + 3)', -5.0),
        ('v = 1.5e1 + 0.5', 15.5),
        ('v = .5 + .25', 0.75),
        ('v = 3 * (2 + 1) - 4 / 2', 7.0),
        ('v = 0.1 + 0.2 - 0.05', 0.25),
    ]

    def test_arithmetic_and_precedence(self):
        for code, want in self.CASES:
            with self.subTest(code=code):
                self.check(code, {'v': want})

    def test_power_is_right_associative(self):
        cases = [
            ('v = 2 ^ 3 ^ 2', 512.0),
            ('v = (2 ^ 3) ^ 2', 64.0),
            ('v = -2 ^ 2', -4.0),
            ('v = (-2) ^ 2', 4.0),
            ('v = 2 ^ -1 * 4', 2.0),
            ('v = 2 ^ 0.5', math.sqrt(2)),
            ('v = 4 ^ 0.5 ^ 3', 4 ** (0.5 ** 3)),
        ]
        for code, want in cases:
            with self.subTest(code=code):
                self.check(code, {'v': want})

    def test_statements_assign_in_order(self):
        self.check('a = 1; a = a + 1; b = a * 3; c = b - a',
                   {'a': 2.0, 'b': 6.0, 'c': 4.0})

    def test_whitespace_comments_and_empty_statements(self):
        code = '  a = 1 ;; \n\t b = a + 1 ;  '
        self.check(code, {'a': 1.0, 'b': 2.0})

    def test_results_contain_only_assigned_names(self):
        got = self.results('zoom = bass * 2', env={'bass': 0.4, 'treb': 0.9})
        self.assertEqual(set(got), {'zoom'})
        self.close(got['zoom'], 0.8, 'zoom')

    def test_engine_vars_read_and_write(self):
        env = {'bass': 0.5, 'mid': 0.25, 'treb': 0.1, 'bass_att': 0.4,
               'mid_att': 0.3, 'treb_att': 0.2, 'time': 2.0, 'fps': 60.0,
               'frame': 120.0, 'progress': 0.5}
        code = ('zoom = 1.004 + 0.02*bass; decay = 0.98 - 0.01*mid;'
                ' rot = 0.01*sin(0.3*time); gamma = 1 + treb_att')
        self.check(code, {'zoom': 1.014, 'decay': 0.9775,
                          'rot': 0.01 * math.sin(0.6), 'gamma': 1.2}, env)

    def test_undefined_reads_are_zero(self):
        self.check('a = nosuch + 1; b = q17 * 2; c = progress; d = value1 - 3',
                   {'a': 1.0, 'b': 0.0, 'c': 0.0, 'd': -3.0})


class FunctionTests(LuaCase):
    def test_function_set(self):
        cases = [
            ('v = sin(0.5)', math.sin(0.5)),
            ('v = cos(1.25)', math.cos(1.25)),
            ('v = tan(0.4)', math.tan(0.4)),
            ('v = asin(0.5)', math.asin(0.5)),
            ('v = acos(0.5)', math.acos(0.5)),
            ('v = atan(1.5)', math.atan(1.5)),
            ('v = atan2(1.0, 2.0)', math.atan2(1.0, 2.0)),
            ('v = abs(-3.5)', 3.5),
            ('v = min(2.5, 1.5)', 1.5),
            ('v = max(2.5, 1.5)', 2.5),
            ('v = sqr(3)', 9.0),                  # sqr is x*x; sqrt is the root
            ('v = sqrt(2)', math.sqrt(2)),
            ('v = pow(2, 10)', 1024.0),
            ('v = log(2.718281828459045)', 1.0),
            ('v = log10(1000)', 3.0),
            ('v = int(-2.7)', -2.0),              # truncation toward zero
            ('v = int(2.7)', 2.0),
            ('v = sign(-4)', -1.0),
            ('v = sign(0)', 0.0),
            ('v = sign(3)', 1.0),
            ('v = exp(1)', math.e),
            ('v = sigmoid(0)', 0.5),
            ('v = sigmoid(2)', 1 / (1 + math.exp(-2))),
            ('v = sigmoid(-3)', 1 / (1 + math.exp(3))),
            ('v = if(1, 10, 20)', 10.0),
            ('v = if(0, 10, 20)', 20.0),
            ('v = if(0.5, 7, 9)', 7.0),
            ('v = above(2, 1)', 1.0),
            ('v = above(1, 2)', 0.0),
            ('v = above(1, 1)', 0.0),
            ('v = below(1, 2)', 1.0),
            ('v = below(2, 1)', 0.0),
            ('v = equal(3, 3)', 1.0),
            ('v = equal(3, 4)', 0.0),
            ('v = band(12, 10)', float(12 & 10)),
            ('v = bor(12, 10)', float(12 | 10)),
            ('v = band(-4, 6)', float(i32(-4 & 6))),
            ('v = bor(-4, 6)', float(i32(i32(-4) | 6))),
            ('v = bnot(5)', float(i32(~5))),
            ('v = bnot(0)', -1.0),
            ('v = bnot(-1)', 0.0),
            ('v = max(min(3, 1), sqrt(4))', 2.0),
            ('v = sin(0.25 * 4)', math.sin(1.0)),
            ('v = sqr(sin(0.5)) + sqr(cos(0.5))', 1.0),
            ('v = int(3.9) + sign(2) * int(-3.9)', 0.0),
        ]
        for code, want in cases:
            with self.subTest(code=code):
                self.check(code, {'v': want})

    def test_boolean_helpers_in_engine_idiom(self):
        env = {'bass_att': 0.45}
        self.check('sw = above(bass_att, 0.3); x = if(sw, 0.7, 0.1)',
                   {'sw': 1.0, 'x': 0.7}, env)
        self.check('sw = above(bass_att, 0.8); x = if(sw, 0.7, 0.1)',
                   {'sw': 0.0, 'x': 0.1}, env)


class StateTests(LuaCase):
    def test_q_pool_read_write_across_statements(self):
        self.check('q1 = q1 + 1; zoom = q1 * q2; q3 = q1 + zoom',
                   {'q1': 5.0, 'zoom': 1.25, 'q3': 6.25},
                   env={'q1': 4.0, 'q2': 0.25})

    def test_read_before_write_uses_env(self):
        self.check('zoom = q1; q1 = 9', {'zoom': 4.0, 'q1': 9.0}, env={'q1': 4.0})

    def test_q_pool_round_trips_through_engine_state(self):
        body = '''\
local function main()
  local state = { bass = 0.5, _rand = make_rand(3) }
  local init = ev.run(state, "q1 = 0.5; phase = 1; seed = rand(1)")
  if not init then print("status\tinit-error"); return end
  for k, v in pairs(init) do state[k] = v end
  local frame = ev.run(state, "q1 = q1 + phase; zoom = q1 * 2")
  if not frame then print("status\tframe-error"); return end
  for k, v in pairs(frame) do state[k] = v end
  print("status\tok")
  print("v\tq1\t" .. fmt(frame.q1))
  print("v\tzoom\t" .. fmt(frame.zoom))
  print("v\tseed\t" .. fmt(init.seed))
  print("v\tenv_q1\t" .. fmt(state.q1))
end
main()
'''
        rows = parse_rows(run_lua(body))
        self.assertEqual(rows[0], ['status', 'ok'], rows)
        got = {row[1]: float(row[2]) for row in rows[1:]}
        self.close(got['q1'], 1.5, 'q1 after two frames')
        self.close(got['zoom'], 3.0, 'zoom after two frames')
        self.close(got['env_q1'], 1.5, 'merged state')
        self.close(got['seed'], lcg(3)[0], 'rand(1) in per_frame_init')

    def test_env_is_never_mutated(self):
        body = '''\
local function main()
  local env = { bass = 0.4, q1 = 3 }
  local r = ev.run(env, "zoom = bass * 2; q1 = q1 + 1")
  if not r then print("status\tfailed"); return end
  print("status\tok")
  print("v\tq1\t" .. fmt(env.q1))
  print("v\ttouched\t" .. fmt(env.zoom == nil and 1 or 0))
end
main()
'''
        rows = parse_rows(run_lua(body))
        self.assertEqual(rows[0], ['status', 'ok'], rows)
        got = {row[1]: float(row[2]) for row in rows[1:]}
        self.close(got['q1'], 3.0, 'env.q1 untouched')
        self.close(got['touched'], 1.0, 'env has no zoom')


class ErrorTests(LuaCase):
    BAD = [
        '1 +',
        'x =',
        'x = 1 +',
        'x 1',
        'x = (1 + 2',
        'x = foo(1)',
        'x = sin(1, 2)',
        'x = sin()',
        'x = 1 $ 2',
        'x = 3 = 4',
        'x = ,1',
        'x = 1; ; y =',
        'sin(1) = 2',
        'x = unknown(',
        'x = 1 2',
        'x = 1..2',
        'x = * 2',
        'x = )',
    ]

    def test_parse_errors_return_nil_and_message(self):
        for code in self.BAD:
            with self.subTest(code=code):
                status, payload = run_code(code)
                self.assertEqual(status, 'error', '%r unexpectedly compiled' % code)
                self.assertIsInstance(payload, str, '%r: %r' % (code, payload))
                self.assertTrue(payload.strip(), '%r produced an empty message' % code)

    def test_never_throws_on_pathological_input(self):
        body = '''\
local function main()
  local cases = {
    "x = " .. string.rep("-", 400) .. "1",
    "x = " .. string.rep("(", 200) .. "1" .. string.rep(")", 200),
    "x = " .. string.rep("1+", 1000) .. "1",
    "x = " .. string.rep("(", 4000),
    "x = " .. string.rep("-", 5000),
    string.rep("x = 1;", 2000),
  }
  for i = 1, #cases do
    local ok, f, err = pcall(ev.compile, cases[i])
    local tag
    if not ok then
      tag = "threw " .. tostring(f)
    elseif f then
      local r = f({})
      tag = "value " .. fmt(r.v or r.x or 0)
    else
      tag = "error " .. tostring(err)
    end
    print("case\t" .. i .. "\t" .. tag)
  end
end
main()
'''
        rows = parse_rows(run_lua(body))
        self.assertEqual(len(rows), 6, rows)
        tags = {int(row[1]): row[2] for row in rows}
        for idx, tag in tags.items():
            with self.subTest(case=idx):
                self.assertFalse(tag.startswith('threw'), 'compile threw on case %d: %s'
                                 % (idx, tag))
        self.close(float(tags[1].split()[1]), 1.0, '400 unary minuses')
        self.close(float(tags[2].split()[1]), 1.0, '200 nested parens')
        self.close(float(tags[3].split()[1]), 1001.0, '1000 chained additions')
        self.close(float(tags[6].split()[1]), 1.0, '2000 statements')

    def test_empty_and_absent_code_compile_to_nothing(self):
        for code in ('', '   ', ';', ';;\n\t'):
            with self.subTest(code=code):
                status, payload = run_code(code)
                self.assertEqual(status, 'ok', '%r failed: %s' % (code, payload))
                self.assertEqual(payload, {})

    def test_compile_accepts_nil_and_rejects_non_strings(self):
        body = '''\
local function main()
  local fnil, enil = ev.compile(nil)
  print("v\tnil-code\t" .. fmt(fnil and 1 or 0))
  local fnum, enum = ev.compile(42)
  print("v\tnumber-code\t" .. fmt(fnum and 1 or 0))
  print("v\tnumber-message\t" .. fmt(type(enum) == "string" and 1 or 0))
  local r = ev.run({}, nil)
  print("v\trun-nil\t" .. fmt(type(r) == "table" and 1 or 0))
end
main()
'''
        rows = parse_rows(run_lua(body))
        got = {row[1]: float(row[2]) for row in rows}
        self.close(got['nil-code'], 1.0, 'compile(nil) compiles')
        self.close(got['number-code'], 0.0, 'compile(42) fails')
        self.close(got['number-message'], 1.0, 'compile(42) message is a string')
        self.close(got['run-nil'], 1.0, 'run(env, nil) returns a table')

    def test_run_reports_parse_error_without_throwing(self):
        body = '''\
local function main()
  local r, err = ev.run({}, "x = 1 +")
  print("v\tresult\t" .. fmt(r == nil and 1 or 0))
  print("v\tmessage\t" .. fmt(type(err) == "string" and 1 or 0))
end
main()
'''
        rows = parse_rows(run_lua(body))
        got = {row[1]: float(row[2]) for row in rows}
        self.close(got['result'], 1.0, 'run returns nil on a parse error')
        self.close(got['message'], 1.0, 'run returns a message')


class ClampTests(LuaCase):
    def test_nonfinite_results_collapse_to_zero(self):
        cases = [
            'v = 1 / 0',
            'v = -1 / 0',
            'v = 0 / 0',
            'v = sqrt(-1)',
            'v = log(0)',
            'v = log10(0)',
            'v = pow(-2, 0.5)',
            'v = exp(1000)',
            'v = 1e308 * 10',
            'v = asin(2)',
            'v = 0 * (1 / 0)',
            'v = sqr(1e200)',
        ]
        for code in cases:
            with self.subTest(code=code):
                self.check(code, {'v': 0.0})

    def test_nonfinite_env_values_read_as_zero(self):
        env = {'bass': Raw('0/0'), 'mid': Raw('1/0'), 'treb': Raw('-1/0'),
               'text': 'loud', 'tbl': Raw('{}')}
        self.check('a = bass + 1; b = mid - 1; c = treb * 2; d = text + 1;'
                   ' e = tbl + 1; f = above(bass, 0)',
                   {'a': 1.0, 'b': -1.0, 'c': 0.0, 'd': 1.0, 'e': 1.0, 'f': 0.0}, env)

    def test_every_result_key_is_finite(self):
        env = {'bass': Raw('0/0'), 'time': Raw('1/0')}
        got = self.results('zoom = 1 + bass; rot = time; decay = 1 / 0; n = 5',
                           env)
        for key, value in got.items():
            self.assertIsInstance(value, float, '%s is not a number' % key)
            self.assertTrue(math.isfinite(value), '%s is not finite: %r' % (key, value))

    def test_zero_division_keeps_the_rest_of_the_block(self):
        self.check('a = 1 / 0; b = a + 4; c = a * 2',
                   {'a': 0.0, 'b': 4.0, 'c': 0.0})


class RandTests(LuaCase):
    def test_rand_uses_env_prng_deterministically(self):
        got = self.check('a = rand(1); b = rand(1); c = rand(4)',
                         {'a': lcg(7, 3)[0], 'b': lcg(7, 3)[1], 'c': 4 * lcg(7, 3)[2]},
                         env={'_rand': Raw('make_rand(7)')})
        self.assertGreaterEqual(got['a'], 0.0)
        self.assertLess(got['a'], 1.0)
        self.assertLess(got['c'], 4.0)

    def test_rand_repeats_across_runs_with_the_same_seed(self):
        code = 'a = rand(1)'
        env = {'_rand': Raw('make_rand(7)')}
        first = self.results(code, env)
        second = self.results(code, env)      # fresh process, fresh handle
        self.close(second['a'], first['a'], 'same seed -> same draw')
        other = self.results(code, {'_rand': Raw('make_rand(8)')})
        self.assertNotEqual(other['a'], first['a'], 'different seed -> different draw')
        self.close(other['a'], lcg(8)[0], 'seed 8 first draw')

    def test_if_does_not_evaluate_the_untaken_branch(self):
        got = self.results('a = if(0, rand(1), 0); b = rand(1)',
                           env={'_rand': Raw('make_rand(7)')})
        self.close(got['a'], 0.0, 'untaken branch')
        self.close(got['b'], lcg(7)[0], 'first draw belongs to b')

    def test_rand_without_a_handle_stays_finite_and_deterministic(self):
        body = '''\
local function main()
  local f = compile_ok("a = rand(1); b = rand(1)")
  local r = f({})
  print("v\ta\t" .. fmt(r.a))
  print("v\tb\t" .. fmt(r.b))
end
main()
'''
        first = {row[1]: float(row[2]) for row in parse_rows(run_lua(body))}
        second = {row[1]: float(row[2]) for row in parse_rows(run_lua(body))}
        self.assertEqual(first, second, 'fallback PRNG is not process-stable')
        for key, value in first.items():
            self.assertGreaterEqual(value, 0.0)
            self.assertLess(value, 1.0)
        self.assertNotEqual(first['a'], first['b'], 'fallback stream does not advance')


class PerPointTests(LuaCase):
    CODE = ('d = x + 2*y + 3*sample + 4*value1 - 5*value2;'
            ' r2 = 2*rad; a2 = ang + 10; m = missing + 1; q = q7 + 1')

    def test_per_point_env_reads_x_y_rad_ang(self):
        raw = [(0.25, 0.5), (0.5, 0.75), (0.9, 0.1), (0.5, 0.5),
               (0.1, 0.2), (0.75, 0.6)]
        points, expected = [], []
        for index, (x, y) in enumerate(raw):
            sample = index / (len(raw) - 1.0)
            value1 = raw[index - 1][0] if index else 0.5
            value2 = raw[index - 1][1] if index else 0.5
            q7 = 0.25 * (index + 1)
            rad = math.hypot(x - 0.5, y - 0.5)
            ang = math.atan2(y - 0.5, x - 0.5)
            points.append({'x': x, 'y': y, 'sample': sample, 'rad': rad, 'ang': ang,
                           'value1': value1, 'value2': value2, 'q7': q7,
                           '_rand': Raw('make_rand(9)')})
            expected.append({'d': x + 2 * y + 3 * sample + 4 * value1 - 5 * value2,
                             'r2': 2 * rad, 'a2': ang + 10, 'm': 1.0, 'q': q7 + 1})

        body = POINTS.replace('__CODE__', lua_str(self.CODE))
        body = body.replace('__PTS__', '{ ' + ', '.join(lua_env(p) for p in points) + ' }')
        rows = parse_rows(run_lua(body))
        self.assertEqual(rows[-1], ['status', 'ok'], rows[-1])
        self.assertFalse([row for row in rows if row[0] == 'mutated'],
                         'evaluator mutated a point env')
        got = {}
        for row in rows:
            if row[0] == 'v':
                got.setdefault(int(row[1]), {})[row[2]] = float(row[3])
        self.assertEqual(sorted(got), list(range(1, len(raw) + 1)))
        for index, want in enumerate(expected, start=1):
            for key, value in want.items():
                self.close(got[index][key], value,
                           'point %d (%r) -> %s' % (index, raw[index - 1], key))

    def test_same_compiled_code_is_reused_per_point(self):
        body = '''\
local function main()
  local f = compile_ok("y2 = x * 2 + sample")
  for _, env in ipairs({ { x = 0.25, sample = 0.1 }, { x = 0.5, sample = 0.2 },
                         { x = 0.75, sample = 0.3 } }) do
    local r = f(env)
    print("v\ty2\t" .. fmt(r.y2))
  end
end
main()
'''
        rows = parse_rows(run_lua(body))
        values = [float(row[2]) for row in rows]
        self.assertEqual(len(values), 3)
        for value, (x, sample) in zip(values, [(0.25, 0.1), (0.5, 0.2), (0.75, 0.3)]):
            self.close(value, 2 * x + sample, 'reused compiled function')


class PresetLibraryTests(LuaCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        rows = parse_rows(run_lua(PRESET_REPORT.replace(
            '__DET_SEEDS__', ', '.join(str(s) for s in DET_SEEDS))))
        cls.count = 0
        cls.presets = {}
        for row in rows:
            kind = row[0]
            if kind == 'count':
                cls.count = int(row[1])
                continue
            entry = cls.presets.setdefault(int(row[1]), {
                'fields': {}, 'codes': {}, 'out': {}, 'points': {},
                'pixel': {}, 'init': {}, 'det': {}})
            if kind == 'field':
                entry['fields'][row[2]] = row[3]
            elif kind == 'code':
                entry['codes'][row[2]] = row[3]
            elif kind == 'out':
                entry['out'][row[2]] = cls._num(row[3])
            elif kind == 'init':
                entry['init'][row[2]] = cls._num(row[3])
            elif kind == 'pt':
                entry['points'].setdefault(int(row[2]), {})[row[3]] = cls._num(row[4])
            elif kind == 'pixel':
                entry['pixel'][row[2]] = cls._num(row[3])
            elif kind == 'det':
                key, _, count = row[3].partition('=')
                entry.setdefault('det', {}).setdefault(int(row[2]), []).append(
                    {'draws': int(count) if key == 'draws' else 0,
                     'values': row[4]})
            elif kind == 'run':
                entry.setdefault('run', []).append(row[2:])
        cls.by_name = {p['fields']['name']: p for p in cls.presets.values()
                       if 'name' in p['fields']}

    @staticmethod
    def _num(text):
        return float(text) if text[0] != '!' else text

    def finite(self, value, label):
        self.assertIsInstance(value, float, '%s is not a number (got %r)' % (label, value))
        self.assertTrue(math.isfinite(value), '%s is not finite (%r)' % (label, value))
        return value

    def test_library_shape(self):
        self.assertGreaterEqual(self.count, 2, 'no presets in the library')
        for name in ('darken-drift', 'sector-shards'):
            self.assertIn(name, self.by_name, 'missing seed preset %r' % name)

    def test_preset_fields_match_the_schema(self):
        for name, preset in sorted(self.by_name.items()):
            fields = preset['fields']
            with self.subTest(preset=name):
                self.assertIn(fields['warp'], ('default', 'sphere', 'sector'))
                self.assertIn(fields['comp'], ('default', 'glow'))
                self.assertIn(int(fields['wave_mode']), range(4))
                self.assertGreater(float(fields['decay']), 0.0)
                self.assertLessEqual(float(fields['decay']), 1.0)
                # an empty declared pool is valid: per_frame_init seeds q1..qN
                if int(fields['q']) > 0:
                    self.assertGreaterEqual(int(fields['q']), 2, 'q pool needs q1..qN')
                # waves = {} is valid: the preset rides the built-in wave_mode
                if int(fields['waves']) > 0:
                    self.assertGreaterEqual(int(fields['samples']), 1,
                                            'a declared wave needs a sample count')

    def test_all_preset_code_compiles(self):
        for name, preset in sorted(self.by_name.items()):
            codes = preset['codes']
            with self.subTest(preset=name):
                self.assertIn('per_frame', codes)
                self.assertIn('per_frame_init', codes)
                self.assertIn('per_pixel', codes)
                for label, status in sorted(codes.items()):
                    self.assertEqual(status, 'ok', '%s: %s did not compile' % (name, label))

    def test_preset_frames_run_finite(self):
        for name, preset in sorted(self.by_name.items()):
            runs = preset.get('run', [])
            with self.subTest(preset=name):
                self.assertEqual(runs, [['ok']], '%s: per_frame did not run cleanly' % name)
                self.assertIn('zoom', preset['out'], 'per_frame never wrote zoom')
                self.assertIn('decay', preset['out'], 'per_frame never wrote decay')
                for key, value in sorted(preset['out'].items()):
                    self.finite(value, '%s: %s' % (name, key))
                for key, value in sorted(preset['init'].items()):
                    self.finite(value, '%s init: %s' % (name, key))

    def test_wave_points_stay_on_screen(self):
        for name, preset in sorted(self.by_name.items()):
            points = preset['points']
            with self.subTest(preset=name):
                if int(preset['fields']['waves']) == 0:
                    # built-in-wave presets declare no custom wave: the engine
                    # draws wave_mode 0..3 from ctx.audio, so no point ran
                    self.assertEqual(points, {}, '%s declared no custom wave' % name)
                    continue
                self.assertEqual(sorted(points), list(range(8)), 'expected 8 wave points')
                seen = set()
                for index, values in sorted(points.items()):
                    for key in ('x', 'y'):
                        self.assertIn(key, values, '%s point %d wrote no %s' % (name, index, key))
                    for field, value in sorted(values.items()):
                        self.finite(value, '%s point %d: %s' % (name, index, field))
                    self.assertGreaterEqual(values['x'], 0.0)
                    self.assertLessEqual(values['x'], 1.0)
                    self.assertGreaterEqual(values['y'], 0.0)
                    self.assertLessEqual(values['y'], 1.0)
                    seen.add((round(values['x'], 9), round(values['y'], 9)))
                self.assertGreater(len(seen), 1, '%s wave is a single point' % name)

    def test_per_frame_init_is_seeded_deterministically(self):
        for name, preset in sorted(self.by_name.items()):
            with self.subTest(preset=name):
                failure = init_determinism_failure(name, preset['det'])
                self.assertIsNone(failure, failure)
                if name in ('darken-drift', 'sector-shards'):
                    # the two seed presets exist to reseed per trigger
                    det = preset['det']
                    self.assertGreater(det[11][0]['draws'], 0,
                                       '%s: per_frame_init must draw from the seed' % name)
                    self.assertNotEqual(det[11][0]['values'], det[12][0]['values'],
                                        '%s: seed change must reseed the init' % name)

    def test_determinism_rule_accepts_steady_state_and_rejects_ignored_seeds(self):
        """The rule above is what makes steady-state presets legal: prove it."""
        probes = sorted(set(DET_SEEDS))

        def det(rows):
            """rows: {seed: [(draws, values), ...]} -> the harness's det shape."""
            return {seed: [{'draws': d, 'values': v} for d, v in runs]
                    for seed, runs in rows.items()}

        steady = {seed: [(0, 'phase=0 q1=0')] for seed in probes}
        steady[DET_SEEDS[0]] = [(0, 'phase=0 q1=0')] * 2
        self.assertIsNone(init_determinism_failure('steady', det(steady)),
                          'a steady-state init that never draws must be accepted')
        driven = {seed: [(1, 'q1=%.3f' % seed)] for seed in probes}
        driven[DET_SEEDS[0]] = [(1, 'q1=%.3f' % DET_SEEDS[0])] * 2
        self.assertIsNone(init_determinism_failure('driven', det(driven)),
                          'an init that varies with the seed must be accepted')
        ignored = {seed: [(1, 'q1=0.5')] for seed in probes}
        ignored[DET_SEEDS[0]] = [(1, 'q1=0.5')] * 2
        self.assertIn('never changed with it',
                      init_determinism_failure('ignored', det(ignored)) or '',
                      'an init that draws but ignores the seed must be rejected')
        differing = dict(driven)
        differing[DET_SEEDS[0]] = [(1, 'q1=0.5'), (1, 'q1=0.6')]
        self.assertIn('same seed gave different',
                      init_determinism_failure('differing', det(differing)) or '',
                      'two runs on one seed must agree')

    def test_darken_drift_is_the_default_archetype(self):
        preset = self.by_name['darken-drift']
        fields = preset['fields']
        self.assertEqual(fields['warp'], 'default')
        self.assertEqual(fields['comp'], 'default')
        self.assertEqual(int(fields['per_pixel_len']), 0, 'default archetype needs no per-pixel code')
        # per_frame zoom/bass coupling: zoom = 1.004 + 0.02*q1*bass_att
        q1 = preset['init']['q1']
        self.finite(q1, 'darken-drift q1 seed')
        self.assertGreaterEqual(q1, 0.4)
        self.assertLessEqual(q1, 0.8)
        self.close(preset['out']['zoom'], 1.004 + 0.02 * q1 * 0.5, 'zoom')
        self.close(preset['out']['warp'], 0.3 * preset['init']['q2'] * 0.5, 'warp')
        self.close(preset['out']['decay'], 0.975 + 0.02 * 0.5, 'decay')
        # wave: sample lookup then point position, both driven by q3
        q3 = preset['out']['q3']
        self.assertGreater(q3, 0.0, 'drift phase never advances')
        for index, values in sorted(preset['points'].items()):
            u = index / 7.0
            sample = 0.5 + 0.45 * math.sin(u * 3.14159 + q3)
            with self.subTest(point=index):
                self.close(values['sample'], sample, 'wave sample')
                self.close(values['x'], sample, 'wave x')
                self.close(values['y'],
                           0.5 + 0.22 * math.sin(sample * 6.28318 + q3 * 1.4), 'wave y')

    def test_sector_shards_ports_the_crystal_shards_math(self):
        preset = self.by_name['sector-shards']
        fields = preset['fields']
        self.assertEqual(fields['warp'], 'sector')
        self.assertEqual(fields['comp'], 'glow')
        self.assertEqual(int(fields['sectors']), 8)
        self.assertEqual(int(fields['waves']), 3, 'three additive petals')
        self.assertGreater(int(fields['per_pixel_len']), 0, 'sector archetype needs per-pixel code')

        # per_frame: sector uniforms and the petal phase advances
        out = preset['out']
        self.assertGreater(out['q1'], 0.0)
        self.assertGreater(out['q2'], 0.0)
        self.assertGreater(out['q3'], 0.0)
        self.close(out['sw'], 1.0, 'sw = above(bass_att, 0.3)')
        self.close(out['sa'], 0.35 + 0.3 * 0.5, 'sa = 0.35 + 0.3*bass_att')
        self.close(out['sector_zoom'], 1.0 + 0.25 * math.sin(out['q3'] * 3.0) * 0.5,
                   'sector_zoom')

        # wave 1: xa/xb petals, if()-switched blend, reflection about the new x
        t1, t2, sa, sw = preset['init']['t1'], preset['init']['t2'], out['sa'], out['sw']
        self.assertGreaterEqual(t1, 0.2)
        self.assertLessEqual(t1, 0.8)
        for index, values in sorted(preset['points'].items()):
            u = index / 7.0
            xa = 0.25 + 0.25 * math.sin(out['q1'] * t1)
            xb = 0.25 + 0.25 * math.sin(out['q2'] * t2)
            x = xa * u + sa * xb if sw != 0 else xb * u + sa * xa
            with self.subTest(point=index):
                self.close(values['x'], x, 'petal x')
                self.close(values['y'], 0.5 - sa * 0.5 * (0.5 - x) * 2, 'petal y')

        # per_pixel: seg = int((ang + pi)/(2*pi)*num); dx = above(seg,0)*(x - ox)
        px, py = 0.9, 0.3
        ang = math.atan2(py - 0.5, px - 0.5)
        seg = math.trunc((ang + math.pi) / (2 * math.pi) * 8)
        rise = 1.0 if seg > 0 else 0.0
        pixel = preset['pixel']
        self.assertEqual(pixel.get('seg'), float(seg))
        self.close(pixel.get('rise'), rise, 'per_pixel rise')
        self.close(pixel.get('dx'), rise * (px - 0.5), 'per_pixel dx')
        self.close(pixel.get('dy'), rise * (py - 0.5), 'per_pixel dy')


if __name__ == '__main__':
    unittest.main(verbosity=2)
