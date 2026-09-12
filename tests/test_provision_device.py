"""Static safety checks for the root-only provisioning script.

The script intentionally is not executed by the test suite: it changes package
and systemd state and is only suitable for the identified spare clone.
"""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools" / "provision_device.sh"


class ProvisionDeviceSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text()

    def test_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_identity_guards_are_not_asserts(self):
        self.assertNotIn("assert ", self.source)
        self.assertIn("marker.get('clone_id')", self.source)
        self.assertIn("raise SystemExit('Clone identity mismatch')", self.source)
        self.assertIn("raise SystemExit('Wrong board')", self.source)
        self.assertIn("raise SystemExit('Wrong OS')", self.source)

    def test_platform_is_checked_before_package_mutation(self):
        checks = self.source.index("systemctl is-active")
        checks = min(checks, self.source.index("systemctl is-enabled"))
        self.assertLess(checks, self.source.index("apt-get update"))
        self.assertIn('for task_unit in eyesy-platform.service eyesy-platform-fallback.service',
                      self.source[:checks + 1])

    def test_backup_inventory_and_destinations_are_protected(self):
        inventory = self.source.index("for task_backup in packages.before")
        first_inventory_write = self.source.index(
            'dpkg-query -W > "$task_base/provision-backup/packages.before"'
        )
        self.assertLess(inventory, first_inventory_write)
        for name in (
            "packages.before", "packages.after", "Xwrapper.config",
            "eyesy-platform.service",
            "eyesy-platform-fallback.service",
        ):
            self.assertIn(name, self.source[inventory:first_inventory_write])
        self.assertIn('[[ -L "$task_backup_dir" ]]', self.source)
        self.assertIn('[[ -L "$task_unit_path" ]]', self.source)
        self.assertIn("path.is_symlink()", self.source)
        self.assertIn("backup.is_symlink()", self.source)

    def test_write_destination_preflight_precedes_package_mutation(self):
        apt = self.source.index("apt-get update")
        self.assertLess(self.source.index('[[ -L "$task_unit_path" ]]'), apt)
        self.assertLess(self.source.index("-L /etc/X11/Xwrapper.config"), apt)

    def test_cleanup_exit_status_reflects_remount_failure(self):
        # Execute only the actual cleanup function, with inert mount/sync stubs.
        # Never source or execute the root provisioning workflow itself.
        start = self.source.index('cleanup() {')
        end = self.source.index('\ntrap cleanup EXIT', start)
        cleanup = self.source[start:end]
        for original, remount, expected in ((0, 1, 1), (7, 1, 7), (0, 0, 0), (7, 0, 7)):
            with self.subTest(original=original, remount=remount):
                script = ('set -euo pipefail\n' + f'mount() {{ return {remount}; }}\n'
                          'sync() { :; }\ntask_restore_ro=true\n' + cleanup +
                          f'\ntrap cleanup EXIT\nexit {original}\n')
                result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual('failed to restore' in result.stderr, remount != 0)


if __name__ == "__main__":
    unittest.main()
