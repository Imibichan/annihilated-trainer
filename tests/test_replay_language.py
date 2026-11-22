import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ReplayLanguageTests(unittest.TestCase):
    manager = ("Naninovel.LocalizationManager+Settings, Elringus.Naninovel.Runtime, "
               "Version=0.0.0.0, Culture=neutral, PublicKeyToken=null")
    relative = Path("NaninovelData/Saves/Settings.json")

    def setUp(self):
        from replay import language
        self.language = language
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.low = Path(root)
        self.enterContext(patch.object(language.iso, "local_low", return_value=self.low))
        self.registry = self.enterContext(patch.object(language, "_official_i2_locale", return_value=None))
        self.official = self.low / "DeathKumiai/Annihilated" / self.relative
        self.game = SimpleNamespace(company="Or161234abc", profile=self.low / "Or161234abc/Annihilated")
        self.private = self.game.profile / self.relative

    def write(self, path, pairs):
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {"objectJsonMap": {"keys": [k for k, _ in pairs], "values": [v for _, v in pairs]}}
        path.write_text(json.dumps(state), encoding="utf-8-sig")

    def fields(self):
        m = json.loads(self.private.read_bytes())["objectJsonMap"]
        return dict(zip(m["keys"], m["values"]))

    def sync(self):
        return self.language.sync_replay_language(self.game)

    def test_first_launch_inherits_only_the_official_locale(self):
        self.write(self.official, [(self.manager, '{"SelectedLocale":"zh-CN","Private":17}'), ("Audio", "music")])
        original = self.official.read_bytes()
        self.assertEqual(self.sync(), "zh-CN")
        self.assertEqual({k: json.loads(v) for k,v in self.fields().items()}, {self.manager: {"SelectedLocale":"zh-CN"}})
        self.assertEqual(self.official.read_bytes(), original)

    def test_cached_profile_replaces_stale_language_preserving_unrelated_game_settings(self):
        self.write(self.official, [(self.manager, '{"SelectedLocale":"zh-CN"}')])
        self.write(self.private, [("Audio","private audio"), (self.manager,'{"SelectedLocale":"en","Custom":19}')])
        self.registry.return_value = "en"
        self.assertEqual(self.sync(), "zh-CN")
        values = self.fields()
        self.assertEqual(values["Audio"], "private audio")
        self.assertEqual(json.loads(values[self.manager]), {"SelectedLocale":"zh-CN", "Custom":19})
        before = self.private.stat().st_mtime_ns
        self.sync()
        self.assertEqual(self.private.stat().st_mtime_ns, before)
        self.write(self.official, [(self.manager, '{"SelectedLocale":"ja"}')])
        self.assertEqual(self.sync(), "ja")
        self.assertEqual(json.loads(self.fields()[self.manager])["SelectedLocale"], "ja")

    def test_registry_only_profile_or_unreadable_source_settings(self):
        self.registry.return_value = "zh-CN"
        self.assertEqual(self.sync(), "zh-CN")
        self.official.parent.mkdir(parents=True, exist_ok=True)
        self.official.write_bytes(b"partial")
        self.registry.return_value = "en"
        self.assertEqual(self.sync(), "en")
        self.assertEqual(json.loads(self.fields()[self.manager])["SelectedLocale"], "en")

    def test_without_an_official_preference_leaves_native_defaults(self):
        self.assertIsNone(self.sync())
        self.assertFalse(self.private.exists())
        self.write(self.private, [(self.manager, '{"SelectedLocale":"en"}')])
        previous = self.private.read_bytes()
        self.assertIsNone(self.sync())
        self.assertEqual(previous, self.private.read_bytes())

    def test_malformed_private_data_and_original_destination_are_never_overwritten(self):
        self.write(self.official, [(self.manager, '{"SelectedLocale":"en"}')])
        self.private.parent.mkdir(parents=True)
        self.private.write_bytes(b"broken")
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(self.private.read_bytes(), b"broken")
        self.game.profile = self.official.parents[2]
        with self.assertRaises(ValueError):
            self.sync()

    def test_game_i2_binary_string_and_invalid_values(self):
        decode = self.language._i2_locale
        self.assertEqual(decode(b"Chinese (Simplified)\0"), "zh-CN")
        self.assertEqual(decode("English"), "en")
        self.assertEqual(decode(b"Japanese\0"), "ja")
        for unsupported in (23, b"\xff\x00", b"English\0corrupt", ""):
            self.assertIsNone(decode(unsupported))
