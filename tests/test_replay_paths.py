import os
from pathlib import Path
import tempfile
import unittest

from replay import isolation as iso, launch, migration


@unittest.skipUnless(os.name == "nt", "Windows replay path compatibility")
class ReplayPathTests(unittest.TestCase):
    def test_io_and_display_round_trip_for_drive_and_network_paths(self):
        for path, extended in (
            (r"C:\玩家\游戏", r"\\?\C:\玩家\游戏"),
            (r"\\server\share\游戏", r"\\?\UNC\server\share\游戏"),
        ):
            with self.subTest(path=path):
                self.assertEqual(iso.io_path(path), Path(extended))
                self.assertEqual(iso.io_path(extended), Path(extended))
                self.assertEqual(iso.display_path(extended), Path(path))
        for path in (r"\\.\PhysicalDrive0", r"\\?\GLOBALROOT\Device\HarddiskVolume1"):
            with self.assertRaises(ValueError):
                iso.io_path(path)

    def test_old_cache_and_overlap_checks_recognize_both_spellings(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            extended = iso.io_path(game)
            self.assertEqual(launch.cache_folder(game), launch.cache_folder(extended))
            self.assertEqual(migration._legacy_id(game, game), migration._legacy_id(extended, extended))
            self.assertTrue(iso._same_directory(str(game), extended))
            self.assertTrue(iso._overlap(extended / "copy", game))
            self.assertTrue(iso._overlap(game, extended / "copy"))
            self.assertFalse(iso._overlap(extended / "two", game / "one"))
