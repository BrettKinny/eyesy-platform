#!/usr/bin/env python3
"""Verify a release without executing it. Hardware activation is separately gated."""
import argparse
import fcntl
from contextlib import contextmanager
import functools
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import time
import re
import stat

ARCHITECTURES = {
    'armhf': (1, 40),       # ELF32, EM_ARM
    'amd64': (2, 62),       # ELF64, EM_X86_64
}
RELEASE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')

def acquire_lock(base):
    base.mkdir(parents=True, exist_ok=True)
    lock_path = base / '.deployment.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('Deployment lock must be a regular file')
    handle = os.fdopen(fd, 'a+')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except BaseException:
        handle.close()
        raise
    return handle

@contextmanager
def deployment_lock(base):
    handle = acquire_lock(Path(base))
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

def locked(operation):
    @functools.wraps(operation)
    def wrapper(*args, **kwargs):
        is_rollback = operation.__name__ == 'rollback'
        clone_id = kwargs.get('clone_id', args[1] if len(args) > 1 else None)
        check_clone(clone_id)
        base = kwargs.get('base', args[0] if is_rollback and args else args[2] if len(args) > 2 else '/sdcard/eyesy-platform')
        base = validate_base(Path(base))
        with deployment_lock(base):
            return operation(*args, **kwargs)
    return wrapper

def elf_architecture(data):
    """Return the supported architecture encoded by an ELF executable."""
    if len(data) < 20 or data[:4] != b'\x7fELF':
        raise ValueError('eyesy-engine is not an ELF executable')
    ei_class, ei_data = data[4], data[5]
    if ei_data != 1:  # releases are little-endian
        raise ValueError('eyesy-engine has unsupported ELF byte order')
    machine = int.from_bytes(data[18:20], 'little')
    for name, (elf_class, elf_machine) in ARCHITECTURES.items():
        if (ei_class, machine) == (elf_class, elf_machine):
            return name
    raise ValueError('eyesy-engine has unsupported ELF architecture')

def write_atomic(path, content):
    if path.is_symlink():
        raise ValueError('Refusing symlinked state file: ' + str(path))
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content.encode() if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temporary.exists(): temporary.unlink()

def check_clone(clone_id):
    if os.geteuid() != 0:
        raise ValueError('Operation requires root on the clone')
    receipt = json.loads(Path('/etc/eyesy-development-clone').read_text())
    if not clone_id or receipt.get('clone_id') != clone_id:
        raise ValueError('Development clone identity mismatch')
    if 'Compute Module 3 Plus' not in Path('/proc/device-tree/model').read_text():
        raise ValueError('Target is not the validated board model')

def validate_base(base):
    base = Path(base)
    for path in (base, base / 'releases', base / 'active.env', base / 'previous.json'):
        if path.is_symlink(): raise ValueError('Refusing symlinked platform path: ' + str(path))
    if (base / 'current').exists() and not (base / 'current').is_symlink():
        raise ValueError('current is not a release symlink')
    return base

def release_path(base, value):
    path = Path(value)
    if (path.is_symlink() or not path.is_dir()
            or path.resolve().parent != (base / 'releases').resolve()):
        raise ValueError('Recorded release is unavailable or outside releases')
    return path.resolve()

def select_release(base, target):
    current = base / 'current'
    if target is None:
        if current.is_symlink(): current.unlink()
        return
    # A unique temporary symlink avoids following an existing .next path.
    fd, name = tempfile.mkstemp(prefix='.select-', dir=base)
    os.close(fd)
    link = Path(name)
    link.unlink()
    try:
        link.symlink_to(target)
        os.replace(link, current)
    finally:
        if link.is_symlink(): link.unlink()

def wait_healthy(base, release_id, timeout=30):
    deadline = time.monotonic() + timeout
    previous_frame = None
    while time.monotonic() < deadline:
        time.sleep(1)
        try: status = json.loads((base / 'status.json').read_text())
        except (OSError, ValueError): continue
        if status.get('release') != release_id or status.get('error'): continue
        renderer = status.get('renderer', '').lower()
        if not renderer: continue
        if any(name in renderer for name in ('llvmpipe', 'softpipe', 'swrast')):
            raise ValueError('Target is software rendering')
        frame = status.get('frame', 0)
        if not isinstance(frame, int) or frame < 0: continue
        if previous_frame is not None and frame > previous_frame:
            return status
        previous_frame = frame
    raise ValueError('Release failed health/heartbeat checks')

