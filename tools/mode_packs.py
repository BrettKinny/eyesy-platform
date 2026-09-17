"""Mode packs: scene collections that live in their own repositories.

The engine repo owns exactly one mode, ``starter`` -- the contract baseline the
deployed service starts on. Every other mode lives in a sibling "mode pack"
repository: a flat collection of mode folders, the same shape a PatchStorage
upload and the stock EYESY ``/sdcard/Modes`` directory use.

``sync()`` assembles the packs into ``modes/`` so the packager ships one flat
catalog; ``find()`` resolves a single mode by name for tests and previews,
searching ``modes/`` first and then every pack, so neither depends on a prior
sync.

Pack roots come from, in order: an explicit ``roots`` argument, the
``EYESY_MODE_PACKS`` colon-separated environment variable (the build container
mounts them), or every ``eyesy-modes-*`` sibling directory of this repo.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
MODES_ROOT = ROOT / 'modes'
MODE_NAME = re.compile(r'[a-z0-9][a-z0-9._-]*')
# A mode folder carrying this marker is authored content that must not ship.
# `zzprobe` is the current case: a scratch diagnostic the docs excluded from
# releases while `package` still copied it.
NO_SHIP = '.eyesy-no-ship'
CATALOG = '.catalog.json'
ENGINE_OWNED = 'starter'


def pack_roots(overrides=()):
    if overrides:
        return [Path(p).expanduser().resolve() for p in overrides]
    declared = os.environ.get('EYESY_MODE_PACKS')
    if declared:
        return [Path(p).resolve() for p in declared.split(':') if p]
    return sorted(p for p in ROOT.parent.glob('eyesy-modes-*') if p.is_dir())


def discover(root):
    """Mode folders in one pack root, keyed by folder name."""
    found = {}
    root = Path(root)
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith('.'):
            continue
        if not (entry / 'main.lua').is_file():
            continue
        if not MODE_NAME.fullmatch(entry.name):
            raise RuntimeError(f'{root.name}: unsafe mode folder name {entry.name!r}')
        found[entry.name] = entry
    return found


def shippable(mode_dir):
    """False for authored-but-unshippable modes (scratch probes, WIP gates)."""
    return not (Path(mode_dir) / NO_SHIP).exists()


def tree_digest(path):
    value = hashlib.sha256()
    for item in sorted(Path(path).rglob('*')):
        if item.is_symlink() or not item.is_file():
            continue
        value.update(str(item.relative_to(path)).encode() + b'\0')
        value.update(item.read_bytes())
    return value.hexdigest()


def sources(roots=()):
    """Resolve every mode in every pack; rejects duplicates across packs."""
    located, owner = {}, {}
    for root in pack_roots(roots):
        for name, path in discover(root).items():
            if name in located:
                raise RuntimeError(f'mode {name!r} exists in two packs: '
                                   f'{owner[name].name} and {root.name}')
            if name == ENGINE_OWNED:
                raise RuntimeError(f'{ENGINE_OWNED} is engine-owned and must not live in a pack ({root.name})')
            located[name], owner[name] = path, root
    return {name: (path, owner[name]) for name, path in located.items()}


def read_catalog(modes_root=None):
    path = (Path(modes_root) if modes_root else MODES_ROOT) / CATALOG
    if not path.is_file():
        return {'synced': {}}
    return json.loads(path.read_text())


def sync(roots=(), modes_root=None):
    """Assemble every pack into `modes/`; prune modes whose pack entry is gone.

    Directories sync did not create are left alone, so a hand-authored mode
    under `modes/` survives.
    """
    modes_root = Path(modes_root) if modes_root else MODES_ROOT
    modes_root.mkdir(parents=True, exist_ok=True)
    located = sources(roots)
    previous = read_catalog(modes_root).get('synced', {})
    added, updated, removed = [], [], []
    for name, (source, pack) in sorted(located.items()):
        destination = modes_root / name
        digest = tree_digest(source)
        if not (destination / 'main.lua').is_file():
            added.append(name)
        elif tree_digest(destination) != digest:
            updated.append(name)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    for name in sorted(set(previous) - set(located)):
        stale = modes_root / name
        if stale.is_dir():
            shutil.rmtree(stale)
        removed.append(name)
    catalog = {name: {'pack': pack.name, 'sha256': tree_digest(modes_root / name)}
               for name, (source, pack) in sorted(located.items())}
    (modes_root / CATALOG).write_text(json.dumps({'synced': catalog}, indent=2, sort_keys=True) + '\n')
    return {'roots': [str(r) for r in pack_roots(roots)], 'added': added,
            'updated': updated, 'removed': removed, 'catalog': catalog}


def find(name, modes_root=None):
    """Resolve one mode folder by name; `modes/` first, then every pack."""
    modes_root = Path(modes_root) if modes_root else MODES_ROOT
    local = modes_root / name
    if (local / 'main.lua').is_file():
        return local
    matches = [path for path, _ in sources().values() if path.name == name]
    return matches[0] if matches else None
