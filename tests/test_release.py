# SPDX-License-Identifier: BSD-3-Clause
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import fcntl
from unittest import mock

spec = importlib.util.spec_from_file_location("release", Path(__file__).parents[1] / "tools/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def archive(self, temp, corrupt=False, traversal=False):
        path = Path(temp) / "release.tar.gz"
        # Minimal ELF64 x86-64 header (the verifier checks the binary, not
        # merely the manifest's architecture field).
        binary = bytearray(64)
        binary[:4] = b"\x7fELF"
        binary[4:6] = bytes((2, 1))
        binary[18:20] = (62).to_bytes(2, "little")
        binary = bytes(binary)
        manifest = {
            "schema_version": 1,
            "release": "test",
            "architecture": "amd64",
            "files": {"eyesy-engine": hashlib.sha256(binary).hexdigest()},
        }
        with tarfile.open(path, "w:gz") as tar:
            for name, data in [
                ("test/eyesy-engine", b"bad" if corrupt else binary),
                ("test/manifest.json", json.dumps(manifest).encode()),
            ]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            if traversal:
                info = tarfile.TarInfo("test/../../escaped")
                info.size = 0
                tar.addfile(info, io.BytesIO())
        return path

    def test_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(release.verify(self.archive(temp), "amd64")["release"], "test")

    def test_wrong_architecture(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "architecture"):
                release.verify(self.archive(temp), "armhf")

    def test_modified_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "Checksum"):
                release.verify(self.archive(temp, corrupt=True))

    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                release.verify(self.archive(temp, traversal=True))

    def test_manifest_cannot_lie_about_elf(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.archive(temp)
            # Rebuild the archive with the same checksum but an ARM ELF.
            arm = bytearray(64)
            arm[:4] = b"\x7fELF"
            arm[4:6] = bytes((1, 1))
            arm[18:20] = (40).to_bytes(2, "little")
            manifest = {
                "schema_version": 1,
                "release": "test",
                "architecture": "amd64",
                "files": {"eyesy-engine": hashlib.sha256(bytes(arm)).hexdigest()},
            }
            with tarfile.open(path, "w:gz") as tar:
                for name, data in [
                    ("test/eyesy-engine", bytes(arm)),
                    ("test/manifest.json", json.dumps(manifest).encode()),
                ]:
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            with self.assertRaisesRegex(ValueError, "architecture"):
                release.verify(path)

    def test_noncanonical_member_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.archive(temp)
            alias = Path(temp) / "alias.tar.gz"
            with tarfile.open(path) as source, tarfile.open(alias, "w:gz") as target:
                for member in source.getmembers():
                    if member.name == "test/eyesy-engine":
                        member.name = "test//eyesy-engine"
                    data = source.extractfile(member).read() if member.isfile() else None
                    target.addfile(member, io.BytesIO(data) if data is not None else None)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                release.verify(alias)

    def test_release_name_cannot_inject_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.archive(temp)
            renamed = Path(temp) / "bad.tar.gz"
            with tarfile.open(path) as source, tarfile.open(renamed, "w:gz") as target:
                for member in source.getmembers():
                    member.name = member.name.replace("test/", "bad\nEYESY_RELEASE=x/")
                    data = source.extractfile(member).read() if member.isfile() else None
                    target.addfile(member, io.BytesIO(data) if data is not None else None)
            with self.assertRaisesRegex(ValueError, "Unsafe|Invalid release"):
                release.verify(renamed)

    def test_deployment_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as temp:
            first = release.acquire_lock(Path(temp))
            second = (Path(temp) / ".deployment.lock").open("a+")
            with self.assertRaises(BlockingIOError):
                fcntl.flock(second.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            first.close()
            fcntl.flock(second.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            second.close()

    def test_root_identity_is_checked_before_lock(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(release, "check_clone", side_effect=ValueError("identity")),
        ):
            with mock.patch.object(release, "acquire_lock") as acquire:
                with self.assertRaisesRegex(ValueError, "identity"):
                    release.activate(Path(temp) / "missing.tar.gz", "wrong", Path(temp) / "platform")
                acquire.assert_not_called()
