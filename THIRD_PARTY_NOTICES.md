# Third-party notices

This project's own code is under the BSD 3-Clause License in [LICENSE](LICENSE).
Some parts come from, or are linked against, other projects under their own
licenses.

## Critter & Guitari EYESY OS

The instrument layer reproduces the behaviour of the stock EYESY OS v3
([critterandguitari/EYESY_OS](https://github.com/critterandguitari/EYESY_OS)),
and one table is copied from it directly:

- `engine/src/palette_manager.cpp`: the 43 default cosine palettes, copied
  verbatim from `engines/python/stuff/color_palettes.py`.
- `engine/src/osd_hud.*`, `engine/src/menu_system.*`,
  `engine/src/knob_sequencer.*` and the trigger-tone synthesis in
  `engine/src/audio.cpp`: ported from the stock `osd.py`, the menu screens,
  and `eyesy.py`, and rewritten in C++.

That code is distributed under this license:

```text
Copyright (c) 2025, Owen Osborn, Critter & Guitari, Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## openFrameworks

The engine is built on [openFrameworks](https://openframeworks.cc/) 0.12.1,
which is released under the
[MIT License](https://github.com/openframeworks/openFrameworks/blob/master/LICENSE.md).
The SDK is downloaded and checksummed at build time, not vendored here. The
`tools/of-*.patch` files modify it and are under the same license as the files
they patch.

## LuaJIT

Modes run on [LuaJIT](https://luajit.org/) 2.1 (Lua 5.1 API), under the
[MIT License](https://github.com/LuaJIT/LuaJIT/blob/v2.1/COPYRIGHT). It is
linked from Debian Bookworm's `libluajit-5.1-dev` and not vendored here.

## Binary release archives

`eyesyctl package --arm` includes Debian Bookworm's `libstdc++.so.6` and
`libgcc_s.so.1` so the engine runs on the stock image. They are GCC runtime
libraries under the GPL-3.0 with the GCC Runtime Library Exception. A release
archive also contains openFrameworks and this project's code, so the notices
above apply to it as well.

## Trademarks

EYESY is a trademark of Critter & Guitari, Inc. This project is independent. It
is not affiliated with, endorsed by, or supported by Critter & Guitari.
