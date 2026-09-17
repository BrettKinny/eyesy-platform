# modes/ is an assembly directory

Only `starter` is committed here — the contract baseline the deployed service
starts on. Every other mode is copied in from a sibling mode-pack repo:

```sh
./eyesyctl modes sync     # assemble; also prunes modes whose pack entry is gone
./eyesyctl modes list     # what the packs hold, and what is refused to ship
```

`sync` is required before `./eyesyctl package` (a release ships one flat `modes/`
catalog and prints it). `./eyesyctl preview` and `./eyesyctl test` resolve modes
across the packs directly and do not need a sync.

A mode folder is self-contained: `main.lua` plus its shaders and assets. The
engine auto-discovers any child folder containing `main.lua`, so the flat layout
here is what the device sees at `/sdcard/Modes`.

`sync` leaves directories it did not create alone, so a hand-authored mode under
`modes/` survives — but it is untracked. Author in a pack repo instead:

```sh
./eyesyctl new-mode my-scene --pack ~/dev/eyesy-modes-bespoke
```

A mode folder containing `.eyesy-no-ship` is copied but excluded from releases
and reported as excluded by `eyesyctl package`.
