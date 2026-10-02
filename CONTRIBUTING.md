# Contributing

Pull requests and issues are welcome.

## Build and test

You need Linux, Python 3.9+, CMake, Ninja and a C++17 compiler. The full engine
builds in a Podman container against a checksummed openFrameworks SDK:

```sh
./eyesyctl bootstrap          # build container + SDK (once)
./eyesyctl build
./eyesyctl test               # core C++ tests and Python unit tests
./eyesyctl test --graphics    # also renders through the engine (needs the build)
```

`./eyesyctl test` without `--graphics` needs only CMake, Ninja, g++ and Python,
and is what CI runs. See [README.md](README.md) for previews and device builds.

## Mode packs

Modes live in separate `eyesy-modes-*` repositories, cloned beside this one.
This repo ships only the `starter` mode. Changes to a pack's modes go to that
pack's repository.

## Style

- Python: [ruff](https://docs.astral.sh/ruff/), configured in `ruff.toml`. Run
  `uvx ruff format` and `uvx ruff check` before sending a change.
- C++: `.clang-format` (LLVM base, 4-space indent, 100 columns). CI checks every
  tracked C++ file with clang-format 23.1.2; run
  `git ls-files -z '*.cpp' '*.h' | xargs -0 uvx clang-format==23.1.2 -i` before
  sending a change.

Keep commits focused, and add or update tests for behaviour changes.

## Device testing

Changes to the KMS display path, audio input, controls, deploy or rollback need
an EYESY to verify. If you don't have one, say so in the pull request and
describe what you tested on the desktop.
