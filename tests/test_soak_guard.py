import contextlib
import importlib.util
import io
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('soak_guard_tested', Path(__file__).parents[1] / 'tools/soak_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class SoakGuardTests(unittest.TestCase):
    def execute(self, rss=1, temperature=40, duration=100, identities=None, error=None,
                exe_disappears_after_term=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            engine = root / 'engine'; engine.touch()
            output = root / 'evidence'; output.mkdir()
            args = SimpleNamespace(clone_id='clone', pid=123, engine=engine, output=output, duration=duration)
            parser = mock.Mock(); parser.parse_args.return_value = args
            original_read = Path.read_text
            original_resolve = Path.resolve
            signalled = []
            def read(path, *a, **kw):
                if str(path) == '/etc/eyesy-development-clone': return '{"clone_id":"clone"}'
                if str(path) == '/proc/device-tree/model': return 'Raspberry Pi Compute Module 3 Plus'
                return original_read(path, *a, **kw)
            def resolve(path, *a, **kw):
                if str(path) == '/proc/123/exe':
                    if exe_disappears_after_term and signalled:
                        raise FileNotFoundError('exited executable link')
                    return engine
                return original_resolve(path, *a, **kw)
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(guard.argparse, 'ArgumentParser', return_value=parser))
                stack.enter_context(mock.patch.object(Path, 'read_text', read))
                stack.enter_context(mock.patch.object(Path, 'resolve', resolve))
                stack.enter_context(mock.patch.object(Path, 'is_relative_to', return_value=True))
                stack.enter_context(mock.patch.object(guard, 'identity', side_effect=identities, return_value='start'))
                stack.enter_context(mock.patch.object(guard, 'reading', side_effect=error, return_value=(rss, temperature)))
                stack.enter_context(mock.patch.object(guard.os, 'pidfd_open', return_value=77))
                closed = stack.enter_context(mock.patch.object(guard.os, 'close'))
                sent = stack.enter_context(mock.patch.object(guard.signal, 'pidfd_send_signal',
                                                             side_effect=lambda *args: signalled.append(args)))
                stack.enter_context(mock.patch.object(guard.time, 'sleep'))
                stack.enter_context(mock.patch.object(guard.time, 'monotonic', side_effect=[0, 2, 5]))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                result = guard.main()
                closed.assert_called_once_with(77)
                return result, json.loads((output / 'guard-report.json').read_text()), sent.call_args_list

    def test_rss_limit_stops_identified_process(self):
        result, report, sent = self.execute(rss=257 * 1024 * 1024)
        self.assertEqual(result, 1)
        self.assertEqual(report['reason'], 'RSS limit')
        self.assertEqual(sent, [mock.call(77, signal.SIGTERM), mock.call(77, signal.SIGKILL)])

    def test_temperature_limit(self):
        result, report, sent = self.execute(temperature=80)
        self.assertEqual(result, 1)
        self.assertEqual(report['reason'], 'temperature limit')
        self.assertEqual(len(sent), 2)

    def test_terminated_zombie_keeps_original_limit_reason(self):
        result, report, sent = self.execute(duration=1, exe_disappears_after_term=True)
        self.assertEqual(result, 1)
        self.assertEqual(report['reason'], 'duration limit')
        self.assertNotIn('error', report)
        self.assertEqual(sent, [mock.call(77, signal.SIGTERM)])

    def test_duration_limit(self):
        result, report, sent = self.execute(duration=1)
        self.assertEqual(result, 1)
        self.assertEqual(report['reason'], 'duration limit')
        self.assertEqual(len(sent), 2)

    def test_process_exit_does_not_claim_target_exit_code(self):
        result, report, sent = self.execute(identities=['start', 'start', None])
        self.assertEqual(result, 0)
        self.assertIsNone(report['target_exit_status'])
        self.assertFalse(report['guard_triggered'])
        self.assertEqual(sent, [])

    def test_identity_change_after_pidfd_open_never_signals(self):
        result, report, sent = self.execute(identities=['start', 'new', 'new'])
        self.assertEqual(result, 1)
        self.assertIn('identity changed', report['error'])
        self.assertEqual(sent, [])

    def test_telemetry_failure_stops_target(self):
        result, report, sent = self.execute(error=OSError('sensor unavailable'))
        self.assertEqual(result, 1)
        self.assertIn('sensor unavailable', report['error'])
        self.assertEqual(sent, [mock.call(77, signal.SIGTERM), mock.call(77, signal.SIGKILL)])
