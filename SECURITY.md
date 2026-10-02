# Security

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's
[security advisories](https://github.com/BrettKinny/eyesy-platform/security/advisories/new)
for this repository. Please don't open a public issue for them.

## Trust model

- **Modes are trusted code.** A mode is Lua that runs inside the engine with
  the full LuaJIT standard library, including `os`, `io` and `ffi`. It can do
  anything the engine's user (`music` on the device) can. Only install modes
  you trust.
- **Deployment uses root on the device.** `eyesyctl provision`, `deploy` and
  `rollback` connect over SSH as `music`, with strict host key checking, and
  run the installer with `sudo -n`. Anyone who can run these commands against a
  device controls it.
- The engine's OSC control port listens on loopback only.
