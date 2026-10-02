import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "provenance", Path(__file__).parents[1] / "tools/build_provenance.py"
)
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)


class ProvenanceTests(unittest.TestCase):
    def elf(self, path, arm=False):
        data = bytearray(64)
        data[:4] = b"\x7fELF"
        data[4:6] = bytes((1 if arm else 2, 1))
        data[18:20] = (40 if arm else 62).to_bytes(2, "little")
        path.write_bytes(data)

    def test_architecture_rejects_wrong_binary(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "engine"
            self.elf(path, arm=True)
            self.assertNotEqual(provenance.elf_arch(path), "amd64")

    def test_image_info_requires_digest(self):
        with mock.patch.object(
            provenance.subprocess, "check_output", return_value='[{"Architecture":"amd64","Id":"abc"}]'
        ):
            with self.assertRaisesRegex(RuntimeError, "immutable digest"):
                provenance.image_info("image", "amd64")

    def test_package_lock_hashes_exact_bytes(self):
        with mock.patch.object(provenance.subprocess, "check_output", return_value=b"pkg 1\n"):
            result = provenance.package_lock("image", "amd64")
        self.assertEqual(result["contents"], "pkg 1\n")
        self.assertEqual(result["sha256"], provenance.hashlib.sha256(b"pkg 1\n").hexdigest())


if __name__ == "__main__":
    unittest.main()
