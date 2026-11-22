import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from replay import isolation as iso


def digest(data):
    return hashlib.sha256(data).hexdigest()


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "stock"
        self.target = self.base / "cache/game"
        self.saves = self.base / "LocalLow"
        self.saves.mkdir()
        self.profile_patch = patch.object(iso, "local_low", return_value=self.saves)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.stock = {name: ("original " + name).encode() for name in iso.STOCK_HASHES}
        self.stock_patch = patch.dict(iso.STOCK_HASHES, {k: digest(v) for k, v in self.stock.items()})
        self.stock_patch.start()
        self.addCleanup(self.stock_patch.stop)
        vendor = patch.object(iso, "VENDOR_HASH", digest(b"Steam"))
        vendor.start()
        self.addCleanup(vendor.stop)
        self.files = {
            "Annihilated.exe": b"game",
            "GameAssembly.dll": b"unmodified game assembly",
            "UnityPlayer.dll": b"player",
            "baselib.dll": b"base",
            iso.APP_INFO: b"DeathKumiai\nAnnihilated",
            iso.MANAGERS: b"settings\0DeathKumiai\0trailer",
            "Annihilated_Data/Plugins/x86_64/steam_api64.dll": b"Steam",
            "Annihilated_Data/Plugins/x86_64/lib_burst_generated.dll": b"native",
            "steam_appid.txt": b"real app id",
            "Annihilated_Data/StreamingAssets/story.bundle": b"story",
            **self.stock,
        }
        for name, content in self.files.items():
            self.write(self.source, name, content)

    @staticmethod
    def write(root, name, data):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def test_source_and_real_progress_untouched_including_after_reuse(self):
        saved = self.write(self.saves, "DeathKumiai/Annihilated/NaninovelData/Saves/GlobalSave.nson", b"progress")
        copy = iso.prepare_copy(self.source, self.target)
        self.assertRegex(copy.company, r"^Or16[0-9a-f]{7}$")
        self.assertEqual(copy.profile, self.saves / copy.company / "Annihilated")
        self.assertFalse(copy.profile.exists())
        self.assertEqual((copy.root / iso.VENDOR).read_bytes(), b"Steam")
        self.assertFalse((copy.root / "steam_appid.txt").exists())
        for name in (iso.APP_INFO, iso.MANAGERS):
            self.assertIn(copy.company.encode(), (copy.root / name).read_bytes())
            self.assertNotIn(b"DeathKumiai", (copy.root / name).read_bytes())
        self.assertEqual((copy.root / "GameAssembly.dll").read_bytes(), self.files["GameAssembly.dll"])
        story = copy.root / "Annihilated_Data/StreamingAssets/story.bundle"
        story.write_bytes(b"replay")
        self.assertEqual(iso.prepare_copy(self.source, self.target), copy)
        self.assertEqual(story.read_bytes(), self.files["Annihilated_Data/StreamingAssets/story.bundle"])
        self.assertEqual(saved.read_bytes(), b"progress")
        for name, data in self.files.items():
            self.assertEqual((self.source / name).read_bytes(), data, name)

    def test_unknown_locations_are_never_overwritten(self):
        unknown = self.write(self.base, "stranger/file.txt", b"keep")
        for destination in [self.source, self.source / "subdir", self.base, unknown.parent, self.saves / "DeathKumiai/Annihilated"]:
            with self.subTest(destination=destination), self.assertRaises((ValueError, OSError)):
                iso.prepare_copy(self.source, destination)
        self.assertEqual(unknown.read_bytes(), b"keep")
        self.assertFalse((self.source / "subdir").exists())

    def test_restores_enabled_gallery_using_verified_backups(self):
        state = self.source / ".annihilated-cg-gallery"
        files = []
        for index, (name, original) in enumerate(self.stock.items()):
            self.write(self.source, name, b"v1.4")
            files.append({"path": name, "original": digest(original), "patched": digest(b"v1.4")})
            self.write(state, f"original-{index}.bin", original)
        self.write(state, "manifest.json", json.dumps({"schema": 1, "files": files}).encode())
        copy = iso.prepare_copy(self.source, self.target)
        for name, original in self.stock.items():
            self.assertEqual((copy.root / name).read_bytes(), original)
            self.assertEqual((self.source / name).read_bytes(), b"v1.4")
        self.assertFalse((copy.root / state.name).exists())

    def test_rejects_bad_fallback_without_committing_partial_tree(self):
        name = next(iter(self.stock))
        self.write(self.source, name, b"v1.4")
        self.write(self.base / "fallback", name, b"different game build")
        with self.assertRaises((ValueError, OSError)):
            iso.prepare_copy(self.source, self.target, stock_fallback=self.base / "fallback")
        self.assertFalse(self.target.exists())
        self.write(self.base / "fallback", name, self.stock[name])
        copy = iso.prepare_copy(self.source, self.target, stock_fallback=self.base / "fallback")
        self.assertEqual((copy.root / name).read_bytes(), self.stock[name])

    def test_new_registered_title_and_catalog_take_precedence_over_previous_game_backup(self):
        old_title = next(name for name in self.stock if name.endswith(".bundle"))
        (self.source / old_title).unlink()
        name = "naninovelstartupui_assets_all_update-1.bundle"
        new_title = iso.AA + "StandaloneWindows64/" + name
        self.write(self.source, new_title, b"new UI")
        self.write(self.source, iso.AA + "catalog.bin", b"latest catalog")
        state = self.source / iso.STATE
        rows = [{"path":key, "original":digest(data), "patched":digest(b"historical patch")}
                for key, data in self.stock.items()]
        self.write(state, "manifest.json", json.dumps({"schema":1,"files":rows}).encode())
        for i, data in enumerate(self.stock.values()):
            self.write(state, f"original-{i}.bin", data)
        dependencies = {"addressables":SimpleNamespace(bundle_locations=lambda binary:[name]),
                        "catalog_crc":SimpleNamespace(locate=lambda binary,title: 4)}
        with patch.dict("sys.modules", dependencies):
            game = iso.prepare_copy(self.source, self.target)
        marker = json.loads((game.root / iso.MARKER).read_bytes())
        self.assertEqual(marker["titleFile"], new_title)
        self.assertEqual(marker["galleryBaseline"], "installed")
        self.assertEqual((game.root / iso.AA / "catalog.bin").read_bytes(), b"latest catalog")
        self.assertFalse((game.root / old_title).exists())

    def test_aborts_on_ambiguous_company_configuration(self):
        self.write(self.source, iso.MANAGERS, b"DeathKumiai repeated DeathKumiai")
        with self.assertRaises(ValueError):
            iso.prepare_copy(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_prior_private_copy_with_missing_vendor_library_can_upgrade(self):
        copy = iso.prepare_copy(self.source, self.target)
        plugin = copy.root / iso.VENDOR
        plugin.unlink()
        with self.assertRaises(ValueError):
            iso.verify_copy(copy.root)
        self.assertEqual(iso.prepare_copy(self.source, self.target), copy)
        self.assertEqual(plugin.read_bytes(), b"Steam")
        self.assertFalse(plugin.samefile(self.source / iso.VENDOR))

    def test_cached_game_still_checks_the_vendor_file_in_current_install(self):
        copy = iso.prepare_copy(self.source, self.target)
        self.write(self.source, iso.VENDOR, b"changed SDK")
        with self.assertRaises(ValueError):
            iso.prepare_copy(self.source, self.target)
        self.assertEqual((copy.root / iso.VENDOR).read_bytes(), b"Steam")

    def test_published_pair_can_run_when_original_backups_are_missing(self):
        published = {name: ("verified-v14 " + name).encode() for name in self.stock}
        hashes = {name: digest(data) for name, data in published.items()}
        for name, data in published.items():
            self.write(self.source, name, data)
        with patch.dict(iso.V14_HASHES, hashes):
            copy = iso.prepare_copy(self.source, self.target)
        self.assertEqual(json.loads((copy.root / iso.MARKER).read_text())["galleryBaseline"], "published-v1.4")
        for name, data in published.items():
            self.assertEqual((copy.root / name).read_bytes(), data)

    def test_mixed_published_and_original_pair_with_no_backup_is_rejected(self):
        name = next(iter(self.stock))
        self.write(self.source, name, b"known v14")
        with patch.dict(iso.V14_HASHES, {name: digest(b"known v14")}), self.assertRaises(ValueError):
            iso.prepare_copy(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_rejects_reintroduced_steam_and_hardlinked_payload(self):
        copy = iso.prepare_copy(self.source, self.target)
        steam = self.write(copy.root, "Annihilated_Data/Plugins/x86_64/steam_api64.dll", b"bad")
        with self.assertRaises(ValueError):
            iso.verify_copy(copy.root)
        steam.unlink()
        file = copy.root / "Annihilated_Data/StreamingAssets/story.bundle"
        file.unlink()
        os.link(self.source / file.relative_to(copy.root), file)
        with self.assertRaises(ValueError):
            iso.verify_copy(copy.root)

    def test_grouped_profile_rejects_save_hardlinked_to_original(self):
        copy = iso.prepare_copy(self.source, self.target)
        original = self.write(self.saves, "DeathKumiai/Annihilated/NaninovelData/Saves/GlobalSave.nson", b"keep")
        save_dir = copy.profile / "NaninovelData/Saves"
        save_dir.mkdir(parents=True)
        os.link(original, save_dir / original.name)
        with self.assertRaises(ValueError):
            iso.verify_copy(copy.root)
        self.assertEqual(original.read_bytes(), b"keep")

    @unittest.skipUnless(os.name == "nt", "Windows path case")
    def test_differently_cased_paths_can_reuse_owned_copy(self):
        copy = iso.prepare_copy(self.source, self.target)
        reused = iso.prepare_copy(str(self.source).upper(), str(self.target).upper())
        self.assertEqual(copy, reused)

    def test_launch_environment_is_local_and_original_environment_survives(self):
        with patch.dict(os.environ, {"SteamAppId": "123", "STEAM_COMPAT_DATA_PATH":"bad", "PATH":r"G:\Steam", "SystemRoot":r"C:\Windows"}, clear=True):
            env = iso.launch_environment()
            self.assertFalse(any(key.lower().startswith("steam") for key in env))
            self.assertNotIn("Steam", env["PATH"])
            self.assertIn("System32", env["PATH"])
            self.assertEqual(os.environ["SteamAppId"], "123")


if __name__ == "__main__":
    unittest.main()
