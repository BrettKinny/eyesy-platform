#!/usr/bin/env python3
"""Unit test for the stock-recovery fallback unit's exit contract.

Runs the real `ExecStart` shell script from `deploy/eyesy-platform-fallback.service`
against a mock `systemctl` (and a no-op `sleep`) and asserts the exit code for
each state of the platform/stock race. The unit is a oneshot triggered by
`OnFailure=`: a nonzero exit means it left the display dead, so the exit code is
the contract under test.

Regression this guards (ROADMAP item 6): when the platform is mid-`Restart=`
(ActiveState `activating`) the fallback's stock start is canceled by the
concurrent platform start (`Conflicts=eyesypy.service`); the old unit then
reported FAILED even though the platform was converging. `activating` now
counts as success, while a genuinely parked platform plus a dead stock client
still exits nonzero.
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
UNIT = ROOT / "deploy" / "eyesy-platform-fallback.service"

MOCK_SYSTEMCTL = """#!/bin/sh
D="${MOCK_DIR:?}"
status=0
case "$1" in
  show)
    # show <unit> -p ActiveState --value : pop the next scripted state.
    seq="$D/seq"
    line=$(sed -n 1p "$seq")
    if [ "$(wc -l < "$seq")" -gt 1 ]; then
      sed -n '2,$p' "$seq" > "$seq.tmp" && mv "$seq.tmp" "$seq"
    fi
    printf '%s\\n' "$line" > "$D/cur"
    printf '%s\\n' "$line"
    ;;
  start)
    printf '%s\\n' "${MOCK_STOCK_ON_START:-1}" > "$D/stock"
    ;;
  is-active)
    # is-active --quiet <unit>
    if [ "$3" = "eyesypy.service" ]; then
      [ "$(cat "$D/stock" 2>/dev/null || echo 0)" = "1" ] || status=3
    else
      [ "$(cat "$D/cur" 2>/dev/null)" = "active" ] || status=3
    fi
    ;;
esac
exit $status
"""

MOCK_SLEEP = "#!/bin/sh\nexit 0\n"


def exec_start_command(text):
    """The ExecStart value as systemd resolves it: drop full-line comments and
    join backslash continuations."""
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("ExecStart="))
    parts = [lines[index][len("ExecStart="):].rstrip().rstrip("\\").rstrip()]
    for line in lines[index + 1:]:
        stripped = line.strip()
        if not stripped:
            break
        if stripped.startswith("#"):
            continue
        parts.append(stripped.rstrip("\\").rstrip())
    return " ".join(parts)


class FallbackUnitTests(unittest.TestCase):
    # name, scripted platform ActiveState sequence, stock-up-on-start, expected rc
    CASES = [
        ("platform active on the first poll", ["active"], "1", 0),
        ("platform failed, stock takes over", ["failed"], "1", 0),
        ("platform failed, stock will not start -> genuine failure", ["failed"], "0", 3),
        ("platform inactive, stock takes over", ["inactive"], "1", 0),
        # The regression: platform mid-Restart= (activating) and the stock start
        # was canceled by Conflicts=; the display is converging on the platform.
        ("platform activating, stock start canceled -> convergent success",
         ["activating"], "0", 0),
    ]

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="eyesy-fallback-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        for name, body in (("systemctl", MOCK_SYSTEMCTL), ("sleep", MOCK_SLEEP)):
            path = self.tmp / name
            path.write_text(body)
            path.chmod(0o755)
        self.command = exec_start_command(UNIT.read_text())

    def run_case(self, states, stock_on_start):
        (self.tmp / "seq").write_text("\n".join(states) + "\n")
        (self.tmp / "cur").write_text(states[-1] + "\n")
        env = dict(os.environ)
        env.update(MOCK_DIR=str(self.tmp), MOCK_STOCK_ON_START=stock_on_start)
        env["PATH"] = f"{self.tmp}:{env['PATH']}"
        result = subprocess.run(self.command, shell=True, executable="/bin/sh",
                                env=env, capture_output=True, text=True, timeout=60)
        started = (self.tmp / "stock").exists()
        return result.returncode, started

    def test_exit_contract(self):
        for name, states, stock_on_start, expected in self.CASES:
            with self.subTest(case=name):
                code, _ = self.run_case(states, stock_on_start)
                self.assertEqual(code, expected, f"{name}: exit {code}, expected {expected}")

    def test_stock_is_started_only_after_the_poll_window(self):
        # An immediately-active platform must not touch the stock service.
        _, started = self.run_case(["active"], "1")
        self.assertFalse(started, "stock started even though the platform was already active")
        # A failed platform must hand over.
        _, started = self.run_case(["failed"], "1")
        self.assertTrue(started, "stock never started after the platform failed")


if __name__ == "__main__":
    unittest.main()
