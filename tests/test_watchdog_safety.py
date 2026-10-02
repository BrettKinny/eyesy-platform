# SPDX-License-Identifier: BSD-3-Clause
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


watchdog = load("watchdog_probe")
soak = load("soak_guard")


class WatchdogSafetyTests(unittest.TestCase):
    def test_require_is_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "unit already"):
            watchdog.require(False, "unit already exists")

    @mock.patch.object(watchdog.subprocess, "run")
    def test_systemd_command_has_bounded_timeout(self, process):
        process.return_value = mock.Mock(stdout="active\n")
        self.assertEqual(watchdog.run("systemctl", "is-active", "eyesypy.service"), "active")
        self.assertEqual(process.call_args.kwargs["timeout"], 20)
        self.assertTrue(process.call_args.kwargs["check"])

    def test_soak_require_rejects_invalid_identity(self):
        with self.assertRaisesRegex(RuntimeError, "identity"):
            soak.require(False, "identity mismatch")

    def test_soak_telemetry_rejects_insane_values(self):
        with self.assertRaisesRegex(ValueError, "insane"):
            soak.validate_telemetry(-1, 40)

    def run_main(
        self, launch_error=None, restart_error=None, report_error=False, state_error=False, heartbeat=(1, 2)
    ):
        scratch = tempfile.TemporaryDirectory()
        root = Path(scratch.name)
        engine = root / "engine"
        engine.write_bytes(b"x")
        mode = root / "mode"
        mode.mkdir()
        (mode / "main.lua").write_text("return {}")
        output = root / "output"
        args = SimpleNamespace(clone_id="clone", engine=engine, mode=mode, output=output)
        parser = mock.Mock()
        parser.parse_args.return_value = args
        states = iter(
            [
                {"MainPID": "101", "NRestarts": "0", "ActiveState": "active"},
                {"MainPID": "202", "NRestarts": "1", "ActiveState": "active"},
            ]
        )
        frames = iter(heartbeat)
        self.commands = []

        def command(*argv, **kwargs):
            self.commands.append(argv)
            if argv[0] == "install":
                output.mkdir()
            if argv[0] == "systemd-run" and launch_error:
                raise launch_error
            if argv[0] == "systemd-run":
                (output / "status.json").write_text("{}")
            if argv[0] == "systemctl" and argv[1] == "stop" and restart_error:
                raise restart_error
            return (
                "active"
                if argv[:2] == ("systemctl", "is-active")
                else "not-found"
                if "LoadState" in argv
                else ""
            )

        def status():
            if state_error:
                raise RuntimeError("restart state unavailable")
            return next(states)

        def status_json(path):
            return {"frame": next(frames), "error": "", "renderer": "VC4"}

        try:
            with (
                mock.patch.object(Path, "is_relative_to", return_value=True),
                mock.patch.object(watchdog.argparse, "ArgumentParser", return_value=parser),
                mock.patch.object(watchdog, "check_clone"),
                mock.patch.object(watchdog, "run", side_effect=command),
                mock.patch.object(watchdog, "properties", side_effect=status),
                mock.patch.object(watchdog.time, "sleep"),
                mock.patch.object(watchdog.json, "loads", side_effect=status_json),
            ):
                if report_error:
                    original = Path.write_text

                    def fail_report(path, data, *a, **kw):
                        if path.name == "watchdog-report.json":
                            raise OSError("report disk full")
                        return original(path, data, *a, **kw)

                    with mock.patch.object(Path, "write_text", fail_report):
                        return watchdog.main()
                return watchdog.main()
        finally:
            scratch.cleanup()

    def test_launch_timeout_still_attempts_cleanup(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_main(launch_error=subprocess.TimeoutExpired("systemd-run", 20))
        self.assertIn(("systemctl", "stop", watchdog.UNIT), self.commands)

    def test_failed_restart_observation_still_cleans_up(self):
        with self.assertRaisesRegex(RuntimeError, "restart state unavailable"):
            self.run_main(state_error=True)
        self.assertIn(("systemctl", "stop", watchdog.UNIT), self.commands)

    def test_stalled_heartbeat_does_not_pass(self):
        with self.assertRaises(RuntimeError):
            self.run_main(heartbeat=(1, 1))
        self.assertIn(("systemctl", "stop", watchdog.UNIT), self.commands)

    def test_success_requires_advancing_heartbeat(self):
        self.assertEqual(self.run_main(), 0)

    def test_cleanup_failure_makes_result_nonzero(self):
        self.assertEqual(self.run_main(restart_error=RuntimeError("stop failed")), 1)

    def test_report_failure_without_primary_raises(self):
        with self.assertRaisesRegex(OSError, "report disk full"):
            self.run_main(report_error=True)

    def test_report_failure_preserves_launch_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_main(launch_error=subprocess.TimeoutExpired("systemd-run", 20), report_error=True)


if __name__ == "__main__":
    unittest.main()