def restore_selection(base, previous, old_env):
    subprocess.run(['systemctl', 'stop', 'eyesy-platform.service'], check=False)
    select_release(base, previous)
    env_path = base / 'active.env'
    if old_env is not None: write_atomic(env_path, old_env)
    elif env_path.exists(): env_path.unlink()
    if previous:
        result = subprocess.run(['systemctl', 'start', 'eyesy-platform.service'], check=False)
        if result.returncode == 0: return
        subprocess.run(['systemctl', 'stop', 'eyesy-platform.service'], check=False)
    subprocess.run(['systemctl', 'start', 'eyesypy.service'], check=True)

def verify(archive, expected_arch=None):
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 512 * 1024 * 1024:
            raise ValueError('Release exceeds file/size budget')
        names = set()
        roots = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or str(path) != member.name or
                any(any(ord(c) < 32 or ord(c) == 127 for c in part) for part in path.parts) or
                '..' in path.parts or not path.parts or member.issym() or member.islnk() or
                not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe archive member')
            if member.name in names: raise ValueError('Duplicate archive member')
            names.add(member.name); roots.add(path.parts[0])
        if len(roots) != 1: raise ValueError('Release must have one root directory')
        root = roots.pop()
        if not RELEASE_RE.fullmatch(root): raise ValueError('Invalid release name')
        handle = tar.extractfile(root + '/manifest.json')
        if not handle: raise ValueError('Missing manifest')
        manifest = json.load(handle)
        if manifest.get('schema_version') != 1 or manifest.get('release') != root:
            raise ValueError('Invalid release manifest')
        if expected_arch and manifest.get('architecture') != expected_arch:
            raise ValueError('Release architecture does not match target')
        declared = manifest.get('files')
        if not isinstance(declared, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in declared.items()):
            raise ValueError('Invalid release file manifest')
        actual = {m.name[len(root)+1:] for m in members if m.isfile() and m.name != root + '/manifest.json'}
        if set(declared) != actual: raise ValueError('Manifest does not cover every file')
        for name, checksum in declared.items():
            stream = tar.extractfile(root + '/' + name)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
            if digest.hexdigest() != checksum: raise ValueError('Checksum mismatch: ' + name)
        if 'eyesy-engine' not in declared: raise ValueError('Missing engine')
        engine = tar.extractfile(root + '/eyesy-engine')
        actual_arch = elf_architecture(engine.read(64))
        if manifest.get('architecture') != actual_arch:
            raise ValueError('Manifest architecture does not match eyesy-engine ELF')
        if expected_arch and actual_arch != expected_arch:
            raise ValueError('eyesy-engine architecture does not match target')
        return manifest

@locked
def activate(archive, clone_id, base=Path('/sdcard/eyesy-platform')):
    """Run on a prepared device as root. Never provisions the stock card."""
    check_clone(clone_id)
    manifest = verify(archive, 'armhf')
    base = validate_base(base)
    releases = base / 'releases'; releases.mkdir(parents=True, exist_ok=True)
    destination = releases / manifest['release']
    if destination.is_symlink(): raise ValueError('Release destination must not be a symlink')
    if destination.exists(): raise ValueError('Release already installed; refusing to overwrite it')
    with tempfile.TemporaryDirectory(prefix='.stage-', dir=releases) as temp:
        stage = Path(temp) / 'release'; stage.mkdir()
        with tarfile.open(archive, 'r:gz') as tar:
            for name in manifest['files']:
                target = stage / name; target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(manifest['release'] + '/' + name) as src, target.open('wb') as out:
                    shutil.copyfileobj(src, out)
                target.chmod(0o755 if name == 'eyesy-engine' else 0o644)
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        result = subprocess.run(['ldd', str(stage / 'eyesy-engine')], capture_output=True, text=True)
        if result.returncode or 'not found' in result.stdout:
            raise ValueError('Runtime dependencies missing; stock engine unchanged:\n' + result.stdout + result.stderr)
        os.rename(stage, destination)
    current = base / 'current'
    if current.exists() and not current.is_symlink(): raise ValueError('current is not a release symlink')
    previous = str(release_path(base, current.resolve())) if current.is_symlink() else None
    def systemctl(*args): subprocess.run(['systemctl', *args], check=True)
    status_path = base / 'status.json'
    env_path = base / 'active.env'
    old_env_exists = env_path.exists()
    old_env = env_path.read_bytes() if old_env_exists else None
    try:
        systemctl('stop', 'eyesy-platform.service')
        systemctl('stop', 'eyesypy.service')
        select_release(base, str(destination))
        # The service reads this at startup, so commit it before starting the
        # candidate.  The exact prior bytes are restored on any failure.
        write_atomic(env_path, 'EYESY_RELEASE=' + manifest['release'] + '\n')
        if status_path.exists(): status_path.unlink()
        systemctl('start', 'eyesy-platform.service')
        status = wait_healthy(base, manifest['release'])
        write_atomic(base / 'previous.json', json.dumps({'release_path': previous}) + '\n')
        return status
    except Exception:
        restore_selection(base, previous, old_env)
        raise

