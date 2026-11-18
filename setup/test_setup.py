"""Run in a disposable mock installation. No Unity or Steam installation is used."""
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import GallerySetup as setup


class FixtureBuilder:
    REVISION = 1
    baseline = [b"original-title", b"original-catalog"]
    def targets(self, game):
        return [game / "Annihilated_Data" / "title.bundle", game / "Annihilated_Data" / "catalog.bin"]

    def supported(self, game):
        return [p.read_bytes() for p in self.targets(game)] == self.baseline

    def build(self, game, out):
        for p in self.targets(game):
            suffix = b"-gallery" if self.REVISION == 1 else b"-gallery-v" + str(self.REVISION).encode()
            (out / p.name).write_bytes(p.read_bytes() + suffix)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name).resolve() / "安装 with spaces"
        (self.game / "Annihilated_Data").mkdir(parents=True)
        (self.game / "Annihilated.exe").write_bytes(b"game")
        self.builder = FixtureBuilder()
        self.files = self.builder.targets(self.game)
        for path, data in zip(self.files, self.builder.baseline):
            path.write_bytes(data)

    def cli(self, verb, code, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = setup.main([verb, str(self.game)], self.builder)
        self.assertEqual(result, code, stdout.getvalue() + stderr.getvalue())
        if code in (0, 10, 11):
            self.assertTrue(stdout.getvalue().strip())
            self.assertFalse(stderr.getvalue())
        if error:
            self.assertIn(error, stderr.getvalue())
        return stderr.getvalue()

    def data(self):
        return [p.read_bytes() for p in self.files]

    def test_toggle_idempotent_and_verified(self):
        self.cli("status", 10)
        self.assertEqual({p.name for p in self.game.iterdir()}, {"Annihilated.exe", "Annihilated_Data"})
        self.cli("enable", 0)
        self.cli("enable", 0)
        self.cli("status", 0)
        self.assertEqual(self.data(), [b"original-title-gallery", b"original-catalog-gallery"])
        self.cli("disable", 0)
        self.cli("disable", 0)
        self.cli("status", 10)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_unknown_content_and_foreign_files_are_preserved(self):
        self.files[1].write_bytes(b"another build")
        self.cli("enable", 1)
        self.cli("status", 1)
        self.assertEqual(self.data(), [b"original-title", b"another build"])
        self.assertFalse((self.game / setup.STATE_DIR).exists())

    def test_partial_external_update_refuses_to_restore_backups(self):
        self.cli("enable", 0)
        self.files[0].write_bytes(b"steam replacement")
        before = self.data()
        self.cli("status", 1)
        self.cli("disable", 1)
        self.assertEqual(self.data(), before)

    def test_game_update_after_disable_rebuilds_from_current_install(self):
        self.cli("enable", 0)
        self.cli("disable", 0)
        self.builder.baseline = [b"title-v2", b"catalog-v2"]
        for path, data in zip(self.files, self.builder.baseline):
            path.write_bytes(data)
        self.cli("status", 10)
        self.cli("enable", 0)
        self.cli("disable", 0)
        self.assertEqual(self.data(), [b"title-v2", b"catalog-v2"])

    def test_full_steam_repair_unmarks_gallery(self):
        self.cli("enable", 0)
        for p, data in zip(self.files, self.builder.baseline):
            p.write_bytes(data)
        self.cli("status", 10)
        self.cli("enable", 0)
        self.cli("status", 0)

    def test_modified_binaries_leave_owned_pair_enabled_and_restorable(self):
        self.cli("enable", 0)
        (self.game / "Annihilated.exe").write_bytes(b"updated steam binary")
        (self.game / "GameAssembly.dll").write_bytes(b"updated game logic")
        before = self.data()
        self.cli("status", 0)
        self.cli("enable", 0)
        self.assertEqual(self.data(), before)
        self.cli("disable", 0)
        self.cli("status", 10)
        self.assertEqual(self.data(), self.builder.baseline)
        self.assertEqual((self.game / "GameAssembly.dll").read_bytes(), b"updated game logic")
        self.assertEqual((self.game / "Annihilated.exe").read_bytes(), b"updated steam binary")

    def test_corrupt_backups_prevent_restore(self):
        self.cli("enable", 0)
        (self.game / setup.STATE_DIR / "original-0.bin").write_bytes(b"corrupt")
        before = self.data()
        self.cli("disable", 1)
        self.assertEqual(self.data(), before)

    def test_changed_localization_can_refresh_an_identical_output_pair(self):
        text = self.game / "Annihilated_Data" / "resources.assets"
        text.write_bytes(b"supported dialogue")
        self.cli("enable", 0)
        text.write_bytes(b"updated dialogue")
        before = self.data()
        mtimes = [p.stat().st_mtime_ns for p in self.files]
        self.cli("status", 11)
        self.cli("enable", 0)
        self.assertEqual(self.data(), before)
        self.assertEqual([p.stat().st_mtime_ns for p in self.files], mtimes)
        self.cli("status", 0)
        self.cli("disable", 0)
        self.assertEqual(text.read_bytes(), b"updated dialogue")

    def test_known_restoration_works_even_if_new_builder_cannot_build_current_game(self):
        self.cli("enable", 0)
        (self.game / "Annihilated_Data/resources.assets").write_bytes(b"incompatible dialogue")
        with patch.object(self.builder, "supported", return_value=False):
            self.cli("status", 11)
            self.cli("enable", 1)
            self.cli("disable", 0)
            self.cli("status", 10)
            self.cli("enable", 1)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_legacy_revision_three_and_current_content_stamp(self):
        art = self.game / "Annihilated_Data" / "art.dat"
        art.write_bytes(b"first art")
        class ContentBuilder(FixtureBuilder):
            REVISION = 3
            LEGACY_SOURCE_FINGERPRINT = hashlib.sha256(b"first art").hexdigest()
            def source_fingerprint(self, root):
                return hashlib.sha256((root / "Annihilated_Data/art.dat").read_bytes()).hexdigest()
            def build(self, root, output, *, source_game):
                for target in self.targets(root):
                    (output / target.name).write_bytes(target.read_bytes() + (source_game / "Annihilated_Data/art.dat").read_bytes())
        self.builder = ContentBuilder()
        self.cli("enable", 0)
        record = self.game / setup.STATE_DIR / "manifest.json"
        saved = json.loads(record.read_text())
        self.assertEqual(saved.pop("inputs"), self.builder.LEGACY_SOURCE_FINGERPRINT)
        record.write_text(json.dumps(saved))
        (self.game / "GameAssembly.dll").write_bytes(b"Steam refresh")
        self.cli("status", 0)
        self.assertNotIn("inputs", json.loads(record.read_text()))
        art.write_bytes(b"second art")
        self.cli("status", 11)
        self.cli("enable", 0)
        self.cli("status", 0)
        self.assertEqual(self.data(), [s + b"second art" for s in self.builder.baseline])
        self.assertEqual(json.loads(record.read_text())["inputs"], hashlib.sha256(b"second art").hexdigest())
        art.unlink()
        self.cli("status", 11)
        self.cli("enable", 1)
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_current_compatible_steam_pair_rebases_even_when_previously_enabled(self):
        self.cli("enable", 0)
        self.builder.baseline = [b"new steam title", b"new steam catalog"]
        for p, data in zip(self.files, self.builder.baseline):
            p.write_bytes(data)
        self.cli("status", 10)
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)
        self.cli("enable", 0)
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_catalog_selecting_a_new_bundle_never_touches_the_superseded_path(self):
        class CatalogBuilder(FixtureBuilder):
            def targets(self, root):
                folder = root / "Annihilated_Data"
                catalog = folder / "catalog.bin"
                title = "newhash.bundle" if catalog.is_file() and catalog.read_bytes().startswith(b"new-") else "title.bundle"
                return [folder / title, catalog]
        self.builder = CatalogBuilder()
        self.cli("enable", 0)
        retired = self.files[0]
        retired.write_bytes(b"inactive foreign file")
        self.files[1].write_bytes(b"new-catalog")
        self.files = self.builder.targets(self.game)
        self.files[0].write_bytes(b"new-stock-title")
        self.builder.baseline = self.data()
        self.cli("status", 10)
        self.cli("enable", 0)
        self.cli("disable", 0)
        self.assertEqual(self.data(), [b"new-stock-title", b"new-catalog"])
        self.assertEqual(retired.read_bytes(), b"inactive foreign file")

    def test_old_two_argument_builder_refreshes_on_changed_dialogue_without_revision_field(self):
        class LegacyBuilder:
            targets = self.builder.targets
            supported = self.builder.supported
            build = self.builder.build
        self.builder = LegacyBuilder()
        self.cli("enable", 0)
        (self.game / "Annihilated_Data/resources.assets").write_bytes(b"new translation")
        self.cli("status", 11)
        self.cli("enable", 0)
        self.cli("status", 0)

    def test_source_update_during_build_leaves_existing_patch_and_backups_in_place(self):
        source = self.game / "art.dat"
        source.write_bytes(b"v1")
        class RacingBuilder(FixtureBuilder):
            def source_fingerprint(self, root):
                return hashlib.sha256((root / "art.dat").read_bytes()).hexdigest()
            def build(self, stock, out, *, source_game):
                token = (source_game / "art.dat").read_bytes()
                for p in self.targets(stock):
                    (out / p.name).write_bytes(p.read_bytes() + token)
                if token == b"v2":
                    (source_game / "art.dat").write_bytes(b"v3")
        self.builder = RacingBuilder()
        self.cli("enable", 0)
        before = self.data()
        source.write_bytes(b"v2")
        self.cli("enable", 1)
        self.assertEqual(self.data(), before)
        self.cli("status", 11)
        self.cli("enable", 0)
        self.assertEqual(self.data(), [s + b"v3" for s in self.builder.baseline])
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_version_change_during_restoration_stops_before_second_target(self):
        self.cli("enable", 0)
        real_replace = os.replace
        def change_build(src, dst):
            real_replace(src, dst)
            if Path(dst) == self.files[0]:
                (self.game / "Annihilated.exe").write_bytes(b"updated between files")
        with patch.object(os, "replace", side_effect=change_build):
            self.cli("disable", 1)
        self.assertEqual(self.data(), [b"original-title", b"original-catalog-gallery"])
        self.cli("status", 1, "RECOVERY_REQUIRED")
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_stock_validator_receives_real_source_during_upgrade_and_reports_reasons(self):
        visits = []
        class ValidatingBuilder(FixtureBuilder):
            def validate_stock(self, root, *, source_game):
                visits.append((root == source_game, source_game))
                if not self.supported(root):
                    raise ValueError("unsupported selected title structure")
        self.builder = ValidatingBuilder()
        self.cli("enable", 0)
        self.builder.REVISION = 2
        self.cli("enable", 0)
        self.assertIn((False, self.game), visits)
        self.files[1].write_bytes(b"foreign changes")
        self.cli("disable", 1, "unsupported selected title structure")

    def test_concurrent_configuration_refuses_second_writer(self):
        with setup.install_lock(self.game), ThreadPoolExecutor(max_workers=1) as workers:
            workers.submit(self.cli, "enable", 1).result(timeout=10)
        self.assertEqual(self.data(), self.builder.baseline)
        self.cli("enable", 0)

    def test_failed_initial_build_changes_no_game_data(self):
        with patch.object(self.builder, "build", side_effect=OSError("builder failed")):
            self.cli("enable", 1, "builder failed")
        self.assertEqual(self.data(), self.builder.baseline)
        self.assertFalse((self.game / setup.STATE_DIR).exists())
        self.cli("status", 10)

    def test_unsafe_builder_target_rejected(self):
        foreign = Path(self.temp.name) / "foreign.bundle"
        foreign.write_bytes(b"foreign")
        with patch.object(self.builder, "targets", return_value=[foreign, self.files[1]]):
            self.cli("enable", 1)
        self.assertEqual(foreign.read_bytes(), b"foreign")

    def legacy(self, recognized=True):
        self.cli("enable", 0)
        record = self.game / setup.STATE_DIR / "manifest.json"
        saved = json.loads(record.read_text(encoding="utf-8"))
        saved.pop("revision", None)
        record.write_text(json.dumps(saved), encoding="utf-8")
        self.builder.REVISION = 2
        if recognized:
            hashes = tuple(entry["patched"] for entry in saved["files"])
            override = patch.object(setup, "LEGACY_PATCH", hashes)
            override.start()
            self.addCleanup(override.stop)

    def test_updates_verified_unversioned_install_and_still_restores_stock(self):
        self.legacy()
        self.builder.REVISION = 3
        old = self.data()
        self.cli("status", 11)
        self.assertEqual(self.data(), old)
        self.cli("enable", 0)
        self.cli("status", 0)
        self.assertEqual(self.data(), [b"original-title-gallery-v3", b"original-catalog-gallery-v3"])
        self.cli("enable", 0)
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_revision_two_to_three_reads_local_art_outside_stock_view(self):
        custom_art = Path("Annihilated_Data/StreamingAssets/aa/StandaloneWindows64/scenery.bundle")
        art = self.game / custom_art
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_bytes(b"game-art-fixture")
        views = []

        class ArtBuilder(FixtureBuilder):
            def build(self, stock, output, *, source_game=None):
                if source_game is None:
                    raise ValueError("source installation missing")
                views.append((source_game, stock == source_game, (stock / custom_art).exists()))
                for target in self.targets(stock):
                    (output / target.name).write_bytes(target.read_bytes() + str(self.REVISION).encode()
                                                       + (source_game / custom_art).read_bytes())

        self.builder = ArtBuilder()
        self.builder.REVISION = 2
        self.cli("enable", 0)
        self.builder.REVISION = 3
        self.cli("status", 11)
        self.cli("enable", 0)
        self.cli("status", 0)
        self.assertEqual(self.data(), [b"original-title3game-art-fixture", b"original-catalog3game-art-fixture"])
        self.assertEqual(views, [(self.game, True, True), (self.game, False, False)])
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)
        self.assertEqual(art.read_bytes(), b"game-art-fixture")

    def test_can_disable_old_version_without_updating(self):
        self.legacy()
        self.cli("status", 11)
        with patch.object(self.builder, "build", side_effect=AssertionError("do not update")):
            self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_upgrade_builds_while_old_gallery_is_live(self):
        self.legacy()
        old = self.data()
        def fail_build(stock, output):
            self.assertNotEqual(stock, self.game)
            self.assertTrue(self.builder.supported(stock))
            self.assertEqual(self.data(), old)
            raise OSError("fixture build failed")
        with patch.object(self.builder, "build", side_effect=fail_build):
            self.cli("enable", 1, "fixture build failed")
        self.assertEqual(self.data(), old)
        self.cli("status", 11)
        self.assertFalse((self.game / setup.STATE_DIR / "upgrade-work").exists())

    def test_abandoned_owned_build_view_reclaimed_on_retry(self):
        self.legacy()
        workspace = self.game / setup.STATE_DIR / "upgrade-work"
        workspace.mkdir()
        (workspace / "owner.txt").write_text("Annihilated CG Gallery upgrade workspace v1", encoding="ascii")
        (workspace / "game").mkdir()
        (workspace / "game" / "leftover-copy").write_bytes(b"old")
        self.cli("status", 11)
        self.assertTrue(workspace.exists())
        self.cli("enable", 0)
        self.assertFalse(workspace.exists())

    def test_unrecognized_work_directory_preserved(self):
        self.legacy()
        before = self.data()
        workspace = self.game / setup.STATE_DIR / "upgrade-work"
        workspace.mkdir()
        foreign = workspace / "myfile.txt"
        foreign.write_bytes(b"private")
        self.cli("enable", 1)
        self.assertEqual(self.data(), before)
        self.assertEqual(foreign.read_bytes(), b"private")

    def test_upgrade_failure_restores_old_gallery_then_allows_retry(self):
        self.legacy()
        old = self.data()
        self.interrupt_after_one_replace("enable", OSError("target locked"))
        self.assertEqual(self.data(), old)
        self.cli("status", 11)
        self.cli("enable", 0)
        self.cli("status", 0)

    def test_interrupted_upgrade_can_be_restored_to_stock(self):
        self.legacy()
        self.interrupt_after_one_replace("enable", KeyboardInterrupt())
        before = self.data()
        self.cli("status", 1, "RECOVERY_REQUIRED")
        self.assertEqual(self.data(), before)
        self.cli("disable", 0)
        self.assertEqual(self.data(), self.builder.baseline)

    def test_later_installed_revision_and_unknown_legacy_are_never_downgraded(self):
        self.legacy(recognized=False)
        before = self.data()
        self.cli("enable", 0)
        self.assertEqual(self.data(), before)
        self.cli("disable", 0)
        self.builder.REVISION = 3
        self.cli("enable", 0)
        newer = self.data()
        self.builder.REVISION = 2
        self.cli("status", 0)
        self.cli("enable", 0)
        self.assertEqual(self.data(), newer)

    def interrupt_after_one_replace(self, verb, exception):
        replace = os.replace
        def interrupted(src, dst):
            if Path(dst) == self.files[1]:
                raise exception
            return replace(src, dst)
        with patch.object(os, "replace", side_effect=interrupted):
            if isinstance(exception, KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.cli(verb, 0)
            else:
                self.cli(verb, 1)

    def test_exception_on_second_replace_restores_originals(self):
        self.interrupt_after_one_replace("enable", OSError("target locked"))
        self.assertEqual(self.data(), self.builder.baseline)
        self.cli("status", 10)

    def test_failed_disable_rolls_back_to_verified_enabled_pair(self):
        self.cli("enable", 0)
        before = self.data()
        self.interrupt_after_one_replace("disable", OSError("target locked"))
        self.assertEqual(self.data(), before)
        self.cli("status", 0)

    def test_steam_update_during_interruption_blocks_recovery(self):
        self.interrupt_after_one_replace("enable", KeyboardInterrupt())
        self.files[1].write_bytes(b"steam update")
        before = self.data()
        error = self.cli("status", 1)
        self.assertNotIn("RECOVERY_REQUIRED", error)
        self.cli("disable", 1)
        self.assertEqual(self.data(), before)

    def test_interrupted_enable_and_disable_have_read_only_status_and_explicit_recovery(self):
        for verb in ("enable", "disable"):
            if verb == "disable":
                self.cli("enable", 0)
            self.interrupt_after_one_replace(verb, KeyboardInterrupt())
            before = self.data()
            self.assertNotEqual(before, self.builder.baseline)
            self.cli("status", 1, "RECOVERY_REQUIRED")
            self.assertEqual(self.data(), before)
            self.cli("disable", 0)
            self.assertEqual(self.data(), self.builder.baseline)
            self.cli("status", 10)


if __name__ == "__main__":
    unittest.main()
