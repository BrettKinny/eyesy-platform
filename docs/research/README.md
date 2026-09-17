# Research corpus — index

This directory no longer holds the corpus. Each scene collection now carries the
research that produced it, alongside the scenes it describes:

| Repo | Corpus |
| --- | --- |
| `eyesy-modes-bespoke` | `docs/research/` — 21 dossiers: scene-family research, the library architecture, lead-hunting passes, and the per-scene bardo/lineage briefs |
| `eyesy-modes-milkdrop` | `docs/research/` — MilkDrop3 portability, the Winamp/AVS lineage, the BeatDrop fork assessment |
| `eyesy-modes-factory` | `docs/research/` — the EYESY ecosystem map and the ranked best-of PatchStorage port specs |
| here | `GIFModes.md` — animated-texture research. It drives an engine primitive (frame-sequence upload), so it belongs with the engine |

Provenance: the dossiers came out of research-agent sessions and were tracked
here as `docs/research/` (15 at first, 28 by 2026-09-17) until the scene
collections were split into their own repos, when each dossier moved to the repo
whose scenes it produced. Their commit history stays in this repo's log.

Path conventions inside those dossiers, now that they live elsewhere:

- `modes/<name>/...` resolves under the owning pack's mode folders once
  `./eyesyctl modes sync` has assembled them into `modes/`.
- `docs/API.md`, `docs/SCENE-LIBRARY.md`, `docs/STATUS.md`, `ROADMAP.md` and
  `eyesyctl` refer to **this** repo.
- `docs/research/<sibling>.md` refers to another dossier in the *same* pack,
  except where the text names a repo explicitly.