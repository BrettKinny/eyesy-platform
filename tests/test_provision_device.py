"""Static safety checks for the root-only provisioning script.

The script intentionally is not executed by the test suite: it changes package
and systemd state and is only suitable for the identified spare clone.
"""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools" / "provision_device.sh"


class ProvisionDeviceSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text()

    def _run_mount_and_xorg_block(
        self,
        *,
        mount_options="rw",
        remount_rw_rc=0,
        remount_ro_rc=0,
        rm_fail=False,
        rm_rc=1,
        conf_exists=True,
    ):
        start = self.source.index('task_mount_options=$(findmnt -n -o OPTIONS /)')
        end = self.source.index('task_script_dir=$(cd -- "$(dirname -- "$0")" && pwd)', start)
        block = self.source[start:end]
        with tempfile.TemporaryDirectory() as task_tmp:
            task_legacy_conf = Path(task_tmp) / "10-eyesy-720p.conf"
            if conf_exists:
                task_legacy_conf.write_text("stale\n")
            block = block.replace(
                '/etc/X11/xorg.conf.d/10-eyesy-720p.conf', str(task_legacy_conf)
            )

            script = """set -euo pipefail
findmnt() { printf \"%s\" \"OPTIONS\"; }
mount() {
    if [[ \"$1\" == \"-o\" && \"$2\" == \"remount,rw\" && \"$3\" == \"/\" ]]; then
        return REMOUNT_RW_RC
    fi
    if [[ \"$1\" == \"-o\" && \"$2\" == \"remount,ro\" && \"$3\" == \"/\" ]]; then
        return REMOUNT_RO_RC
    fi
    return 0
}
sync() { :; }
apt-get() { :; }
cp() { :; }
install() { :; }
python3() { :; }
systemctl() { :; }
rm() {
    if [[ \"$1\" == \"-f\" && \"$2\" == \"CONF_PATH\" && \"$RM_FAIL_FLAG\" -ne 0 ]]; then
        return RM_RC
    fi
    command rm \"$@\"
}
RM_FAIL_FLAG=RM_FAIL_VALUE
RM_RC=RM_RC_VALUE
"""
            script += block
            script += "\nexit 0\n"

            script = script.replace("OPTIONS", mount_options)
            script = script.replace("REMOUNT_RW_RC", str(remount_rw_rc))
            script = script.replace("REMOUNT_RO_RC", str(remount_ro_rc))
            script = script.replace("RM_FAIL_VALUE", str(int(rm_fail)))
            script = script.replace("RM_RC_VALUE", str(rm_rc))
            script = script.replace("CONF_PATH", str(task_legacy_conf))

            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True
            )

            return result, task_legacy_conf

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
            "packages.before", "packages.after",
            "eyesy-platform.service",
            "eyesy-platform-fallback.service",
        ):
            self.assertIn(name, self.source[inventory:first_inventory_write])
        self.assertIn('[[ -L "$task_backup_dir" ]]', self.source)
        self.assertIn('[[ -L "$task_unit_path" ]]', self.source)
        self.assertNotIn("10-eyesy-720p.conf", self.source[inventory:first_inventory_write])

    def test_write_destination_preflight_precedes_package_mutation(self):
        apt = self.source.index("apt-get update")
        self.assertLess(self.source.index('[[ -L "$task_unit_path" ]]'), apt)

    def test_no_xorg_display_stack(self):
        # The engine draws with direct KMS; any Xorg session blanks HDMI on this
        # board, and Xwrapper.config with needs_root_rights=yes is a root X hole.
        for name in ("xserver-xorg", "xinit", "xauth", "Xwrapper.config"):
            self.assertNotIn(name, self.source)

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

    def test_legacy_xorg_conf_removed_and_verified(self):
        result, legacy_conf = self._run_mount_and_xorg_block()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(legacy_conf.exists())

    def test_legacy_xorg_conf_absence_is_idempotent_success(self):
        result, legacy_conf = self._run_mount_and_xorg_block(conf_exists=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(legacy_conf.exists())

    def test_failed_read_write_remount_is_fatal(self):
        result, _legacy_conf = self._run_mount_and_xorg_block(
            mount_options='ro', remount_rw_rc=1
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('failed to remount root filesystem read-write', result.stderr)

    def test_failed_legacy_xorg_conf_removal_is_fatal(self):
        result, _legacy_conf = self._run_mount_and_xorg_block(rm_fail=True, rm_rc=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('failed to remove', result.stderr)


if __name__ == "__main__":
    unittest.main()
