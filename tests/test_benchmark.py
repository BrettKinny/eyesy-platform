import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("benchmark", Path(__file__).parents[1] / "tools/benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkTests(unittest.TestCase):
    def test_does_not_qualify_short_memory_run(self):
        self.assertFalse(benchmark.memory_summary([], 3)["qualified"])

    def test_excludes_warmup(self):
        samples = [{"elapsed": i, "rss_bytes": 9999 if i < 3 else 100} for i in range(10)]
        result = benchmark.memory_summary(samples, 3)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["peak_bytes"], 100)
        self.assertEqual(result["delta_bytes"], 0)

    def test_detects_growth(self):
        samples = [{"elapsed": i, "rss_bytes": i * 100} for i in range(10)]
        self.assertGreater(benchmark.memory_summary(samples, 3)["delta_bytes"], 0)

    def test_explicit_missing_mode_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "valid").mkdir()
            (root / "valid/main.lua").write_text("")
            with self.assertRaisesRegex(ValueError, "Missing"):
                benchmark.select_modes(root, ["valid", "absent"])

    def test_switch_catalog_hashes_siblings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("one", "two"):
                (root / name).mkdir()
                (root / name / "main.lua").write_text(name)
            selected = benchmark.select_modes(root, ["one"])
            files = benchmark.mode_files(root, selected, include_catalog=True)
            self.assertIn("two/main.lua", files)

    def test_default_selection_rejects_external_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "modes"
            root.mkdir()
            external = Path(temp) / "external"
            external.mkdir()
            (external / "main.lua").write_text("return {}")
            (root / "escape").symlink_to(external, target_is_directory=True)
            with self.assertRaises(ValueError):
                benchmark.select_modes(root)

    def test_nested_switch_catalog_matches_engine_siblings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("nested/one", "nested/two", "unrelated"):
                folder = root / name
                folder.mkdir(parents=True)
                (folder / "main.lua").write_text(name)
            files = benchmark.mode_files(root, benchmark.select_modes(root, ["nested/one"]), True)
            self.assertEqual(set(files), {"nested/one/main.lua", "nested/two/main.lua"})

    def test_all_sample_failure_types_are_detected(self):
        for status in ({"error": "bad"}, {"shader_warning": "fallback"}, {"mode_errors": 1}):
            self.assertTrue(benchmark.sample_failed(status))
        self.assertFalse(benchmark.sample_failed({"error": "", "shader_warning": "", "mode_errors": 0}))

    def test_transient_sample_error_fails_experiment(self):
        class Process:
            returncode = 0

            def __init__(self):
                self.states = iter([None, 0, 0])

            def poll(self):
                return next(self.states)

            def wait(self, **kwargs):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mode = root / "mode"
            mode.mkdir()
            (mode / "main.lua").write_text("")
            folder = root / "run"
            process = Process()

            def launch(*args, **kwargs):
                (folder / "status.json").write_text(
                    json.dumps(
                        {
                            "frame": 1,
                            "error": "transient",
                            "renderer": "llvmpipe",
                            "rss_bytes": 1,
                            "mode_errors": 0,
                        }
                    )
                )
                (folder / "report.json").write_text(json.dumps({"frame": 2, "renderer": "llvmpipe"}))
                return process

            with (
                mock.patch.object(benchmark.subprocess, "Popen", side_effect=launch),
                mock.patch.object(benchmark.time, "sleep"),
                mock.patch.object(benchmark.time, "monotonic", side_effect=[0, 1, 2]),
                mock.patch.object(benchmark, "temperature_c", return_value=None),
            ):
                result = benchmark.experiment(Path("/bin/true"), mode, folder, 1, 0, 10, 0)
            self.assertFalse(result["passed"])
            self.assertEqual(result["samples"][0]["error"], "transient")
