#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Record deterministic provenance for an existing EYESY build artifact."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARCH = {"amd64": (2, 62), "armhf": (1, 40)}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def elf_arch(path):
    with path.open("rb") as stream:
        data = stream.read(64)
    if len(data) < 20 or data[:4] != b"\x7fELF" or data[5] != 1:
        return None
    return next(
        (name for name, pair in ARCH.items() if (data[4], int.from_bytes(data[18:20], "little")) == pair),
        None,
    )


def image_info(image, arch):
    raw = subprocess.check_output(["podman", "image", "inspect", image], text=True)
    info = json.loads(raw)[0]
    actual_arch = info.get("Architecture") or info.get("OsArch")
    if not actual_arch:
        raise RuntimeError("Podman image architecture is missing")
    if actual_arch not in (arch, "x86_64" if arch == "amd64" else "arm"):
        raise RuntimeError("Container image architecture mismatch: " + str(actual_arch))
    digest = info.get("Digest") or (info.get("RepoDigests") or [""])[0]
    if not digest:
        raise RuntimeError("Podman image has no immutable digest")
    return {
        "name": image,
        "id": info.get("Id", info.get("ID")),
        "digest": digest,
        "architecture": actual_arch or arch,
    }


def package_lock(image, arch):
    # Read the lock from the image without pulling or rebuilding it.
    data = subprocess.check_output(
        [
            "podman",
            "run",
            "--rm",
            "--pull=never",
            "--arch",
            "arm" if arch == "armhf" else "amd64",
            image,
            "cat",
            "/build-packages.lock",
        ]
    )
    return {"sha256": hashlib.sha256(data).hexdigest(), "contents": data.decode()}


def engine_sources(root=ROOT):
    paths = list((root / "engine/src").rglob("*")) + [
        root / "engine/Makefile",
        root / "engine/config.make",
        root / "engine/addons.make",
    ]
    return {str(p.relative_to(root)): sha256(p) for p in sorted(paths) if p.is_file()}


def sdk_patches(root=ROOT):
    return {str(p.relative_to(root)): sha256(p) for p in sorted((root / "tools").glob("of-*.patch"))}


def provenance(arm=False, binary=None, output=None):
    arch = "armhf" if arm else "amd64"
    image = "localhost/eyesy-build:armhf" if arm else "localhost/eyesy-build:bookworm"
    binary = Path(binary or (ROOT / ("engine/bin/eyesy-armhf" if arm else "engine/bin/engine")))
    if not binary.is_file():
        raise RuntimeError("Built binary not found: " + str(binary))
    if elf_arch(binary) != arch:
        raise RuntimeError("Built binary architecture does not match " + arch)
    runtime = {}
    if arm:
        for name in ("libstdc++.so.6", "libgcc_s.so.1"):
            path = ROOT / "local/runtime-arm" / name
            if not path.is_file():
                raise RuntimeError("Missing ARM private runtime library: " + str(path))
            runtime[name] = sha256(path)
    lock_path = ROOT / "dependencies.lock.json"
    lock = json.loads(lock_path.read_text())
    sdk = lock["openframeworks"]
    sdk_key = "armhf" if arm else "desktop"
    archive = ROOT / (
        ".cache/downloads/of-0.12.1-armhf.tar.gz" if arm else ".cache/downloads/of-0.12.1-linux64.tar.gz"
    )
    patches = sdk_patches()
    source = engine_sources()
    result = {
        "schema_version": 1,
        "architecture": arch,
        "image": image_info(image, arch),
        "build_packages_lock": package_lock(image, arch),
        "sdk_lock": {
            "version": sdk["version"],
            "url": sdk[sdk_key + "_url"],
            "sha256": sdk[sdk_key + "_sha256"],
            "archive_present": archive.is_file(),
            "archive_sha256": sha256(archive) if archive.is_file() else None,
        },
        "patches": patches,
        "engine_sources": source,
        "private_runtime_libraries": runtime,
        "binary": {"path": str(binary.relative_to(ROOT)), "sha256": sha256(binary)},
    }
    output = Path(output or ROOT / "build" / ("provenance-armhf.json" if arm else "provenance-amd64.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(provenance(args.arm, args.binary, args.output), indent=2, sort_keys=True))
    except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as e:
        print("provenance: " + str(e), file=sys.stderr)
        raise SystemExit(1)
