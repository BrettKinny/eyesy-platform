# Bench session 2026-09-15: rollback, recovery-path, provision hygiene, soak

Device: CM3+ spare, <device-ip>, clone <clone-id>, releases `dev-cf8b1ee8013f`
(current, KMS) and `dev-dd42a1d3bd86` (previous, Xorg-era). Observer chain: one
UVC streamer on the HDMI→USB dongle (sink + HPD authority), `vidctl_watch.sh`
latch oracle (~10 Hz). Device runs UTC in `date`, BST in the journal; all
journal quotes below are BST.

Sections 3–6 of `docs/BENCH-CHECKLIST.md` were the frame; physical-input
sections (knobs/MIDI/stereo/latency) still need hands and remain open.

## Phase 0 — baseline

- Platform active on `dev-cf8b1ee8013f`, 60.4 fps, `VC4 V3D 2.1`, audio clean.
- The engine had been rendering blind since the morning V2 streamer stopped:
  `card0-HDMI-A-1: disconnected` while frames kept advancing. After restarting
  the streamer, HPD returned and the blind engine's scanout resumed onto the
  dongle with **no service intervention** (content YAVG ~30.3, `VID_CTL
  0xc0000000`). Mid-run sink loss is non-fatal; sink return needs no restart.
- Oracle: zero latched (`0xc2…`) samples across the whole session.

## Phase 1 — `rollback --target previous` (dd42, Xorg-era)

- dd42's engine rejects the service's `--kms` flag:
  `eyesy: unknown argument: --kms` (it predates the KMS backend; `strings`
  shows zero `--kms` support).
- Cascade (journal `00:07:36–38`): dd42 start fails → helper raises at
  `systemctl start` → `restore_selection` re-points `current` to cf8b → one
  auto-restart raced the reselection (second dd42 rejection, PID 4659) → cf8b
  start succeeds (PID 4674, `KMS: scanout live`, `VC4 V3D 2.1`). Total <2 s,
  end state healthy, `Result=success`.
- The restore's stop of the restarting unit fired `OnFailure`; the fallback's
  `systemctl start eyesypy` was **canceled** by the concurrent platform start
  (`Conflicts=eyesypy.service`), so the fallback unit itself ended FAILED.
  Convergent but noisy: recovery outran the fallback. Reset with
  `systemctl reset-failed eyesy-platform-fallback`.
- `previous.json` unchanged (still dd42) — correct, updates only on success.
- Verdict: the rollback *mechanism* (select → start → detect → restore) is
  qualified live and self-heals in seconds. The *target* dd42 is not a valid
  previous release under the KMS service; until two KMS releases exist,
  `--target previous` is a safe, deterministic no-op.

## Phase 2 — `rollback --target stock`

- Exit 0, ~5 s. `eyesypy` active (pygame/SDL), platform inactive, `current`
  and `active.env` removed, `previous.json` retained.
- **Stock output visible on the dongle** (YAVG 30.3 → 129.8), `VID_CTL
  0xc0000000` — clean; stock SDL/KMSDRM does not latch.
- The stop fired `OnFailure` again: the engine **exits 1 on SIGTERM** (journal:
  `Main process exited, code=exited, status=1/FAILURE` on a routine stop), so a
  clean stop marks the unit failed and triggers the fallback. The fallback's
  stock start merged with the rollback's own stock start — convergent. Engine
  fix candidate: exit 0 on SIGTERM.

## Phase 3 — platform re-entry after stock (tooling gap found)

- **Gap**: after `--target stock` there is no supported path back to an
  already-installed release. `activate()` refuses existing release dirs,
  byte-reproducible rebuilds produce the same release ID, and `rollback` only
  knows previous (dd42, incompatible) or stock.
- Applied `reselect_cf8b.py` (mirrors `select_release()` + activate's env
  write), `reset-failed`, `systemctl start eyesy-platform` → healthy
  (60.5 fps, VC4). `Conflicts` auto-stopped stock. A supported re-entry
  command is a follow-up.

## Phase 4 — genuine recovery path: engine failure → OnFailure → stock

- Sink dropped (streamer stopped → HPD released → connector `disconnected`),
  then stop/start of the platform service, **no operator recovery**:
  engine refuses to start (`eyesy: KMS: no connected display …is the dongle
  streamer keeping HPD asserted?`) → auto-restarts (counter 2, 3) →
  `Start request repeated too quickly` → unit FAILED → `Triggering OnFailure=`
  → fallback **finished successfully** → `eyesypy` **active**. ~9 s end to end,
  deterministic.
- Stock started and stayed up with **no display attached**.

## Phase 5 — subsequent platform recovery

- Streamer back (HPD asserted, connector `connected`), `reset-failed` +
  `systemctl start eyesy-platform` → stock auto-stopped, engine healthy
  (60.5 fps, VC4, `Result=success`, NRestarts=0). Dongle shows engine content
  again (YAVG 30.3).
- Roadmap #3 is qualified at service level. The literal cold-boot variant
  (power cycle into each state) still needs a user power-cycle.

## Phase 6 — provision hygiene (roadmap #5)

- `/etc/X11/xorg.conf.d/10-eyesy-720p.conf` removed on the live device with the
  verified remount dance: `ro,noatime` → rw → rm → **absence verified** → ro →
  `ro,noatime` confirmed. Platform unaffected.
