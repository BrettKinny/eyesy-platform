# SPDX-License-Identifier: BSD-3-Clause
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("prepare_clone", ROOT / "tools/prepare_clone.py")
prepare_clone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_clone)


class CloneSafetyTests(unittest.TestCase):
    def test_stock_os_release_relative_symlink_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            (root / "etc").mkdir(parents=True)
            (root / "usr/lib").mkdir(parents=True)
            (root / "home/music/EYESY_OS").mkdir(parents=True)
            (root / "usr/lib/os-release").write_text("ID=raspbian\n")
            (root / "etc/os-release").symlink_to("../usr/lib/os-release")
            key = Path(temp) / "key"
            key.write_text("deliberately-invalid")
            with mock.patch.object(Path, "is_mount", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "PUBLIC key"):
                    prepare_clone.prepare(root, key)

    def test_os_release_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            (root / "etc").mkdir(parents=True)
            (root / "etc/os-release").symlink_to("/etc/os-release")
            with mock.patch.object(Path, "is_mount", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "escapes the offline root"):
                    prepare_clone.prepare(root, Path(temp) / "key")

    def test_root_symlink_is_rejected_before_mount_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            link = Path(temp) / "root"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                prepare_clone.prepare(link, Path("/etc/hosts"))

    def test_key_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / "key"
            key.symlink_to("/etc/hosts")
            root = Path(temp) / "root"
            root.mkdir()
            with mock.patch.object(Path, "is_mount", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "Public key path"):
                    prepare_clone.prepare(root, key)


if __name__ == "__main__":
    unittest.main()
