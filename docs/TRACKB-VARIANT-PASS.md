# Track B Variant Pass

Spec for Track B of the batch-2 plan (`eyesy-modes-bespoke/docs/batch2-plan/PLAN.md`):
the scaling unlock that turns the milkdrop preset engine's catalog into a
growing library of scene variants. Preset authoring lives in the
`eyesy-modes-milkdrop` sibling repo, not in this repo; this document is the
engine-side contract the pass runs against and the acceptance gate every
shipped batch must clear.

## What Track B is

One Lua engine (`modes/milkdrop/`) loads a catalog of presets defined in
`presets/presets.lua`: per-frame equations drive the feedback loop, per-point
equations drive custom waves, and a warp -> composite fragment chain (six
canonical ES2 passes in this pack, `frag/`) renders the frame. The engine is
built, measured, and documented in `eyesy-modes-milkdrop/README.md`; the
engine-side tier facts are recorded in `docs/SCENE-LIBRARY.md`
(milkdrop-engine tiers, 2026-09-16).

The variant pass is the authoring workload on top of that engine: instead of
one-off scenes, presets are written as parameterized families so a family can
be cheaply re-instantiated across its variant axes. The payoff is scale —
from the 12 presets that shipped with the engine toward a library of 100+
self-authored variants (see Target) — at the per-preset cost of a parameter
pass rather than a new scene.

## Presets as scene variants

A preset is a scene variant in the `docs/SCENE-LIBRARY.md` sense: a saved
scene JSON is parameters + state, never new code, and must be recognizable
as its family while carrying its own name, default palette, and trigger
behavior. The preset catalog encodes the same contract in Lua — each entry is
`name` + `per_frame_init` / `per_frame` / `per_pixel` / `waves` equation
blocks plus archetype and parameter tables (`warp_archetype`,
`comp_archetype`, `comp_params`, `wave_mode`, `decay`, `q` pool). Switching
between presets is the mode-level equivalent of scene recall; the trigger
button re-runs `per_frame_init` with a fresh seed ("in-family beat":
re-seed morphology and palette, never switch preset — the k2/`preset` knob
and saved-scene variants own switching, per the Track B brief).

A variant is therefore a full preset entry whose family (warp archetype,
comp archetype, wave structure) is held constant while the three axes below
are swept.

## Per-family variant axes

| Axis | What varies | Where it lives in a preset |
| --- | --- | --- |
| **palette** | colour identity: base hue and drift, gamma, contrast, echo, per-family palette name | `hue`/`gamma`/`contrast` writes in `per_frame`, `comp_params` colour uniforms, the `palette` field of a variant JSON (Track B brief layout); trigger re-seeds it (MilkDrop `c` randomize-colors equivalent) |
| **regime** | feedback character: which warp and composite do the loop, how hard the decay, which built-in wave rides along | `warp_archetype` (`default`/`sphere`/`sector`), `comp_archetype` (`default`/`glow`/`softmax`/`plasma`), `decay`/`gamma`/`contrast`/`echo` envelope, `wave_mode` 0..3, `q`-pool integration rates |
| **motion** | geometry and audio coupling: zoom/rot drift, wave shape and radius, how hard bass/mid/treb push | per-frame `zoom`/`rot`/`cx`/`cy`/`dx`/`dy`/`warp` writes, per-point wave equations (`th`, `rr`, `x`, `y`), `bass_att`/`mid_att`/`treb_att` coefficients, knob-1/knob-5 bridge |

A family is a fixed (warp_archetype, comp_archetype, wave structure);
variants of that family differ along at least one axis above and keep the
family's recognizable look. Example in the shipped catalog: the two tranche-2
composite presets `softmax-halo` and `plasma-veil` (`presets/presets.lua`)
are single-points of their families today — the pass sweeps palette and
motion variants of each at fixed comp regime.

## Target

