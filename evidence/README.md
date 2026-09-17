# Platform evidence

The durable evidence for this engine, in git. Paths mirror where each item was
produced under `local/`, so a doc written as `local/reports/bench-2026-09-15/`
resolves here as `evidence/reports/bench-2026-09-15/`.

## The rule

`local/` is a working directory, not a record. It is gitignored and holds the
SDK runtime trees (`local/runtime`, `local/runtime-arm`), preview scratch, image
grabs, and the full run output of every experiment — about 900 MB here, all of
it regenerable. `evidence/` holds the part worth keeping: the written findings
and the machine-readable results that back the claims in `docs/STATUS.md`,
`ROADMAP.md` and `docs/HDMI-DISPLAY-ISSUE.md`.

Tracked: `*.md`, `*.txt`, `*.log`, `*.jsonl`, every `summary.json` and
`analysis.json`, and `*report*.json` (but not the per-run `report.json`).
Not tracked: image grabs, per-run `experiment.json`/`status.json`/`engine.log`,
release tarballs, and the runtime trees.

The same convention is used by the mode-pack repos, where it is scoped per
scene (`evidence/<scene>/`) instead of per workstream.

## What is here

| Area | What it backs |
| --- | --- |
| `reports/bench-2026-09-15/` | The bench session: rollback qualified in all four paths, recovery path, donor-card work; `REPORT.md` is the finding |
| `reports/soak-2026-09-16/` + `soak-2026-09-16-samples.jsonl` | The 60-minute observe-only soak: zero errors, reload-correlated RSS growth |
| `reports/1080p-plan-2026-09-15/` | The 1080p viability assessment (parked) |
| `reports/hdmi-dongle-stream/`, `reports/vidctl-*.txt`, `reports/vc4-hdmi-regs-*.txt`, `reports/kms-*.{log,txt}`, `reports/stock-after-x-full.txt` | The HDMI_VID_CTL latched-bit investigation |
| `reports/bootstrap-arm-2026-09-15/`, `reports/provision-hygiene-2026-09-15/` | Card provisioning and the ARM bootstrap |
| `overnight/` | The overnight experiment corpus: package rounds, hardware rounds, soak round 1, headless CLI, input workflow, prototypes, sanitizer runs — one `summary.json` per round plus its written findings |

## Deliberately not here

- `local/eyesy_known_hosts` — SSH trust material, machine-specific.
- `local/fresh-card-receipt.json` — the clone UUID receipt for one prepared card.
- The device gate runs for individual scenes: those live with the scenes, in
  `eyesy-modes-bespoke/evidence/<scene>/`.

## Regenerating

Most of this is reproducible output, not unique data:
`./eyesyctl test --graphics`, `tools/scene_verify.py`, `tools/benchmark.py`,
`tools/soak_observe.py` and the `local/overnight/*.py` helpers produce their own
directories under `local/` on each run. Delete `local/` freely; re-run what you
need.
