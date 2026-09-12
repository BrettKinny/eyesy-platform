import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from importlib.machinery import SourceFileLoader
spec = importlib.util.spec_from_loader('eyesyctl', SourceFileLoader('eyesyctl', str(Path(__file__).parents[1] / 'eyesyctl')))
eyesyctl = importlib.util.module_from_spec(spec); spec.loader.exec_module(eyesyctl)

CLONE = '01234567-89ab-cdef-0123-456789abcdef'

class RemoteCliTests(unittest.TestCase):
    def args(self, command='rollback', **kwargs):
        values = dict(command=command, host='192.0.2.10', clone_id=CLONE,
                      target='previous', known_hosts=None)
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_ssh_options_require_host_key_checking_and_known_hosts(self):
        args = self.args(known_hosts=Path('/etc/hosts'))
        options = eyesyctl.ssh_options(args)
        self.assertIn('StrictHostKeyChecking=yes', options)
        self.assertIn('UserKnownHostsFile=/etc/hosts', options)

    def test_rejects_option_injection_and_shell_metacharacters(self):
        for host in ('-oProxyCommand=bad', 'host;touch /tmp/pwned', 'host$(id)', 'host name'):
            with self.assertRaisesRegex(RuntimeError, 'hostname'):
                eyesyctl.ssh_options(self.args(host=host))

    @mock.patch.object(eyesyctl, 'container')
    def test_preview_recording_limit_matches_engine(self, container):
        for limit in ('0', '100001', '1000000'):
            with mock.patch.object(eyesyctl.sys, 'argv', ['eyesyctl', 'preview', 'starter', '--record-limit', limit]):
                with self.assertRaisesRegex(RuntimeError, '1..100000'):
                    eyesyctl.main()
        container.assert_not_called()
        with mock.patch.object(eyesyctl.sys, 'argv', ['eyesyctl', 'preview', 'starter', '--record-limit', '100000']):
            eyesyctl.main()
        self.assertEqual(container.call_args.args[0][-2:], ['--record-limit', '100000'])

    @mock.patch.object(eyesyctl, 'run')
    @mock.patch.object(eyesyctl.subprocess, 'check_output', return_value='/tmp/eyesy-platform.ABC123\n')
    def test_rollback_stages_guarded_release_and_selected_target(self, check_output, run):
        eyesyctl.remote(self.args(target='stock'))
        calls = [c.args[0] for c in run.call_args_list]
        self.assertEqual(len(calls), 2)
        command = calls[1][-1]
        self.assertIn('rollback', command)
        self.assertIn('--activate-clone', command)
        self.assertIn(CLONE, command)
        self.assertIn('--target stock', command)
        self.assertNotIn('systemctl', command)
        self.assertIn('StrictHostKeyChecking=yes', calls[0])

    @mock.patch.object(eyesyctl, 'run')
    @mock.patch.object(eyesyctl.subprocess, 'check_output', return_value='/tmp/eyesy-platform.ABC123\n')
    def test_rollback_previous_is_forwarded_and_failures_propagate(self, check_output, run):
        run.side_effect = RuntimeError('ssh failed')
        with self.assertRaisesRegex(RuntimeError, 'ssh failed'):
            eyesyctl.remote(self.args(target='previous'))

if __name__ == '__main__': unittest.main()