- `tools/provision_device.sh` now does the same with loud failures
  (10/10 targeted tests pass; agent slice verified).

## Phase 7 — 60-minute deployed-service soak (500-switch memory measurement)

- Launched 00:19:09 BST against the live service (engine PID 24361):
  `soak_guard.py --duration 3600` (RSS/temp every 5 s), 500 OSC `/key (5,1)`
  mode switches at 7.2 s cadence, status.json sampler every 60 s.
- Guard semantics note: at duration end the guard SIGTERMs the target by
  design; against the deployed service this causes one systemd auto-restart,
  verified after collection.

### Early-stop partials

- Stopped at 53.7 min / 446 of 500 switches (89%) to wrap the session early;
  the collector was cancelled and the device-side guard/drivers killed (note:
  a `pkill -f` pattern matched the controlling SSH shell once - use
  `pkill -f "pat[t]ern"` self-match-proof patterns).
- **Memory growth: +248 KiB** (first-5-min median 69.9 MiB → last-5-min 70.2
  MiB, peak 70.4 MiB against the 256 MiB guard limit), 645 guard samples.
  Temperature peak 58.0 °C. All 446 switches landed (`reloads=447`), zero mode
  errors, zero audio drops, steady-state fps ~60. The full 60-min/500-switch
  formality still needs one clean rerun, but the memory-growth question is
  effectively answered (cf. the 78.6-min native soak's 80 KiB).

## Phase 8 — second KMS release + KMS↔KMS rollback (roadmap #2 closed)

- Deployed `dev-c2f150be2380` (built by the fixed bootstrap): transactional
  activation passed health (frames advancing, VC4 V3D 2.1, audio clean);
  `previous.json` → `dev-cf8b1ee8013f`.
- `rollback --target previous` → cf8b healthy: **first successful
  previous-release rollback ever** (previously impossible; the only earlier
  candidate, dd42, is Xorg-era and rejected). `previous.json` → c2f1.
- `rollback --target previous` again → back to c2f1, `previous.json` → cf8b.
  Both directions live-proven between KMS releases; recovery on any failure
  is deterministic.
- **Final device state**: `dev-c2f150be2380` active (60.4 fps, VC4 V3D 2.1),
  previous = `dev-cf8b1ee8013f`, stock idle, dongle content YAVG 30.26,
  `VID_CTL 0xc0000000`. No latched samples the entire session (the one
  unexplained-looking 0x401c0000 block in the oracle log correlates with the
  phase-4 sink-disconnected window; healthy 0xc0000000 resumed on HPD return).

## 1080p viability (Plan1080p agent, see local/reports/1080p-plan-2026-09-15/)

- **Scanout: reachable.** The sink's EDID exposes 1920x1080 kernel modes and
  the KMS/GBM path can drive them (engine currently prefers 1280x720 55–65 Hz,
  silent fallback to modes[0] — kms_window.cpp:253-263; needs a loud fallback
  regardless).
- **Native 1080p60 for all modes: not viable.** Four of seven modes already
  miss 60 fps at 720p under shared stock-video load (measured p50: aurora
  22.79 ms, shader 25.79 ms, feedback 29.73 ms, echo-feedback 29.66 ms);
  2.25× fill scaling puts those at roughly 15–25 fps. starter/stereo-mesh/
  prism-mesh are plausible at 1080p60 but vsync-capped, so headroom is
  unproven without a measured offscreen 1080p pass.
- Engine changes for a 1080p trial are small and localized: canvas FBO size
  (main.cpp:422-428), `loadMode(…, 1280, 720)` (main.cpp:168), GLFW/offscreen
  window paths (main.cpp:797,800), KMS mode preference, plus 720p-tuned
  composition constants in four modes and the documented API contract
  (docs/API.md:13,68).
- Recommendation: keep 720p as the mode render resolution; native 1080p is a
  sharpness win only for the cheap modes and needs the fill-scaling calibration
  + offscreen 1080p cost pass from the agent's measurement plan first. Full
  analysis: local/reports/1080p-plan-2026-09-15/analysis.md.

## Local infrastructure (agents, verified)

- **bootstrap --arm arch defect (roadmap #4) FIXED**: the pinned digest
  `5ae3c39…` was the *single-arch amd64 manifest of the bookworm-slim index*
  (config history shows the debuerreproducibility slim build), so `podman
  build --arch arm` could never select arm content. Re-pinned to the slim
  **multi-arch OCI index** `88200866…` (contains arm v7) + `EXPECTED_ARCH`
  build-arg asserted against `dpkg --print-architecture` in the Containerfile.
  Both images rebuilt from scratch; `dpkg --print-architecture` verified inside
  each; `eyesyctl build --arm` → `eyesy-armhf` is ARM EABI5; private runtime
  libs ARM; desktop build still x86-64; `package --arm` produced
  **`dev-c2f150be2380`** — a second KMS-capable release candidate.
- Evidence: `local/reports/bootstrap-arm-2026-09-15/`.

## Remaining for hands/bench

- §3 physical knobs/trigger/scene/MIDI + disconnect/reconnect.
- §4 known stereo signal through the physical codec.
- §6 visible-latency feel; cold-boot recovery confirmation (one power cycle).
- Final acceptance on a real HDMI display (dongle chain is qualified, but a
  real display remains recommended).
