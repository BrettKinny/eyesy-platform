#!/usr/bin/env python3
"""Mocked transaction tests for release activation and rollback.

These exercise the real filesystem/link transaction while replacing only root,
board identity, service commands, and time. They are intentionally offline.
"""

import hashlib
import importlib.util
import json
from contextlib import ExitStack
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "tools/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTransactionTests(unittest.TestCase):
    def archive(self, folder, name="candidate"):
        payload = b"engine payload"
        manifest = {
            "schema_version": 1,
            "release": name,
            "architecture": "armhf",
            "files": {"eyesy-engine": hashlib.sha256(payload).hexdigest()},
        }
        path = folder / (name + ".tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            for member, data in (
                (name + "/manifest.json", json.dumps(manifest).encode()),
                (name + "/eyesy-engine", payload),
            ):
                info = tarfile.TarInfo(member)
                info.size = len(data)
                tar.addfile(info, __import__("io").BytesIO(data))
        return path, manifest

    def identity(self, candidate):
        """Patch identity/model checks for both current and helper-based APIs."""
        patches = [mock.patch.object(release.os, "geteuid", return_value=0)]
        if hasattr(release, "check_clone"):
            patches.append(mock.patch.object(release, "check_clone", return_value=None))
        else:
            original = release.Path.read_text

            def read(path, *args, **kwargs):
                if path == Path("/etc/eyesy-development-clone"):
                    return json.dumps({"clone_id": candidate})
                if path == Path("/proc/device-tree/model"):
                    return "Compute Module 3 Plus\0"
                return original(path, *args, **kwargs)

            patches.append(mock.patch.object(release.Path, "read_text", read))
        return patches

    def services(self, base, release_id=None, fail_start=False, renderer="hardware", advance=True):
        calls = []
        status = base / "status.json"
        platform_starts = [0]

        def run(args, **kwargs):
            calls.append((list(args), kwargs))
            if args[0] == "ldd":
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[:2] == ["systemctl", "start"] and args[2] == "eyesy-platform.service":
                if fail_start:
                    if kwargs.get("check"):
                        raise subprocess.CalledProcessError(1, args)
                    return subprocess.CompletedProcess(args, 1, "", "")
                if platform_starts[0] == 0 and not (base / "active.env").exists():
                    raise AssertionError("candidate active.env missing before service start")
                platform_starts[0] += 1
                rid = release_id or json.loads((base / "active.env").read_text()).split("=", 1)[1].strip()
                status.write_text(json.dumps({"release": rid, "frame": 1, "renderer": renderer}))
            return subprocess.CompletedProcess(args, 0, "", "")

        return calls, run

    def healthy_clock(self, base, advance=True):
        status = base / "status.json"

        def sleep(_):
            data = json.loads(status.read_text())
            if advance:
                data["frame"] += 1
            status.write_text(json.dumps(data))

        now = [0]

        def monotonic():
            now[0] += 1
            return now[0]

        return mock.patch.object(release.time, "monotonic", side_effect=monotonic), mock.patch.object(
            release.time, "sleep", side_effect=sleep
        )

    def test_activate_commits_candidate_env_before_start_and_records_previous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            (base / "releases" / "old").mkdir(parents=True)
            (base / "current").symlink_to(str(base / "releases" / "old"))
            archive, manifest = self.archive(root)
            calls, service = self.services(base, manifest["release"])
            with ExitStack() as stack:
                for patch in [
                    mock.patch.object(release, "verify", return_value=manifest),
                    mock.patch.object(release.subprocess, "run", side_effect=service),
                    *self.identity("unit"),
                    *self.healthy_clock(base),
                ]:
                    stack.enter_context(patch)
                result = release.activate(archive, "unit", base)
            self.assertEqual(result["release"], "candidate")
            self.assertEqual((base / "active.env").read_text(), "EYESY_RELEASE=candidate\n")
            self.assertEqual(
                json.loads((base / "previous.json").read_text())["release_path"],
                str(base / "releases" / "old"),
            )
            self.assertTrue(any(c[0][:3] == ["systemctl", "start", "eyesy-platform.service"] for c in calls))

    def test_activate_start_failure_restores_exact_previous_link_and_env(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            old = base / "releases" / "old"
            old.mkdir(parents=True)
            (base / "current").symlink_to(str(old))
            (base / "active.env").write_bytes(b"OLD=exact\n")
            archive, manifest = self.archive(root)
            calls, service = self.services(base, manifest["release"], fail_start=True)
            with ExitStack() as stack:
                for patch in [
                    mock.patch.object(release, "verify", return_value=manifest),
                    mock.patch.object(release.subprocess, "run", side_effect=service),
                    *self.identity("unit"),
                ]:
                    stack.enter_context(patch)
                with self.assertRaises(subprocess.CalledProcessError):
                    release.activate(archive, "unit", base)
            self.assertEqual((base / "current").resolve(), old.resolve())
            self.assertEqual((base / "active.env").read_bytes(), b"OLD=exact\n")

    def test_activate_failure_without_previous_restores_stock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            base.mkdir()
            archive, manifest = self.archive(root)
            calls, service = self.services(base, manifest["release"], fail_start=True)
            with ExitStack() as stack:
                for patch in [
                    mock.patch.object(release, "verify", return_value=manifest),
                    mock.patch.object(release.subprocess, "run", side_effect=service),
                    *self.identity("unit"),
                ]:
                    stack.enter_context(patch)
                with self.assertRaises(subprocess.CalledProcessError):
                    release.activate(archive, "unit", base)
            self.assertFalse((base / "current").exists())
            self.assertFalse((base / "active.env").exists())
            self.assertTrue(any(c[0] == ["systemctl", "start", "eyesypy.service"] for c in calls))

    def install(self, base, manifest):
        """Stage an installed release matching the archive helper's manifest."""
        installed = base / "releases" / manifest["release"]
        installed.mkdir(parents=True)
        (installed / "manifest.json").write_text(json.dumps(manifest))
        (installed / "eyesy-engine").write_bytes(b"engine payload")
        return installed

    def test_activate_after_stock_rollback_reselects_installed_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            base.mkdir()
            archive, manifest = self.archive(root)
            installed = self.install(base, manifest)
            old = base / "releases" / "old"
            old.mkdir()
            (base / "previous.json").write_text(json.dumps({"release_path": str(old)}) + "\n")
            calls, service = self.services(base, manifest["release"])
            with ExitStack() as stack:
                for patch in [
                    mock.patch.object(release, "verify", return_value=manifest),
                    mock.patch.object(release.subprocess, "run", side_effect=service),
                    *self.identity("unit"),
                    *self.healthy_clock(base),
                ]:
                    stack.enter_context(patch)
                result = release.activate(archive, "unit", base)
            self.assertEqual(result["release"], "candidate")
            self.assertEqual((base / "current").resolve(), installed.resolve())
            self.assertEqual((base / "active.env").read_text(), "EYESY_RELEASE=candidate\n")
            # Retained previous.json survives re-entry with no current link.
            self.assertEqual(json.loads((base / "previous.json").read_text())["release_path"], str(old))

    def test_activate_refuses_installed_release_with_different_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            base.mkdir()
            archive, manifest = self.archive(root)
            self.install(base, manifest)
            (base / "releases" / manifest["release"] / "eyesy-engine").write_bytes(b"tampered payload")
            calls, service = self.services(base)
            with ExitStack() as stack:
                for patch in [
                    mock.patch.object(release, "verify", return_value=manifest),
                    mock.patch.object(release.subprocess, "run", side_effect=service),
                    *self.identity("unit"),
                ]:
                    stack.enter_context(patch)
                with self.assertRaisesRegex(ValueError, "different content"):
                    release.activate(archive, "unit", base)
            self.assertEqual(calls, [])
            self.assertFalse((base / "current").exists())

    def test_identity_and_wrong_clone_refuse_before_service(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "platform"
            base.mkdir()
            archive, _ = self.archive(Path(temp))
            service = mock.Mock()
            with (
                mock.patch.object(release.os, "geteuid", return_value=0),
                mock.patch.object(release.Path, "read_text", return_value=json.dumps({"clone_id": "right"})),
                mock.patch.object(release.subprocess, "run", service),
            ):
                with self.assertRaisesRegex(ValueError, "identity"):
                    release.activate(archive, "wrong", base)
            service.assert_not_called()

    def test_rollback_previous_start_failure_restores_link_and_env(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            old = base / "releases" / "old"
            current = base / "releases" / "current"
            old.mkdir(parents=True)
            current.mkdir()
            (old / "manifest.json").write_text(json.dumps({"release": "old"}))
            (base / "current").symlink_to(str(current))
            (base / "active.env").write_bytes(b"CURRENT=exact\n")
            (base / "previous.json").write_text(json.dumps({"release_path": str(old)}))
            calls, service = self.services(base, "old", fail_start=True)
            with ExitStack() as stack:
                for patch in [
                    mock.patch.object(release.subprocess, "run", side_effect=service),
                    *self.identity("unit"),
                ]:
                    stack.enter_context(patch)
                with self.assertRaises(subprocess.CalledProcessError):
                    release.rollback(base, "unit")
            self.assertEqual((base / "current").resolve(), current.resolve())
            self.assertEqual((base / "active.env").read_bytes(), b"CURRENT=exact\n")
            self.assertTrue(any(c[0] == ["systemctl", "start", "eyesypy.service"] for c in calls))

    def test_blank_or_software_renderer_is_rejected_and_restored(self):
        for renderer, expected in (("", "health/heartbeat"), ("llvmpipe", "software rendering")):
            with self.subTest(renderer=renderer), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                base = root / "platform"
                old = base / "releases" / "old"
                old.mkdir(parents=True)
                (base / "current").symlink_to(str(old))
                archive, manifest = self.archive(root)
                calls, service = self.services(base, manifest["release"], renderer=renderer)
                with ExitStack() as stack:
                    for patch in [
                        mock.patch.object(release, "verify", return_value=manifest),
                        mock.patch.object(release.subprocess, "run", side_effect=service),
                        *self.identity("unit"),
                        *self.healthy_clock(base),
                    ]:
                        stack.enter_context(patch)
                    with self.assertRaisesRegex(ValueError, expected):
                        release.activate(archive, "unit", base)
                self.assertEqual((base / "current").resolve(), old.resolve())

    def test_nonadvancing_frame_times_out(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            old = base / "releases" / "old"
            old.mkdir(parents=True)
            (base / "current").symlink_to(str(old))
            archive, manifest = self.archive(root)
            calls, service = self.services(base, manifest["release"], advance=False)
            with ExitStack() as stack:
                for patch in [
                    mock.patch.object(release, "verify", return_value=manifest),
                    mock.patch.object(release.subprocess, "run", side_effect=service),
                    *self.identity("unit"),
                    *self.healthy_clock(base, advance=False),
                ]:
                    stack.enter_context(patch)
                with self.assertRaisesRegex(ValueError, "health/heartbeat"):
                    release.activate(archive, "unit", base)
            self.assertEqual((base / "current").resolve(), old.resolve())

    def test_corrupt_previous_manifest_and_symlinked_releases_refuse_before_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "platform"
            releases = base / "releases"
            releases.mkdir(parents=True)
            old = releases / "old"
            old.mkdir()
            (old / "manifest.json").write_text('{"release":"wrong"}')
            (base / "current").symlink_to(str(old))
            (base / "previous.json").write_text(json.dumps({"release_path": str(old)}))
            service = mock.Mock()
            with ExitStack() as stack:
                for patch in [mock.patch.object(release.subprocess, "run", service), *self.identity("unit")]:
                    stack.enter_context(patch)
                with self.assertRaisesRegex(ValueError, "manifest identity"):
                    release.rollback(base, "unit")
            service.assert_not_called()
            outside = root / "outside"
            outside.mkdir()
            symlink_base = root / "symlink-platform"
            symlink_base.mkdir()
            (symlink_base / "releases").symlink_to(outside, target_is_directory=True)
            with ExitStack() as stack:
                for patch in [mock.patch.object(release.subprocess, "run", service), *self.identity("unit")]:
                    stack.enter_context(patch)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    release.rollback(symlink_base, "unit")
            service.assert_not_called()

    def test_malformed_previous_metadata_refuses_without_stopping_service(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "platform"
            (base / "releases").mkdir(parents=True)
            (base / "previous.json").write_text("{bad")
            service = mock.Mock()
            with ExitStack() as stack:
                for patch in [mock.patch.object(release.subprocess, "run", service), *self.identity("unit")]:
                    stack.enter_context(patch)
                with self.assertRaises(json.JSONDecodeError):
                    release.rollback(base, "unit")
            service.assert_not_called()


if __name__ == "__main__":
    unittest.main()
