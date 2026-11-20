import json
import os
from pathlib import Path
import unittest

from scenes import ScriptMap
import warrior_replay as warrior


@unittest.skipUnless(os.environ.get('V15_SCRIPTS') and os.environ.get('V14_GALLERY'),
                     'set V15_SCRIPTS and V14_GALLERY for the original scripts')
class WarriorScenesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = json.loads(Path(os.environ['V15_SCRIPTS']).read_text('utf-8'))
        cls.gallery = json.loads(Path(os.environ['V14_GALLERY']).read_text('utf-8'))['scenes']
        cls.flow = ScriptMap(cls.scripts)
        rows = []
        warrior.integrate(rows, cls.flow, cls.gallery)
        cls.ids = {r['id']: r for r in rows}
        cls.entries = {r['label']: r for r in rows}

    def test_court_preserves_both_native_decisions_and_head_outcomes(self):
        entry = self.entries['VillainessBattleAfter']
        self.assertTrue(entry['naturalReturn'])
        for letter in 'ABCDE':
            self.assertTrue(any('@set xSwitchChoiceOutcastFinal'+letter+'=1' in p['setupCommands']
                                for p in entry['presets']))
        self.assertTrue(any('@set xSwitchWarriorAtamaBreak=1' in p['setupCommands'] for p in entry['presets']))
        self.assertTrue(all(p['choices'] >= 3 for p in entry['presets']))

    def test_final_accepts_native_ending_and_resumes_the_confrontation(self):
        entry = self.entries['WarriorBattleBefore']
        self.assertIn('Ending-215', entry['galleryIds'])
        self.assertFalse(entry['naturalTitle'])
        self.assertEqual(entry['exits'], ['Battle.InitializeCommand'])
        self.assertTrue(all(p['choices'] >= 3 for p in entry['presets']))
        self.assertTrue(all('@gosub Func.ClearPartnerCharacter' in p['setupCommands'] for p in entry['presets']))

    def test_post_battle_game_over_and_level_one_are_one_entry(self):
        entry = self.entries['WarriorBattleAfter']
        self.assertEqual(entry['exits'], ['Battle.InitializeCommand'])
        self.assertEqual(entry['status'], 'script-reviewed')
        self.assertIn('@goto Scenario_Warrior5.GameOverBackPoint', [r['text'] for r in entry['evidenceRows']])
        self.assertNotIn('GameOverBackPoint', self.entries)

    def test_stop_battle_uses_the_original_card_and_resolves_both_cutscenes(self):
        entry = self.ids['Battle.Action.WarriorStopBattle']
        self.assertEqual(entry['id'], 'Battle.Action.WarriorStopBattle')
        self.assertEqual(entry['galleryIds'], ['Battle-10089', 'Battle-10107'])
        action = entry['actionAtFirstCommand']
        self.assertIn('@set selectCommand=-141', action['commands'])
        self.assertEqual(action['target'], 'Battle.PlayerAttack')
        self.assertIn('Scenario_Warrior5.WarriorBattleAfter', entry['exits'])
        self.assertFalse(any('WarriorFinalStopBattleText' in t for t in action['commands']))

    def test_surviving_capital_epilogue_requires_the_actual_reversal(self):
        entry = self.entries['WarriorLv1DuelAfter']
        hits = [p for p in entry['presets'] if 'Scenario_Warrior5-1807' in p['galleryIds']]
        self.assertEqual(len(hits), 1)
        self.assertIn('@set xSwitchChoiceWarriorBattleAfterKutsugaesuS=1', hits[0]['setupCommands'])
        self.assertIn('@set xSwitchChoiceOutcastFinalB=0', hits[0]['setupCommands'])
        self.assertIn('@set xSwitchWarriorGlitchEnd=0', hits[0]['setupCommands'])
        self.assertTrue(entry['naturalTitle'])

    def test_illusion_rescues_use_native_enemy_action_and_selected_ally(self):
        for number, attack in [(1, 'warriorIllusionAGrandAttack'), (2, 'warriorHydraPoisonBlast'),
                               (3, 'warriorIllusionCGrandAttack')]:
            scene = self.entries['Last'+str(number)]
            self.assertEqual(len(scene['presets']), 2)
            for p in scene['presets']:
                action = p['actionAtFirstCommand']
                self.assertIn(f'@storeEnemyNextActionSet enemyId:{{v15WarriorEnemy}} actionSetName:"{attack}"', action['commands'])
                self.assertEqual(action['target'], 'Battle.EnemiesActionLoop')
            if number == 2:
                self.assertIn('Battle-9634', scene['presets'][0]['galleryIds'])
                self.assertNotIn('Battle-9634', scene['presets'][1]['galleryIds'])

    def test_scripted_hydra_death_head_throw_and_both_hands_use_native_handlers(self):
        hydra = self.ids['Battle.Action.WarriorHydraAfter']
        self.assertEqual(hydra['galleryIds'], ['Battle-9726', 'Battle-9771', 'Battle-9860'])
        self.assertIn('@set selectionEnemyTargetId=GetEnemyStr(yValWarriorHydraEnemyId)',
                      hydra['actionAtFirstCommand']['commands'])
        head = self.ids['Battle.Action.WarriorHead']
        self.assertEqual(head['galleryIds'], ['Battle-14739', 'Battle-14769'])
        self.assertIn('@set selectCommand=itemAddedIndex', head['actionAtFirstCommand']['commands'])
        arms = self.ids['Battle.Action.WarriorArms']
        self.assertEqual(arms['galleryIds'], ['Battle-11893'])
        self.assertEqual(len(arms['presets']), 3)
        self.assertTrue(all('@set yValSlimeWarriorReviveCount=3' in p['actionAtFirstCommand']['commands']
                            for p in arms['presets']))

    def test_fourth_floor_includes_both_sides_of_gameplay(self):
        self.assertEqual(self.entries['Slime2']['exits'], ['Battle.InitializeCommand'])
        aftermath = self.entries['V15SlimeServantsAfter']
        self.assertTrue(aftermath['naturalReturn'])
        self.assertTrue(any(i.startswith('Scenario_Warrior4-') for i in aftermath['galleryIds']))
        edits = {}
        warrior.patch_program(edits, self.scripts)
        index, label = next(iter(edits['Scenario_Warrior4'].items()))
        self.assertEqual(label, '# V15SlimeServantsAfter')
        self.assertIn(self.scripts['Scenario_Warrior4'][index][1], ('Empty', 'Comment'))
        self.assertLess(index, self.flow.sources['Scenario_Warrior4'].labels['KakuseiCutTest'])

    def test_parted_companions_and_aftermaths(self):
        for name in ('DealerBattleAfter', 'GiantBattleAfter', 'Last1BattleAfter', 'Last2BattleAfter'):
            self.assertTrue(self.entries[name]['naturalReturn'])
        for label, partner in [('Last1BattleAfter', 'mage'), ('Last2BattleAfter', 'hero'),
                               ('Last3BattleAfter', 'priest')]:
            entry = self.entries[label]
            self.assertEqual(len(entry['presets']), 2)
            for p in entry['presets']:
                self.assertIn(f'@set switchPartnerCharacter="{partner}"', p['setupCommands'])

    def test_integrating_twice_does_not_duplicate_scene_ids(self):
        items = [dict(id='unrelated')]
        warrior.integrate(items, self.flow, self.gallery)
        warrior.integrate(items, self.flow, self.gallery)
        self.assertEqual(len(items), len({s['id'] for s in items}))


if __name__ == '__main__':
    unittest.main()
