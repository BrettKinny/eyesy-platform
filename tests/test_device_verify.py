# SPDX-License-Identifier: BSD-3-Clause
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest

from PIL import Image

spec = importlib.util.spec_from_file_location(
    "device_verify", Path(__file__).parents[1] / "tools/device_verify.py"
)
dv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dv)

ARGS = types.SimpleNamespace(budget_ms=33.3, brightness_low=0.0001, flatness=0.002)
GOOD = {"mean": 40.0, "stddev": 30.0}


def exp(**final):
    base = {"mode_errors": 0, "error": "", "shader_warning": "", "p50_ms": 20.0, "p95_ms": 22.0}
    base.update(final)
    return {"returncode": 0, "timed_out": False, "software_renderer": False, "final": base}


def kinds(findings):
    return sorted(f["kind"] for f in findings)


class ClassifyTests(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(dv.classify(exp(), "[notice ] Renderer: VC4 V3D 2.1\n", GOOD, ARGS), [])

    def test_regalloc_and_black(self):
        log = "Mode: loading x\nFailed to register allocate:\nBLOCK 0:\n"
        self.assertEqual(
            kinds(dv.classify(exp(), log, {"mean": 0.0, "stddev": 0.0}, ARGS)), ["black", "gpu_compile"]
        )

    def test_regalloc_alone(self):
        self.assertEqual(
            kinds(dv.classify(exp(), "Failed to register allocate:\n", GOOD, ARGS)), ["gpu_compile"]
        )

    def test_compile_error(self):
        f = dv.classify(exp(mode_errors=1, error="boom"), "", GOOD, ARGS)
        self.assertEqual(kinds(f), ["setup_error", "setup_error"])

    def test_flat_not_black(self):
        self.assertEqual(kinds(dv.classify(exp(), "", {"mean": 120.0, "stddev": 0.1}, ARGS)), ["flat"])

    def test_budget(self):
        self.assertEqual(kinds(dv.classify(exp(p50_ms=39.0), "", GOOD, ARGS)), ["over_budget"])
        self.assertEqual(dv.classify(exp(p50_ms=33.3), "", GOOD, ARGS), [])

    def test_missing_evidence(self):
        self.assertEqual(kinds(dv.classify(None, "", None, ARGS)), ["setup_error", "setup_error"])

    def test_exit_status(self):
        ok = {"findings": []}
        slow = {"findings": [{"kind": "over_budget"}]}
        bad = {"findings": [{"kind": "black"}]}
        self.assertEqual(dv.exit_status([ok]), 0)
        self.assertEqual(dv.exit_status([ok, slow]), 2)
        self.assertEqual(dv.exit_status([ok, slow], True), 1)
        self.assertEqual(dv.exit_status([slow, bad]), 1)
        self.assertEqual(dv.exit_status([]), 1)


class EvidenceTests(unittest.TestCase):
    def test_collect_and_stats(self):
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "headless-abc" / "00-m"
            (run / "grabs").mkdir(parents=True)
            (run / "experiment.json").write_text(json.dumps(exp()))
            (run / "engine.log").write_text("Failed to register allocate:\n")
            Image.new("RGB", (8, 8), (0, 0, 0)).save(run / "grabs" / "a.png")
            e, log, grab = dv.collect(t)
            self.assertEqual(e["final"]["p50_ms"], 20.0)
            stats = dv.grab_stats(grab)
            self.assertEqual(stats["mean"], 0.0)
            self.assertEqual(kinds(dv.classify(e, log, stats, ARGS)), ["black", "gpu_compile"])

    def test_main_with_fake_execute(self):
        with tempfile.TemporaryDirectory() as t:

            def fake(archive, host, clone, mode, frames, out, ssh=None, keep_staging=False):
                run = Path(out) / "headless-1" / f"00-{mode}"
                (run / "grabs").mkdir(parents=True)
                slow = mode == "slow"
                (run / "experiment.json").write_text(json.dumps(exp(p50_ms=40.0 if slow else 10.0)))
                (run / "engine.log").write_text("")
                img = Image.new("L", (8, 8))
                img.putdata([i * 4 for i in range(64)])
                img.save(run / "grabs" / "a.png")

            orig = dv.archive_modes
            dv.archive_modes = lambda a: ["ok", "slow"]
            try:
                out = Path(t) / "out"
                self.assertEqual(
                    dv.main(["x.tgz", "--host", "h", "--clone-id", "c", "--output", str(out)], fake), 2
                )
                summary = json.loads((out / "summary.json").read_text())
                self.assertEqual(summary["counts"], {"total": 2, "passed": 1})
                self.assertTrue((out / "slow.json").exists())
            finally:
                dv.archive_modes = orig


if __name__ == "__main__":
    unittest.main()
