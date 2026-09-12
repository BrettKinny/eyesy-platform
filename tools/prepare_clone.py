#!/usr/bin/env python3
"""Enable key-authenticated SSH on an OFFLINE, mounted EYESY development clone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

def prepare(root, public_key):
    root = Path(root)
    if root.is_symlink():
        raise RuntimeError('Root must not be a symlink')
    root = root.resolve()
    if root in (Path('/'), Path('/home'), Path('/tmp')) or not root.is_mount():
        raise RuntimeError('Root must be the exact mounted root partition of the spare EYESY card')
    if public_key.is_symlink():
        raise RuntimeError('Public key path must not be a symlink')
    for relative in ('etc', 'etc/passwd', 'usr', 'home', 'home/music', 'home/music/EYESY_OS'):
        candidate = root / relative
        if candidate.is_symlink():
            raise RuntimeError('Refusing symlinked offline path: ' + relative)
    # Stock Raspbian uses ../usr/lib/os-release. Allow that read-only link
    # only when resolution remains inside the mounted card.
    os_release_path = (root / 'etc/os-release').resolve()
    if not os_release_path.is_relative_to(root):
        raise RuntimeError('os-release escapes the offline root')
    os_release = os_release_path.read_text()
    if 'raspbian' not in os_release.lower() or not (root / 'home/music/EYESY_OS').is_dir():
        raise RuntimeError('This is not an identifiable EYESY Raspbian root filesystem')
    key = public_key.read_text().strip()
    if not key.startswith(('ssh-ed25519 ', 'ssh-rsa ', 'ecdsa-sha2-')) or '\n' in key:
        raise RuntimeError('Provide one SSH PUBLIC key, never a private key')
    if not (root / 'usr/sbin/sshd').is_file() or (root / 'usr/sbin/sshd').is_symlink():
        raise RuntimeError('Clone lacks openssh-server; install it before enabling SSH')
    marker = root / 'etc/eyesy-development-clone'
    if marker.is_symlink() or marker.exists():
        raise RuntimeError('Clone is already prepared; inspect its marker before changing access')
    passwd = [line.split(':') for line in (root / 'etc/passwd').read_text().splitlines()]
    music = next(p for p in passwd if len(p) > 3 and p[0] == 'music')
    uid, gid = int(music[2]), int(music[3])
    keydir = root / 'home/music/.ssh'
    if keydir.is_symlink():
        raise RuntimeError('Refusing a symlinked .ssh directory')
    keydir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(keydir, 0o700); os.chown(keydir, uid, gid)
    authorized = keydir / 'authorized_keys'
    if authorized.is_symlink():
        raise RuntimeError('Refusing symlinked authorized_keys')
    if authorized.exists() and not authorized.is_file():
        raise RuntimeError('authorized_keys must be a regular file')
    old = authorized.read_text() if authorized.exists() else ''
    if old: shutil.copy2(authorized, keydir / 'authorized_keys.before-eyesy-platform')
    authorized.write_text(old.rstrip() + ('\n' if old else '') + key + '\n')
    os.chmod(authorized, 0o600); os.chown(authorized, uid, gid)
    unit = root / 'etc/systemd/system/ssh.service'
    if unit.exists() and not unit.is_symlink() and not unit.is_file():
        raise RuntimeError('ssh.service must be a regular file or symlink')
    previous = os.readlink(unit) if unit.is_symlink() else 'file' if unit.exists() else 'absent'
    subprocess.run(['systemctl', '--root', str(root), 'unmask', 'ssh.service'], check=True)
    subprocess.run(['systemctl', '--root', str(root), 'enable', 'ssh.service'], check=True)
    subprocess.run(['ssh-keygen', '-A', '-f', str(root)], check=True)
    receipt = {'schema_version': 1, 'clone_id': str(uuid.uuid4()), 'previous_ssh_unit': previous,
               'public_key_sha256': hashlib.sha256(key.encode()).hexdigest()}
    marker.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root, args.public_key)