@locked
def rollback(base=Path('/sdcard/eyesy-platform'), clone_id=None, target='previous'):
    """Select the last known-good release recorded by activation."""
    check_clone(clone_id)
    base = validate_base(base)
    if target not in ('previous', 'stock'):
        raise ValueError('Rollback target must be previous or stock')
    record = base / 'previous.json'
    current = base / 'current'
    env_path = base / 'active.env'
    old_env_exists = env_path.exists()
    old_env = env_path.read_bytes() if old_env_exists else None
    old_current = str(release_path(base, current.resolve())) if current.is_symlink() else None
    if target == 'stock':
        try:
            subprocess.run(['systemctl', 'stop', 'eyesy-platform.service'], check=True)
            subprocess.run(['systemctl', 'start', 'eyesypy.service'], check=True)
            select_release(base, None)
            if env_path.exists(): env_path.unlink()
            return {'target': 'stock'}
        except Exception:
            restore_selection(base, old_current, old_env)
            raise
    if not record.exists():
        raise ValueError('No previous release is recorded')
    previous = json.loads(record.read_text()).get('release_path')
    releases = (base / 'releases').resolve()
    previous_path = Path(previous).resolve() if previous else Path()
    if (not previous or previous_path.parent != releases or
            not previous_path.is_dir() or Path(previous).is_symlink()):
        raise ValueError('Recorded previous release is unavailable or unsafe')
    if current.exists() and not current.is_symlink():
        raise ValueError('current is not a release symlink')
    # Parse and validate before stopping the currently running engine.
    manifest = json.loads((previous_path / 'manifest.json').read_text())
    if manifest.get('release') != previous_path.name:
        raise ValueError('Previous release manifest identity mismatch')
    try:
        subprocess.run(['systemctl', 'stop', 'eyesy-platform.service'], check=True)
        subprocess.run(['systemctl', 'stop', 'eyesypy.service'], check=True)
        select_release(base, str(previous_path))
        write_atomic(env_path, 'EYESY_RELEASE=' + manifest['release'] + '\n')
        status_path = base / 'status.json'
        if status_path.exists(): status_path.unlink()
        subprocess.run(['systemctl', 'start', 'eyesy-platform.service'], check=True)
        status = wait_healthy(base, manifest['release'])
        write_atomic(record, json.dumps({'release_path': old_current}) + '\n')
        return status
    except Exception:
        restore_selection(base, old_current, old_env)
        raise

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive'); parser.add_argument('--architecture', choices=['amd64', 'armhf'])
    parser.add_argument('--activate-clone', help='Exact clone ID from offline preparation receipt')
    parser.add_argument('--target', choices=['previous', 'stock'], default='previous')
    args = parser.parse_args()
    if args.archive == 'rollback':
        result = rollback(clone_id=args.activate_clone, target=args.target)
    elif args.activate_clone:
        result = activate(args.archive, args.activate_clone)
    else:
        result = verify(args.archive, args.architecture)
    print(json.dumps(result, indent=2))
