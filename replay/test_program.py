"""Contract for scene boundaries in the original game scripts."""
import json
import os
from pathlib import Path
import unittest

from program import make_program


class ReplayProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = json.loads(Path(os.environ["REPLAY_SCRIPT_FIXTURE"]).read_text(encoding="utf-8"))
        scene = {"id":"prologue-chat", "group":"Hero", "chapter":0, "title":"营火交谈",
                 "status":"script-reviewed", "source":"Opening3", "label":"heroScene",
                 "setupCommands":[], "exits":["Opening3.hanasiChoice"]}
        cls.edits = make_program(cls.scripts, [scene], [])
        cls.menu = list(cls.edits["Test2"].values())

    def test_selection_uses_native_script_and_does_not_rewrite_dialogue_choices(self):
        self.assertIn("@gosub Opening3.heroScene", self.menu)
        choices = {r[0] for r in self.scripts["Opening3"] if r[3].lstrip().startswith("@choice ")}
        self.assertFalse(choices.intersection(self.edits.get("Opening3", {})))

    def test_keeps_original_attack_and_event_through_last_line(self):
        self.assertIn("@goto Battle.PlayerAttack", self.menu)
        self.assertNotIn("@set autoPlay=true", self.menu)
        rows = self.scripts["Battle"]
        event = next(r[0] for r in rows if r[3].strip() == "@set xSwitchTutorialSlimeBattleBreakEvent=1")
        self.assertFalse(set(range(event-19, event+1)).intersection(self.edits["Battle"]))

    def test_automatic_boss_selection_preserves_the_original_target_logic_for_other_scenes(self):
        scene = dict(id='multi', group='Mage', chapter=5, title='合流测试', status='script-reviewed',
                     source='Battle', label='Start', setupCommands=[], exits=['Battle.InitializeCommand'],
                     actionAtFirstCommand={'target':'Battle.PlayerAttack', 'selectBoss':True,
                                           'commands':['@set selectCommand=-1;selectionEnemyTargetId=GetEnemyStr(xPriestFinalSlot)']})
        edits = make_program(self.scripts, [scene, dict(scene, id='multi2')], [])
        row = next(r[0] for r in self.scripts['Battle'] if r[3].strip() ==
                   '@set tempActionTargetArr=GetActionTargetArrayStrBySlotNumber(selectCommand)')
        self.assertEqual(edits['Battle'][row-1], ('Battle',row))
        self.assertIn('v15Scene==301||v15Scene==401', edits['Battle'][row])
        self.assertIn('v15ActionIssued==1&&selectCommand==-1', edits['Battle'][row])
        self.assertNotIn(row, self.edits['Battle'])

    def test_remembers_selected_item_and_page(self):
        self.assertTrue(any(isinstance(s,str) and s.startswith("@set G_v15Last=") for s in self.menu))
        self.assertTrue(any(isinstance(s,str) and "◆" in s and "if:G_v15Last==" in s for s in self.menu))
        self.assertIn("@title", self.menu)

    def test_roulette_plays_native_spin_after_the_players_choice(self):
        for name in ("Dungeon", "Scenario_Warrior4"):
            rows = self.scripts[name]
            changes = self.edits[name]
            for caption, destination in (("START!", ".RouletteStartGoto"), ("STOP!", ".RouletteStop")):
                source = next(r for r in rows if r[3].strip().startswith(f'@choice " {caption}"'))
                self.assertTrue(changes[source[0]].startswith("@goto .V15"))
                self.assertIn("@goto " + destination, changes.values())
            for idx, _, _, raw, *_ in rows:
                if raw.strip() in ('@roulette "start"', '@roulette "stop"') or 'goto:.createRouletteGoto' in raw:
                    self.assertNotIn(idx, changes)

    def test_first_choice_and_switch_return_to_the_same_catalog_page(self):
        resume = self.menu.index("# Resume")
        restore = next(i for i, cmd in enumerate(self.menu) if isinstance(cmd, str) and " if:G_v15Last==" in cmd)
        self.assertIn("@gosub .ChooseLead if:G_v15Lead!=1&&G_v15Lead!=2", self.menu[resume:restore])
        self.assertIn('@choice "使用女主角" goto:.ChooseFemale', self.menu)
        self.assertIn('@choice "使用男主角" goto:.ChooseMale', self.menu)
        for label, lead in (("ChooseFemale", 1), ("ChooseMale", 2)):
            i = self.menu.index("# " + label)
            self.assertEqual(self.menu[i+1], f"@set G_v15Lead={lead}")
        for page in ("Home", "PShared0x0"):
            self.assertIn(f'@choice "切换主角（当前为女主角）" goto:.Change{page} if:G_v15Lead==1', self.menu)
            i = self.menu.index("# Change" + page)
            self.assertEqual(self.menu[i+1:i+3], ["@gosub .ChooseLead", "@goto ." + page])

    def test_each_scene_applies_gender_before_setup_and_leaves_opening_choices_intact(self):
        starts = [i for i, cmd in enumerate(self.menu) if cmd == "@gosub First.InitialSettings"]
        self.assertTrue(starts)
        for idx in starts:
            self.assertIn("@gosub .ApplyLead", self.menu[idx+1:idx+4])
        self.assertIn("@set playerType=G_v15Lead;playerLooksType=G_v15Lead", self.menu)
        for lead, subject, obj in ((1, "She", "Her"), (2, "He", "Him")):
            self.assertIn(f'@set SoldierEnHe="{subject}" if:G_v15Lead=={lead}&&xSwitchSoldierEnHeInputted!=1', self.menu)
            self.assertIn(f'@set SoldierEnHim="{obj}" if:G_v15Lead=={lead}&&xSwitchSoldierEnHimInputted!=1', self.menu)
        for idx, _, _, text, *_ in self.scripts["Opening"]:
            if "goto:Opening.MeChoice" in text or text.strip() in ("@set playerType=1", "@set playerType=2"):
                self.assertNotIn(idx, self.edits["Opening"])

    def test_artwork_with_two_variants_follows_the_saved_protagonist(self):
        gallery = json.loads(Path(os.environ["V14_GALLERY"]).read_bytes())
        art = next(s for s in gallery["scenes"] if s["id"] == "Extras-74")
        rows = list(make_program(self.scripts, [], [art], gallery["assets"])["Test2"].values())
        first = rows.index("@goto .A3v1 if:G_v15Lead==2")
        self.assertEqual(rows[first+1], "# A3v0")
        start_male = rows.index("# A3v1")
        self.assertTrue(any('CG/cutinMe1' in str(s) for s in rows[first:start_male]))
        self.assertTrue(any('CG/cutinMe2' in str(s) for s in rows[start_male:]))

    def test_no_platform_achievement_calls_remain(self):
        for script, rows in self.scripts.items():
            for index, _, _, line, *_ in rows:
                if line.strip().lower().startswith("@steamachievement "):
                    self.assertEqual(self.edits[script][index], ";")

    def test_private_scene_starts_with_999_spendable_currency(self):
        rows = self.scripts["First"]
        slot = next(r[0] for r in rows if r[3].strip() == "@set curse=0")
        self.assertEqual(self.edits["First"].get(slot, rows[slot][3].strip()), "@set curse=999")
        self.assertGreaterEqual(self.menu.count("@gosub First.InitialSettings"), 3)

    def test_success_and_failure_can_both_reach_the_paid_wheel_controls(self):
        rows = self.scripts["Dungeon"]
        changes = self.edits["Dungeon"]
        original_autosettle = next(r[0] for r in rows if r[3].strip() ==
                                   '@if curse<rotateNeedCurse||rouletteResult=="success"')
        self.assertEqual(changes.get(original_autosettle - 1),
                         "@goto .RouletteEnd if:curse>=rotateNeedCurse")
        for row in rows:
            line = row[3].strip()
            if line.startswith(("@roulette \"rotate\"", "@gosub Func.ReduceCurse",
                                "@gosub Func.AddCurse", '@choice "受け入れる"')):
                self.assertNotIn(row[0], changes)
