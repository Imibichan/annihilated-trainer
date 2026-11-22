import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from replay import isolation as iso, launch, migration
from replay.launch import generation, session_lock


class ReplayMigrationTests(unittest.TestCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source = root / "Steam game"
        self.cache = root / "sandbox"
        self.low = root / "LocalLow"
        self.low.mkdir()
        self.hashfile = iso.AA + "catalog.hash"
        self.script = "naninovel_assets_naninovel_" + "2" * 32 + ".bundle"
        self.script_rel = iso.AA + "StandaloneWindows64/" + self.script
        self.catalog = iso.AA + "catalog.bin"
        self.index = self.write(root / "index", b"index")
        files = {name: name.encode() for name in iso.ROOT_REQUIRED | set(iso.STOCK_HASHES)}
        files.update({iso.APP_INFO: b"DeathKumiai\nAnnihilated", iso.MANAGERS: b"prefix DeathKumiai suffix",
                      iso.VENDOR: b"original Valve", self.hashfile: b"historical hash", self.script_rel: b"program"})
        for name, data in files.items():
            self.write(self.source / name, data)
        self.enterContext(patch.object(iso, "local_low", return_value=self.low))
        self.enterContext(patch.object(iso, "VENDOR_HASH", iso._file_hash(self.source / iso.VENDOR)))
        self.enterContext(patch.dict(iso.STOCK_HASHES, {n: iso._file_hash(self.source / n) for n in iso.STOCK_HASHES}))
        title_name = next(Path(n).name for n in iso.STOCK_HASHES if n.endswith(".bundle"))
        provider = SimpleNamespace(bundle_locations=lambda blob: [self.script, title_name])
        self.enterContext(patch.dict(sys.modules, {"addressables": provider}))
        self.cache.mkdir()

    def legacy(self, marker=True, receipt=False):
        folder = self.cache / migration._legacy_id(self.source, self.source)
        game = folder / "game"
        folder.mkdir()
        shutil.copytree(self.source, game)
        company = "Or15" + hashlib.sha256(folder.name.encode()).hexdigest()[:7]
        for name in (iso.APP_INFO, iso.MANAGERS):
            path = game / name
            path.write_bytes(path.read_bytes().replace(b"DeathKumiai", company.encode()))
        if marker:
            iso.atomic_json(game / iso.MARKER, {"schema": 1, "root": str(game), "source": str(self.source),
                            "company": company, "managerSha256": iso._file_hash(game / iso.MANAGERS),
                            "sourceBuild": iso.legacy_stamp(game)})
        if receipt:
            self.write(game / ".v15-program.json", b'{"scenes":204}')
        return folder, game, self.low / company / iso.GAME

    def fresh(self):
        folder = generation(self.cache, self.source, self.index)
        game = iso.prepare_copy(self.source, folder / "game", program_inputs=launch.program_inputs(self.index))
        marker = json.loads((game.root / iso.MARKER).read_bytes())
        receipt = {"packed": {"bundle": self.script}, "bundleSha": iso._file_hash(game.root / self.script_rel),
                   "titleSha": iso._file_hash(game.root / marker["titleFile"]),
                   "catalogSha": iso._file_hash(game.root / self.catalog)}
        iso.atomic_json(game.root / ".v16-program.json", receipt)
        return game

    def global_save(self, profile):
        inner = {"GlobalVariableMap": {"keys": ["G_v15Lead", "G_v15Last", "G_unrelated"],
                                      "values": ["2", "128812", "77"]}}
        outer = {"objectJsonMap": {"keys": [migration.STATE, "OtherManager"], "values": [json.dumps(inner), "extra"]}}
        raw = json.dumps(outer).encode("utf-8-sig")
        compressor = zlib.compressobj(wbits=-15)
        return self.write(profile / migration.SAVE, compressor.compress(raw) + compressor.flush())

    def run_upgrade(self, game):
        folders = migration.legacy_folders(self.source, self.cache)
        return migration.retire_old_games(self.source, self.cache, game, folders)

    def test_font_receipt_must_match_before_retiring_the_previous_game(self):
        _, old, _ = self.legacy()
        font = iso.AA + "StandaloneWindows64/startupuiinitialdependencies_assets_all_" + "3" * 32 + ".bundle"
        source_font = self.write(self.source / font, b"installed font")
        current = self.fresh()
        marker = json.loads((current.root / iso.MARKER).read_bytes())
        marker["fontFile"] = font
        iso.atomic_json(current.root / iso.MARKER, marker)
        (current.root / font).write_bytes(b"menu with additional glyphs")
        receipt_path = current.root / ".v16-program.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["fontSha"] = iso._file_hash(source_font)
        iso.atomic_json(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, "资源回读"):
            self.run_upgrade(current)
        self.assertTrue(old.is_dir())
        receipt["fontSha"] = iso._file_hash(current.root / font)
        iso.atomic_json(receipt_path, receipt)
        self.assertTrue(self.run_upgrade(current)["removed"])
        self.assertFalse(old.exists())

    def test_marker_cannot_disguise_an_unrelated_file_as_the_menu_font(self):
        current = self.fresh()
        marker = json.loads((current.root / iso.MARKER).read_bytes())
        marker["fontFile"] = "UnityPlayer.dll"
        iso.atomic_json(current.root / iso.MARKER, marker)
        with self.assertRaises(ValueError):
            iso.verify_copy(current.root)

    def test_completed_old_build_and_current_marker_only_copy_both_retired(self):
        _, first, profile = self.legacy(receipt=True)
        original = self.global_save(profile)
        official = self.global_save(self.low / iso.SOURCE_COMPANY / iso.GAME)
        before = original.read_bytes()
        self.write(profile / migration.SAVE.parent / "GameSave001.nson", b"private slot")
        self.write(self.source / self.hashfile, b"new release")
        _, partial, _ = self.legacy(marker=False)
        replacement = self.fresh()
        report = self.run_upgrade(replacement)
        self.assertFalse(first.exists())
        self.assertFalse(partial.exists())
        self.assertEqual(len(report["removed"]), 2)
        self.assertEqual(set(report["preferences"]), set(migration.KEYS))
        fresh = replacement.profile / migration.SAVE
        keys = json.loads(zlib.decompress(fresh.read_bytes(), -15))["objectJsonMap"]["keys"]
        self.assertEqual(keys, [migration.STATE])
        self.assertNotIn("G_unrelated", zlib.decompress(fresh.read_bytes(), -15).decode("utf-8-sig"))
        self.assertEqual([p.name for p in fresh.parent.iterdir()], ["GlobalSave.nson"])
        self.assertEqual(official.read_bytes(), before)
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(self.run_upgrade(replacement)["removed"], [])

    def test_second_game_update_transfers_preferences_and_leaves_one_game(self):
        first = self.fresh()
        self.global_save(first.profile)
        self.write(self.source / "GameAssembly.dll", b"new assembly with unchanged catalog hash")
        second = self.fresh()
        self.assertNotEqual(first.root, second.root)
        self.run_upgrade(second)
        self.assertFalse(first.root.exists())
        self.assertEqual(migration._preferences(second.profile)[1], {"G_v15Lead":"2","G_v15Last":"128812"})
        self.assertEqual(list(self.cache.glob("build-*/game")), [second.root])

    def test_interrupted_legacy_payload_without_marker_recognized_from_same_build(self):
        folder, old, _ = self.legacy(marker=False)
        partial = folder / ".orien-prepare-123abc89/payload"
        partial.parent.mkdir()
        old.rename(partial)
        (partial / "Annihilated.exe").unlink()
        self.run_upgrade(self.fresh())
        self.assertFalse(partial.exists())

    def test_v15_marked_payload_before_rename_and_partial_missing_member(self):
        folder, old, _ = self.legacy()
        partial = folder / ".orien-prepare-123abc89/payload"
        partial.parent.mkdir()
        old.rename(partial)
        (partial / iso.MANAGERS).unlink()
        report = self.run_upgrade(self.fresh())
        self.assertEqual(report["removed"], [folder.name])
        self.assertFalse(partial.exists())

    def test_editable_config_in_both_old_copy_and_install_is_not_removed(self):
        relative = iso.DATA + "/boot.config"
        self.write(self.source / relative, b"real config")
        _, old, _ = self.legacy()
        (old / relative).write_bytes(b"personal config")
        report = self.run_upgrade(self.fresh())
        self.assertTrue(report["preserved"])
        self.assertEqual((old / relative).read_bytes(), b"personal config")

    def test_even_authenticated_journal_cannot_reference_root_relative_members(self):
        folder, old, _ = self.legacy()
        sent = self.write(self.source.parent / "sentinel", b"safe")
        key = str(sent)[len(sent.drive):]
        self.assertTrue(key.startswith("\\"))
        for field in ("files","directories"):
            plan = {"folder":str(folder),"source":str(self.source),"cache":str(self.cache),
                    "target":"game","directoryId":old.stat().st_ino,"files":{},"directories":{}}
            plan[field][key] = migration._file_id(sent) if field == "files" else sent.parent.stat().st_ino
            plan["signature"] = migration._sign(self.cache, plan, create=True)
            with self.assertRaises(ValueError):
                migration._finish(self.source, self.cache, folder, plan)
            self.assertTrue(old.exists())
            self.assertEqual(sent.read_bytes(), b"safe")

    @unittest.skipUnless(os.name == "nt", "Windows alternate namespace")
    def test_resume_when_files_and_directories_resolve_through_different_windows_names(self):
        # NTFS's literal drive namespace provides a real second name for these
        # scratch files. Simulate the MSIX projection observed on LocalAppData:
        # GetFinalPathNameByHandle returns that alternate name for files only.
        folder, old, _ = self.legacy()
        replacement = self.fresh()
        original_resolve = Path.resolve
        def projected(path, *args, **kwargs):
            result = original_resolve(path, *args, **kwargs)
            if path.is_relative_to(folder) and path.is_file() and not str(path).startswith("\\\\?\\"):
                return Path("\\\\?\\" + str(result))
            return result
        with patch.object(Path, "resolve", projected):
            probe = old / iso.MARKER
            self.assertFalse(probe.resolve().is_relative_to(old.resolve()))
            self.assertTrue(probe.resolve().parent.samefile(old))
            with patch.object(migration, "_finish", side_effect=OSError("interrupted")):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    self.run_upgrade(replacement)
            self.assertTrue((folder / migration.JOURNAL).is_file())
            self.assertEqual(self.run_upgrade(replacement)["removed"], [folder.name])
        self.assertFalse(old.exists())
        self.assertFalse((folder / migration.JOURNAL).exists())

    def test_mapped_file_with_same_relative_suffix_in_foreign_directory_is_rejected(self):
        _, old, _ = self.legacy()
        other = self.write(self.source.parent / "unrelated" / iso.MARKER, b"outside")
        target = old / iso.MARKER
        original_resolve = Path.resolve
        def foreign(path, *args, **kwargs):
            return other if path == target else original_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", foreign), self.assertRaisesRegex(ValueError, "超出"):
            migration._strict_child(old, iso.MARKER)
        self.assertEqual(other.read_bytes(), b"outside")

    def test_previous_content_build_without_marker_needs_matching_native_players(self):
        _, old, _ = self.legacy(marker=False)
        self.write(self.source / self.hashfile, b"new catalog registration")
        self.write(self.source / "GameAssembly.dll", b"new managed assembly")
        self.write(self.source / iso.MANAGERS, b"updated DeathKumiai manager")
        replacement = self.fresh()
        player = old / "UnityPlayer.dll"
        known = player.read_bytes()
        player.write_bytes(b"foreign engine")
        self.assertEqual(self.run_upgrade(replacement)["removed"], [])
        player.write_bytes(known)
        self.assertEqual(len(self.run_upgrade(replacement)["removed"]), 1)
        self.assertFalse(old.exists())

    def test_forged_marker_or_unknown_content_never_deleted(self):
        _, old, _ = self.legacy()
        replacement = self.fresh()
        marker = old / iso.MARKER
        original = marker.read_bytes()
        values = json.loads(original)
        for key, value in [("root", str(self.source)), ("source", str(self.low)), ("company", iso.SOURCE_COMPANY)]:
            iso.atomic_json(marker, {**values, key:value})
            self.assertEqual(self.run_upgrade(replacement)["removed"], [])
            self.assertTrue(old.exists())
        marker.write_bytes(original)
        foreign = self.write(old / "Annihilated_Data/my-notes.txt", b"keep")
        self.assertEqual(self.run_upgrade(replacement)["removed"], [])
        self.assertEqual(foreign.read_bytes(), b"keep")
        foreign.unlink()
        os.link(self.index, foreign)
        self.assertEqual(self.run_upgrade(replacement)["removed"], [])
        self.assertTrue(foreign.samefile(self.index))

    def test_reparse_point_inside_legacy_never_followed(self):
        _, old, _ = self.legacy()
        private = old / "Annihilated_Data/unknown"
        try:
            private.symlink_to(self.low, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            import _winapi
            _winapi.CreateJunction(str(self.low), str(private))
        self.assertEqual(self.run_upgrade(self.fresh())["removed"], [])
        self.assertTrue(private.is_symlink() or os.path.isjunction(private))

    def test_recognizes_existing_compiler_work_but_keeps_foreign_temp_file(self):
        _, old, _ = self.legacy()
        work = old / iso.AA / "StandaloneWindows64/.replay-build-123abcde"
        self.write(work / "previous.bundle", b"old temporary asset")
        note = self.write(work / "readme.txt", b"keep")
        replacement = self.fresh()
        self.assertEqual(self.run_upgrade(replacement)["removed"], [])
        self.assertEqual(note.read_bytes(), b"keep")
        note.unlink()
        self.run_upgrade(replacement)
        self.assertFalse(old.exists())

    def test_interrupted_private_copy_resumes_and_foreign_stage_is_preserved(self):
        original = shutil.copyfile
        def fail_once(source, target, **kwargs):
            if target.name == "UnityPlayer.dll":
                raise OSError("copy interrupted")
            return original(source, target, **kwargs)
        with patch.object(shutil, "copyfile", fail_once), self.assertRaisesRegex(OSError, "interrupted"):
            self.fresh()
        generation_root = generation(self.cache, self.source, self.index)
        self.assertFalse((generation_root / "game").exists())
        extra = self.write(generation_root / ".game.building/foreign.txt", b"keep")
        with self.assertRaises(ValueError):
            self.fresh()
        self.assertEqual(extra.read_bytes(), b"keep")
        extra.unlink()
        self.assertTrue(self.fresh().executable.is_file())

    def test_new_update_retires_interrupted_copy_with_truncated_catalog(self):
        first = self.fresh()
        stage = first.root.with_name(".game.building")
        first.root.rename(stage)
        (stage / self.catalog).write_bytes(b"incomplete")
        (stage / ".v16-program.json").unlink()
        self.write(self.source / self.hashfile, b"another update")
        second = self.fresh()
        self.run_upgrade(second)
        self.assertFalse(stage.exists())

    def test_modified_v16_inventory_cannot_authorize_removal_of_new_file(self):
        first = self.fresh()
        note = self.write(first.root / "Annihilated_Data/notes.txt", b"keep")
        path = first.root / iso.MARKER
        data = json.loads(path.read_bytes())
        data["copiedFiles"].append("Annihilated_Data/notes.txt")
        iso.atomic_json(path, data)
        self.write(self.source / self.hashfile, b"new build")
        report = self.run_upgrade(self.fresh())
        self.assertTrue(report["preserved"])
        self.assertEqual(note.read_bytes(), b"keep")

    def test_orphaned_running_unity_child_refuses_cleanup(self):
        folder, old, _ = self.legacy()
        child = SimpleNamespace(stdout=(str(old / "Annihilated.exe") + "\n").encode(), check_returncode=lambda: None)
        with patch.object(iso, "windows_powershell", return_value=child), self.assertRaises(RuntimeError):
            migration.check_running_games(self.cache, [folder])

    def test_foreign_retirement_record_cannot_authorize_deletion(self):
        folder, old, _ = self.legacy()
        replacement = self.fresh()
        foreign = self.write(old / "notes", b"keep")
        iso.atomic_json(folder / migration.JOURNAL, {"folder":str(folder), "source":str(self.source),
                        "cache":str(self.cache), "target":"game", "directoryId":old.stat().st_ino,
                        "files":{"notes":migration._file_id(foreign)}, "signature":"0"*64})
        self.assertEqual(self.run_upgrade(replacement)["removed"], [])
        self.assertEqual(foreign.read_bytes(), b"keep")

    def test_interrupted_retirement_and_restart(self):
        folder, old, profile = self.legacy()
        self.global_save(profile)
        replacement = self.fresh()
        unlink = Path.unlink
        def interrupt(path, *args, **kwargs):
            if path.name == "UnityPlayer.dll" and migration.RETIRED in path.parts:
                raise PermissionError("simulated interruption")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupt), self.assertRaises(PermissionError):
            self.run_upgrade(replacement)
        self.assertFalse(old.exists())
        self.assertTrue((folder / migration.JOURNAL).exists())
        seeded = (replacement.profile / migration.SAVE).read_bytes()
        report = self.run_upgrade(replacement)
        self.assertIn(folder.name, report["removed"])
        self.assertFalse((folder / migration.RETIRED).exists())
        self.assertEqual((replacement.profile / migration.SAVE).read_bytes(), seeded)

    def test_invalid_new_receipt_never_retires_old_game(self):
        _, old, _ = self.legacy()
        replacement = self.fresh()
        self.write(replacement.root / self.script_rel, b"corrupt")
        with self.assertRaises(ValueError):
            self.run_upgrade(replacement)
        self.assertTrue(old.exists())

    def test_normal_prepare_repairs_registered_assets_and_recovers_each_patched_file(self):
        import unittest.mock as mock
        aa = Path(iso.AA)
        title = next(n for n in iso.STOCK_HASHES if n.endswith(".bundle"))
        font = iso.AA + "StandaloneWindows64/startupuiinitialdependencies_assets_all_abc.bundle"
        self.write(self.source / font, b"original font")
        ordinary = [iso.DATA + "/Plugins/x86_64/lib_burst_generated.dll",
                    iso.DATA + "/il2cpp_data/Metadata/global-metadata.dat", iso.AA + "StandaloneWindows64/scene.bundle"]
        for n in ordinary:
            self.write(self.source / n, b"official bytes")
        def patch_title(source, game):
            self.assertEqual((game / title).read_bytes(), (source / title).read_bytes())
            (game / title).write_bytes(b"patched title")
        def patch_scripts(source, game, edits):
            self.assertEqual((game / self.script_rel).read_bytes(), (source / self.script_rel).read_bytes())
            self.assertEqual((game / self.catalog).read_bytes(), (source / self.catalog).read_bytes())
            (game / self.script_rel).write_bytes(b"patched script")
            (game / self.catalog).write_bytes(b"patched catalog")
            return {"bundle":self.script}
        def patch_font(source, game, edits):
            self.assertEqual((game / font).read_bytes(), b"original font")
            (game / font).write_bytes(b"patched font")
            (game / self.catalog).write_bytes(b"catalog with script and font")
            return {"added": 1}
        compile_mock = mock.Mock(return_value=({},{"artworks":15,"scenes":204}))
        support = {"program":SimpleNamespace(compile_replays=compile_mock),
                   "addressables":SimpleNamespace(address_paths=lambda blob:{}),
                   "replay.menu_font":SimpleNamespace(font_bundle=lambda root:root/font,
                         patch_menu_font=patch_font, MenuFontUnavailable=LookupError),
                   "replay.private_title":SimpleNamespace(ensure_replay_title=patch_title,title_path=lambda g,m:g/title),
                   "script_assets":SimpleNamespace(AA=aa,PLATFORM="StandaloneWindows64",_bundle=lambda p:p/self.script_rel,
                                      patch_scripts=patch_scripts,read_script_rows=lambda source:{})}
        self.index.write_bytes(b"{}")
        destination = generation(self.cache, self.source, self.index) / "game"
        with patch.dict(sys.modules, support):
            game, receipt = launch.prepare(self.source,destination,self.index)
            self.assertEqual(receipt.get("fontSha"), iso._file_hash(game.root / font))
            self.global_save(game.profile)
            original_save = (game.profile / migration.SAVE).read_bytes()
            (game.root / ordinary[0]).unlink()
            (game.root / ordinary[1]).write_bytes(b"wrong metadata")
            # Match size and timestamp to exercise content verification.
            asset = game.root / ordinary[2]
            clock = asset.stat()
            asset.write_bytes(b"x" * clock.st_size)
            os.utime(asset, ns=(clock.st_atime_ns, clock.st_mtime_ns))
            game, _ = launch.prepare(self.source,destination,self.index)
            self.assertEqual(compile_mock.call_count, 1)
            self.assertTrue(all((game.root / p).read_bytes() == b"official bytes" for p in ordinary))
            for count, name in enumerate([self.script_rel,self.catalog,title,font,".v16-program.json"], 2):
                path = game.root / name
                if count % 2:
                    path.unlink()
                else:
                    path.write_bytes(b"truncated")
                game, _ = launch.prepare(self.source,destination,self.index)
                self.assertEqual(compile_mock.call_count, count)
                self.assertEqual((game.root / self.script_rel).read_bytes(), b"patched script")
            self.assertEqual((game.profile / migration.SAVE).read_bytes(), original_save)

    def test_only_gui_launch_announces_new_warning_once_and_report_lists_reasons(self):
        report = {"gameRoot":"scratch", "scenes":204, "artworks":15, "migration":{"preserved":[], "removed":[]}}
        with patch.object(launch.ctypes.windll.user32, "MessageBoxW") as message:
            launch.compatibility_report(self.cache, "first", report, show=True)
            message.assert_not_called()
            report["excludedPresets"] = {"mage.4":{"取回魔力":"缺少原作画面"}}
            report["migration"]["preserved"] = [["old game","存在未知文件"]]
            out = launch.compatibility_report(self.cache, "first", report, show=False)
            message.assert_not_called()
            lines = Path(out).read_text(encoding="utf-8-sig")
            self.assertIn("取回魔力　缺少原作画面", lines)
            self.assertIn("old game　存在未知文件", lines)
            launch.compatibility_report(self.cache, "first", report, show=True)
            launch.compatibility_report(self.cache, "first", report, show=True)
            message.assert_called_once()
            self.assertIn(out, message.call_args.args[1])

    def test_missing_foreign_language_font_leaves_playable_entries_available(self):
        report = {"gameRoot":"scratch", "scenes":204, "artworks":15, "migration":{"preserved":[], "removed":[]},
                  "fontWarning":"部分菜单字形缺失", "replayLocale":"zh-CN"}
        self.cache.mkdir(exist_ok=True)
        with patch.object(launch.ctypes.windll.user32, "MessageBoxW") as message:
            name = launch.compatibility_report(self.cache, "current", report, show=True)
            self.assertIn("部分菜单字形缺失", Path(name).read_text(encoding="utf-8-sig"))
            message.assert_not_called()
            report["replayLocale"] = "ja"
            launch.compatibility_report(self.cache, "current", report, show=True)
            launch.compatibility_report(self.cache, "current", report, show=True)
            message.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows byte range lock")
    def test_active_v15_lock_rejects_parallel_launch(self):
        folder, old, _ = self.legacy()
        with session_lock(folder):
            with self.assertRaisesRegex(RuntimeError, "V1.5"), session_lock(folder):
                pass
        self.assertTrue(old.is_dir())
