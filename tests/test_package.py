# SPDX-License-Identifier: BSD-3-Clause
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader(
    "eyesyctl_package_test", str(Path(__file__).parents[1] / "eyesyctl")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
ctl = importlib.util.module_from_spec(spec)
loader.exec_module(ctl)


class PackageTests(unittest.TestCase):
    def fixture(self, root):
        (root / "engine/bin").mkdir(parents=True)
        (root / "engine/bin/engine").write_bytes(b"fixture binary")
        (root / "modes/starter").mkdir(parents=True)
        (root / "modes/starter/main.lua").write_text("return {}")
        (root / "dependencies.lock.json").write_text("{}")
        (root / "LICENSE").write_text("licence")
        (root / "THIRD_PARTY_NOTICES.md").write_text("notices")

    def package(self, root, version=None):
        with (
            patch.object(ctl, "ROOT", root),
            patch.object(ctl.subprocess, "check_output", return_value="ELF 64-bit x86-64"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ctl.package(version=version)

    def commit_all(self, root):
        (root / ".gitignore").write_text("dist/\n")
        git = [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
        ]
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
            subprocess.run(git + args, check=True)
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

    def manifest(self, archive):
        import tarfile

        with tarfile.open(archive) as tar:
            return json.load(tar.extractfile(next(n for n in tar.getnames() if n.endswith("/manifest.json"))))

    def test_version_names_release_and_records_platform_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            commit = self.commit_all(root)
            self.package(root, version="v0.1.0")
            manifest = self.manifest(root / "dist/v0.1.0-amd64.tar.gz")
            self.assertEqual(manifest["release"], "v0.1.0")
            self.assertEqual(manifest["sources"]["platform"], {"commit": commit, "dirty": False})

    def test_dev_package_records_unknown_platform_outside_git(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.package(root)
            manifest = self.manifest(next((root / "dist").glob("dev-*.gz")))
            self.assertEqual(manifest["sources"], {"platform": None, "packs": {}})

    def test_version_rejects_malformed_name(self):
        for version in ("0.1.0", "v0.1", "v0.1.0/../x", "latest"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.fixture(root)
                with self.assertRaisesRegex(RuntimeError, "--version"):
                    self.package(root, version=version)

    def test_pack_revision_counts_ignored_files_that_would_ship(self):
        with tempfile.TemporaryDirectory() as temp:
            pack = Path(temp)
            (pack / "wave").mkdir()
            (pack / "wave/main.lua").write_text("return {}")
            self.commit_all(pack)
            (pack / ".gitignore").write_text("dist/\n.eyesy-no-ship\n__pycache__/\n")
            subprocess.run(["git", "-C", str(pack), "add", ".gitignore"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(pack),
                    "-c",
                    "user.name=t",
                    "-c",
                    "user.email=t@t",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-q",
                    "-m",
                    "ignore",
                ],
                check=True,
            )
            (pack / "__pycache__").mkdir()
            self.assertFalse(ctl.mode_packs.git_revision(pack, [pack / "wave"])["dirty"])
            (pack / "wave/.eyesy-no-ship").write_text("")
            self.assertFalse(ctl.mode_packs.git_revision(pack)["dirty"])
            self.assertTrue(ctl.mode_packs.git_revision(pack, [pack / "wave"])["dirty"])

    def test_version_rejects_unclean_sources(self):
        for change in ("no-git", "dirty-platform", "dirty-pack", "unknown-pack", "edited-mode"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.fixture(root)
                (root / "modes/.gitignore").write_text("*\n!.gitignore\n!starter/\n!starter/**\n")
                if change != "no-git":
                    self.commit_all(root)
                (root / "modes/wave").mkdir()
                (root / "modes/wave/main.lua").write_text("return {}")
                pack = {"commit": "abc", "dirty": change == "dirty-pack"}
                catalog = {
                    "synced": {
                        "wave": {
                            "pack": "eyesy-modes-x",
                            "sha256": ctl.mode_packs.tree_digest(root / "modes/wave"),
                        }
                    },
                    "packs": {"eyesy-modes-x": None if change == "unknown-pack" else pack},
                }
                (root / "modes/.catalog.json").write_text(json.dumps(catalog))
                if change == "dirty-platform":
                    (root / "LICENSE").write_text("edited")
                elif change == "edited-mode":
                    (root / "modes/wave/main.lua").write_text("return { edited = true }")
                expected = "changed since" if change == "edited-mode" else "clean, committed"
                with self.assertRaisesRegex(RuntimeError, expected):
                    self.package(root, version="v0.1.0")

    def test_version_rejects_packs_outside_the_release_set(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "modes/.gitignore").write_text("*\n!.gitignore\n!starter/\n!starter/**\n")
            self.commit_all(root)
            (root / "modes/wave").mkdir()
            (root / "modes/wave/main.lua").write_text("return {}")
            catalog = {
                "synced": {
                    "wave": {
                        "pack": "eyesy-modes-private",
                        "sha256": ctl.mode_packs.tree_digest(root / "modes/wave"),
                    }
                },
                "packs": {"eyesy-modes-private": {"commit": "abc", "dirty": False}},
            }
            (root / "modes/.catalog.json").write_text(json.dumps(catalog))
            with self.assertRaisesRegex(RuntimeError, "also synced: eyesy-modes-private"):
                self.package(root, version="v0.1.0")
            with patch.object(ctl, "RELEASE_PACKS", ("eyesy-modes-private",)):
                self.package(root, version="v0.1.0")
            self.assertTrue((root / "dist/v0.1.0-amd64.tar.gz").is_file())

    def test_byte_reproducible_despite_source_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.package(root)
            artifact = next((root / "dist").glob("*.gz"))
            before = artifact.read_bytes()
            os.utime(root / "modes/starter/main.lua", (100, 100))
            self.package(root)
            self.assertEqual(before, artifact.read_bytes())

    def test_release_carries_licence_and_notices_but_not_fmod(self):
        import tarfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "engine/bin/libfmod.so").write_bytes(b"proprietary")
            self.package(root)
            with tarfile.open(next((root / "dist").glob("*.gz"))) as tar:
                names = {name.split("/", 1)[1] for name in tar.getnames() if "/" in name}
                manifest = json.load(
                    tar.extractfile(next(n for n in tar.getnames() if n.endswith("/manifest.json")))
                )
            self.assertLessEqual({"LICENSE", "THIRD_PARTY_NOTICES.md"}, names)
            self.assertLessEqual({"LICENSE", "THIRD_PARTY_NOTICES.md"}, set(manifest["files"]))
            self.assertNotIn("libfmod.so", names)

    def test_dependency_metadata_changes_release_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.package(root)
            (root / "dependencies.lock.json").write_text('{"changed": true}')
            self.package(root)
            self.assertEqual(len(list((root / "dist").glob("*.gz"))), 2)

    def test_rejects_mode_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "modes/starter/escape").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                self.package(root)

    def test_rejects_wrong_build_architecture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with (
                patch.object(ctl, "ROOT", root),
                patch.object(ctl.subprocess, "check_output", return_value="ELF 32-bit ARM,"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Expected amd64"):
                    ctl.package()

    def test_rejects_new_deleted_or_changed_source_and_patch(self):
        from tools import build_provenance

        for change in ("new-source", "deleted-source", "changed-source", "new-patch", "changed-patch"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.fixture(root)
                (root / "engine/src").mkdir()
                source = root / "engine/src/main.cpp"
                source.write_text("original")
                (root / "tools").mkdir()
                sdk_patch = root / "tools/of-test.patch"
                sdk_patch.write_text("patch")
                (root / "build").mkdir()
                metadata = {
                    "binary": {"sha256": ctl.digest(root / "engine/bin/engine")},
                    "engine_sources": build_provenance.engine_sources(root),
                    "patches": build_provenance.sdk_patches(root),
                }
                (root / "build/provenance-amd64.json").write_text(json.dumps(metadata))
                if change == "new-source":
                    (root / "engine/src/new.cpp").write_text("new")
                elif change == "deleted-source":
                    source.unlink()
                elif change == "changed-source":
                    source.write_text("modified")
                elif change == "new-patch":
                    (root / "tools/of-new.patch").write_text("new")
                else:
                    sdk_patch.write_text("modified")
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    self.package(root)

    def test_rejects_unsafe_provenance_path_before_read(self):
        for path in ("/etc/passwd", "../escape"):
            with self.subTest(path=path), patch.object(ctl, "digest") as digest:
                with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                    ctl.verify_hash_set({"engine_sources": {path: "hash"}}, "engine_sources", {path: "hash"})
                digest.assert_not_called()

    def test_arm_package_bundles_private_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            arm = bytearray(64)
            arm[:4] = b"\x7fELF"
            arm[4:6] = bytes((1, 1))
            arm[18:20] = (40).to_bytes(2, "little")
            (root / "engine/bin/eyesy-armhf").write_bytes(arm)
            runtime = root / "local/runtime-arm"
            runtime.mkdir(parents=True)
            (runtime / "libstdc++.so.6").write_bytes(b"stdc")
            (runtime / "libgcc_s.so.1").write_bytes(b"gcc")
            (root / "build").mkdir()
            import hashlib
            import json

            (root / "build/provenance-armhf.json").write_text(
                json.dumps(
                    {
                        "binary": {"sha256": hashlib.sha256(bytes(arm)).hexdigest()},
                        "engine_sources": {},
                        "patches": {},
                        "private_runtime_libraries": {
                            "libstdc++.so.6": hashlib.sha256(b"stdc").hexdigest(),
                            "libgcc_s.so.1": hashlib.sha256(b"gcc").hexdigest(),
                        },
                    }
                )
            )
            with (
                patch.object(ctl, "ROOT", root),
                patch.object(ctl.subprocess, "check_output", return_value="ELF 32-bit ARM,"),
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    ctl.package(arm=True)
            archive = next((root / "dist").glob("*.gz"))
            import tarfile

            with tarfile.open(archive) as tar:
                self.assertEqual(
                    tar.extractfile(
                        next(n for n in tar.getnames() if n.endswith("/libs/libstdc++.so.6"))
                    ).read(),
                    b"stdc",
                )