From 12 presets (the `dev-e46f786ab44d` catalog, `docs/SCENE-LIBRARY.md`
milkdrop tier table) toward 100+ self-authored variants. The catalog is 18
presets as of the soft-max/plasma tranche (pack commit "Port the soft-max
composite", slot 17 = `softmax-halo`, slot 18 = `plasma-veil`). The 100+
goal is met by sweeping the three axes per family, not by adding one-off
presets; each tranche ships as a batch (see QC gate).

## QC gate

Every batch of new or re-tuned variants must pass, in order:

1. **Pack gates** (in `eyesy-modes-milkdrop`, run from that repo): preset
   schema/archetype/compile gate `tools/check_presets.py` and fragment
   host/uniform-traffic gate `tools/check_fragments.py` (plus the negative
   demonstrations). The evaluator side is re-verified from this repo with
   `python3 -m unittest tests.test_milkdrop_evaluator`.
2. **Per-scene tier assertion**: every preset holds tier C (`<= 33.3 ms` p50,
   `docs/SCENE-LIBRARY.md` performance tiers) on the device, 600 frames
   offscreen with a tier-A neighbour, per preset; the two glow-comp presets
   stay under the documented waiver, everything new ships at or under tier C.
3. **Contact sheet per batch**: `evidence/` in `eyesy-modes-milkdrop` gets a
   `contact-sheet.png` (from `tools/scene_verify.py` in this repo) plus per
   preset `summary.json` from the deterministic A/B contract verdict, and a
   human visual pass over the sheet — aesthetics and family resemblance are a
   human call, never asserted mechanically.
4. **Batch docs + commit**: the batch lands with its variant list, per-preset
   tier numbers, and any family notes, committed in `eyesy-modes-milkdrop`.

## Licensing rule

- Self-authored parameter variants are unencumbered. The engine's equations
  are self-authored ports of documented archetypes (BSD-3-Clause upstream
  `milkdrop2077/MilkDrop3`); no community `.milk` preset file is copied, and
  this pass keeps it that way — variants are parameter sweeps of
  self-authored presets, not re-encoded packs.
- Community preset packs (projectM cream-of-the-crop, butterchurn-presets)
  are separate artwork with separate terms: importing them into a distributed
  product is a rights question, not a code-port question. Treat community
  pack import as user-supplied content unless cleared — the import QC
  checklist (MilkDrop1-era compat patches, aspect handling) is in
  `eyesy-modes-milkdrop/docs/research/BeatDropForkPorting.md`.

## Authoring location

Preset authoring, the pack gates, and per-batch evidence all live in the
`eyesy-modes-milkdrop` sibling repo (`main.lua`, `lib/evaluator.lua`,
`presets/presets.lua`, `frag/`, `tools/`, `evidence/`). This repo consumes
the assembled mode via `./eyesyctl modes sync` and owns the engine-side
contracts (`docs/SCENE-LIBRARY.md`, `tests/test_milkdrop_evaluator.py`) and
the device tier verification of each shipment. Never edit `modes/` directly:
it is the gitignored assembly dir.

## Cross-repo follow-up: spirolateral wave point out of range

Found by `tests/test_milkdrop_evaluator.py::PresetLibraryTests::test_wave_points_stay_on_screen`
during the softmax archetype widening (2026-09-18). The test asserts every
custom-wave point stays in `[0, 1]` and fails for the `spirolateral` preset:
point x = **1.037814476523391 > 1.0**.

- **Preset data is genuinely out of range.** `modes/milkdrop/presets/presets.lua:828`
  (first wave of `spirolateral`): `rr = 0.05 + 0.38*sample + (0.08 + 0.14*sample)*bass_att`,
  then `x = 0.5 + rr*cos(th)` (line 829). At `sample = 1` with `bass_att = 0.5`
  (the harness's audio state), `rr` reaches **0.54** -> radius beyond the
  0.5 the per-point contract allows -> `x` up to ~1.04. The failing point is
  the spiral tip (sample 1, `cos(th) ~ 0.996`). Not an engine bug: the math
  is the authored equation.
- **The engine clamps, but not to the screen.** `draw_custom_waves` in
  `modes/milkdrop/main.lua:521-522` clamps every custom-wave `x`/`y` to
  `WAVE_MIN..WAVE_MAX = -1.0..2.0` (`main.lua:69`) — a sanity bound against
  non-finite blowups, not an on-screen clamp. 1.0378 passes through untouched
  and draws off the right edge (GPU viewport clips it visually).
- **The test assertion is correct and stays.** It guards the scene contract
  ("x/y are normalised 0..1 about (0.5, 0.5)", `main.lua` wave comment); the
  preset legitimately violates it at the tip.
- **Action, owned by the pack repo** (parallel work, not this repo): retune
  `spirolateral`'s first wave so `max(rr) <= 0.5` over the audio range (e.g.
  scale `bass_att` radius term or cap `rr`), then re-run the evaluator suite
  here — the test must go green with the assertion unchanged.

## Cross-repo follow-up: reaction-field per_frame never writes zoom

Found by `tests/test_milkdrop_evaluator.py::PresetLibraryTests::test_preset_frames_run_finite`
on 2026-09-18, after the archetype allow-list was widened. The preset's
`per_frame` writes `rd_dt`, `gamma`, `rd_feed`, `saturation`, `contrast`,
`rd_kill`, `q1` and `hue` but **never `zoom`**, so the test's
`assertIn('zoom', preset['out'])` fails.

- The warp pass samples the previous feedback frame at the warped uv and needs
  `zoom` (with `decay`) written every frame; a preset that omits it leaves the
  feedback loop without its warp driver.
- **Action, owned by the pack repo** (parallel work, not this repo): have
  `reaction-field`'s `per_frame` write `zoom` (the other diffuse/warp presets
  set it), then re-run the evaluator suite here.

The other three presets that the widened allow-list unblocked — `kaleido-fold`
(`warp=kaleido`), `painterly-flow` (`warp=blur`) and `roto-streaks`
(`comp=rotoblur`) — now pass; the engine dispatches those archetypes in
`modes/milkdrop/main.lua`.