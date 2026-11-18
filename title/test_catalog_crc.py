import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch
import zlib

import UnityPy
from UnityPy.streams.EndianBinaryReader import EndianBinaryReader_Memoryview
import catalog_crc


class CatalogCrcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = Path(os.getenv("GALLERY_TEST_BUNDLE", str(Path(__file__).with_name("test.bundle"))))
        if not cls.example.is_file():
            raise unittest.SkipTest("Set GALLERY_TEST_BUNDLE to an installed single-CAB title bundle")

    def test_matches_legacy_crc_without_copying_entire_reader(self):
        env = UnityPy.load(self.example.read_bytes())
        expected = zlib.crc32(next(iter(env.file.files.values())).reader.bytes)
        with patch.object(EndianBinaryReader_Memoryview, "bytes",
                          property(lambda _: self.fail("copied the entire uncompressed CAB"))):
            self.assertEqual(catalog_crc.crc_and_size(self.example), (expected, self.example.stat().st_size))

    def test_validates_prefab_in_the_same_read_and_propagates_error(self):
        reads = []
        def check(env):
            reads.append(len(env.container))
            raise ValueError("invalid title prefab")
        with self.assertRaisesRegex(ValueError, "invalid title prefab"):
            catalog_crc.crc_and_size(self.example, validate=check)
        self.assertEqual(len(reads), 1)
        self.assertGreater(reads[0], 0)

    def test_multiple_cabs_remain_unsupported(self):
        env = UnityPy.load(self.example.read_bytes())
        env.file.files["second-cab"] = next(iter(env.file.files.values()))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "two.bundle"
            path.write_bytes(env.file.save(packer="lz4"))
            with self.assertRaisesRegex(ValueError, "single-CAB"):
                catalog_crc.crc_and_size(path)


if __name__ == "__main__":
    unittest.main()
