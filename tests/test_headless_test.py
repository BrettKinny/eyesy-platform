import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('headless_test', Path(__file__).parents[1] / 'tools/headless_test.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)

class HeadlessWorkflowTests(unittest.TestCase):
    def test_frames_and_missing_mode_refuse_before_ssh(self):
        with tempfile.TemporaryDirectory() as temp:
            for mode, frames in [('starter', 0), ('starter', 3601), ('missing', 10)]:
                with self.subTest(mode=mode, frames=frames), mock.patch.object(helper.release, 'verify', return_value={'release':'r','files':{'modes/starter/main.lua':'x'}}), mock.patch.object(helper.subprocess, 'check_output') as ssh:
                    with self.assertRaises(ValueError):
                        helper.execute(Path(temp)/'archive', 'host', 'clone', mode, frames, Path(temp)/'out')
                    ssh.assert_not_called()

    def test_wrong_clone_does_not_upload_or_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'out'
            with mock.patch.object(helper.release, 'verify', return_value={'release':'r','files':{'modes/starter/main.lua':'x'}}), mock.patch.object(helper.subprocess, 'check_output', return_value='{"clone_id":"other"}'), mock.patch.object(helper, 'run') as commands:
                with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                    helper.execute(Path(temp)/'archive', 'host', 'clone', 'starter', 10, output)
                commands.assert_not_called()
                self.assertFalse(output.exists())

    def test_dangling_output_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'out'; output.symlink_to(Path(temp)/'missing')
            with mock.patch.object(helper.release, 'verify', return_value={'release':'r','files':{'modes/starter/main.lua':'x'}}), mock.patch.object(helper.subprocess, 'check_output') as ssh:
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    helper.execute(Path(temp)/'archive', 'host', 'clone', 'starter', 10, output)
                ssh.assert_not_called()

    def test_failed_benchmark_still_fetches_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            calls=[]
            def command(args, **kwargs):
                calls.append(args)
                if args[0]=='ssh' and '--require-gpu' in args[-1]:
                    raise subprocess.CalledProcessError(1,args)
            with mock.patch.object(helper.release, 'verify', return_value={'release':'r','files':{'modes/starter/main.lua':'x'}}), mock.patch.object(helper.subprocess, 'check_output', side_effect=['{"clone_id":"clone"}','Compute Module 3 Plus','/tmp/eyesy-headless.ABC']), mock.patch.object(helper, 'run', side_effect=command):
                with self.assertRaises(subprocess.CalledProcessError):
                    helper.execute(Path(temp)/'archive','host','clone','starter',10,Path(temp)/'out')
            self.assertEqual(calls[-1][0],'scp')
            self.assertIn('-r',calls[-1])
            self.assertTrue(all('StrictHostKeyChecking=yes' in c for c in calls))
            self.assertFalse(any('systemctl' in ' '.join(c) or 'sudo' in c for c in calls))

    def test_invalid_mode_refuses_before_ssh(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'release.tar.gz'; archive.write_bytes(b'x')
            with mock.patch.object(helper.release, 'verify', return_value={'release': 'r', 'files': {'modes/starter/main.lua': 'x'}}), mock.patch.object(helper.subprocess, 'check_output') as ssh:
                with self.assertRaisesRegex(ValueError, 'basename'):
                    helper.execute(archive, 'host', 'clone', '../starter', 10, Path(temp) / 'out')
                ssh.assert_not_called()

    def test_existing_output_refuses_before_ssh(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'release.tar.gz'; archive.write_bytes(b'x')
            output = Path(temp) / 'out'; output.mkdir()
            with mock.patch.object(helper.release, 'verify', return_value={'release': 'r', 'files': {'modes/starter/main.lua': 'x'}}), mock.patch.object(helper.subprocess, 'check_output') as ssh:
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    helper.execute(archive, 'host', 'clone', 'starter', 10, output)
                ssh.assert_not_called()

    def test_remote_order_is_clone_check_upload_verify_extract_run_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'release.tar.gz'; archive.write_bytes(b'x')
            responses = [json.dumps({'clone_id': 'clone'}), 'Compute Module 3 Plus\0', '/tmp/eyesy-headless.ABC']
            calls = []
            def output(*args, **kwargs): calls.append(('check', args[0])); return responses.pop(0)
            def command(args, **kwargs): calls.append(('run', args)); return mock.DEFAULT
            with mock.patch.object(helper.release, 'verify', return_value={'release': 'r', 'files': {'modes/starter/main.lua': 'x'}}), mock.patch.object(helper.subprocess, 'check_output', side_effect=output), mock.patch.object(helper, 'run', side_effect=command):
                helper.execute(archive, 'host', 'clone', 'starter', 10, Path(temp) / 'out', [])
            run_commands = [str(item[1]) for item in calls if item[0] == 'run']
            self.assertIn('release.tar.gz', run_commands[0])
            self.assertIn('release.py', run_commands[1])
            self.assertIn('release.py', run_commands[2])
            self.assertIn('tar -xzf', run_commands[3])
            self.assertIn('benchmark.py', run_commands[4])
            self.assertIn('scp', run_commands[5])

if __name__ == '__main__': unittest.main()
