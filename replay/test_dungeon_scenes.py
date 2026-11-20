import json
import os
from pathlib import Path
import unittest

try:
    from . import dungeon_scenes as dungeon
except ImportError:
    import dungeon_scenes as dungeon


@unittest.skipUnless(os.getenv("V15_SCRIPTS") and os.getenv("V14_GALLERY"), "requires locally owned original game data")
class DungeonEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads(Path(os.environ["V15_SCRIPTS"]).read_text(encoding="utf-8"))
        cls.gallery = json.loads(Path(os.environ["V14_GALLERY"]).read_text(encoding="utf-8"))

    def test_whole_event_keeps_all_choices_and_art_under_one_entry(self):
        scenes = dungeon.build_dungeon_scenes(self.rows, self.gallery)
        self.assertEqual(len(scenes), 29)
        gold = next(s for s in scenes if s["label"] == "event25")
        self.assertEqual(gold["status"], "script-reviewed")
        self.assertEqual(len(gold["galleryIds"]), 2)
        self.assertFalse(any(s["label"] == "event26" for s in scenes))
        self.assertIn("Dungeon.events", gold["exits"])
        self.assertIn("@gosub Dungeon.ShowEventIllustration", gold["setupCommands"])
        self.assertIn("@gosub Dungeon.afterEvent", gold["finishCommands"])
        self.assertNotIn("presets", gold)

    def test_stale_roulette_outcome_cannot_be_published(self):
        changed = {**self.rows, "Dungeon": list(self.rows["Dungeon"])}
        pos = next(i for i, r in enumerate(changed["Dungeon"]) if r[3] == "# event25_forward")
        row = list(changed["Dungeon"][pos])
        row[3] = "# renamedOutcome"
        changed["Dungeon"][pos] = row
        scene = next(s for s in dungeon.build_dungeon_scenes(changed, self.gallery) if s["label"] == "event25")
        self.assertEqual(scene["status"], "candidate")

    def test_helper_only_appends_and_claims_no_default_story_option(self):
        start = len(self.rows["Dungeon"])
        edits = {"Dungeon": {start: "; existing guard"}}
        dungeon.add_dungeon_helpers(edits, self.rows)
        self.assertEqual(edits["Dungeon"][start], "; existing guard")
        self.assertTrue(all(i >= start for i in edits["Dungeon"]))
        self.assertFalse(any(isinstance(r, str) and r.startswith("@choice") for r in edits["Dungeon"].values()))
