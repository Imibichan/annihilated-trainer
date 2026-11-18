import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gallery_builder as builder


class SourceCompatibilityTests(unittest.TestCase):
    def test_missing_install_is_unsupported(self):
        self.assertFalse(builder.supported(Path(__file__).parent / "missing-game"))

    @unittest.skipUnless("GALLERY_TEST_GAME" in os.environ, "requires an installed game")
    def test_pack_matches_installed_art_and_text(self):
        game = Path(os.environ["GALLERY_TEST_GAME"])
        self.assertTrue(builder.supported(game))
        bundle, catalog = builder.targets(game)
        self.assertEqual(catalog.name, "catalog.bin")
        self.assertTrue(bundle.is_file())
        data = json.loads(builder.index_file().read_text(encoding="utf-8"))
        self.assertEqual(data["resourcesSize"], (game/"Annihilated_Data/resources.assets").stat().st_size)

    @unittest.skipUnless("GALLERY_TEST_GAME" in os.environ, "requires original catalog")
    def test_selects_the_catalogued_title_after_steam_renames_it(self):
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder)
            aa = game / "Annihilated_Data/StreamingAssets/aa"
            bundles = aa / "StandaloneWindows64"
            bundles.mkdir(parents=True)
            new = "naninovelstartupui_assets_all_0123456789abcdef0123456789abcdef.bundle"
            (bundles / new).touch()
            source = Path(os.environ["GALLERY_TEST_GAME"])
            stock, catalog = builder.targets(source)
            (bundles / stock.name).touch()
            (aa / "catalog.bin").write_bytes(catalog.read_bytes().replace(stock.name.encode(), new.encode()))
            self.assertEqual(builder.targets(game)[0], bundles / new)

    @unittest.skipUnless("GALLERY_TEST_GAME" in os.environ, "requires original title and catalog")
    def test_compatible_catalog_update_with_new_bundle_identity(self):
        source = Path(os.environ["GALLERY_TEST_GAME"])
        old, catalog = builder.targets(source)
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder)
            target = game / old.relative_to(source)
            target.parent.mkdir(parents=True)
            old_id = old.stem.rsplit("_", 1)[1]
            new_id = "0123456789abcdef0123456789abcdef"
            shutil.copyfile(old, target.with_name(old.name.replace(old_id, new_id)))
            updated = catalog.read_bytes().replace(old_id.encode(), new_id.encode())
            updated = updated.replace(bytes.fromhex(old_id), bytes.fromhex(new_id))
            (game / catalog.relative_to(source)).write_bytes(updated)
            (game / "Annihilated.exe").touch()
            shutil.copyfile(source / "Annihilated_Data/resources.assets", game / "Annihilated_Data/resources.assets")
            self.assertTrue(builder.supported(game))
            from catalog_crc import crc_and_size
            crc, size = crc_and_size(old)
            signature = struct.pack("<II", crc, size)
            self.assertEqual(updated.count(signature), 1)
            wrong = updated.replace(signature, struct.pack("<II", crc ^ 1, size))
            (game / catalog.relative_to(source)).write_bytes(wrong)
            self.assertFalse(builder.supported(game))


if __name__ == "__main__":
    unittest.main()
