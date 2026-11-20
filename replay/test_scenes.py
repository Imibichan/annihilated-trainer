import json
import os
from pathlib import Path
import unittest

try:
    from . import scenes
except ImportError:
    import scenes


def rows(*lines):
    return [
        [i, 'Label' if t.startswith('#') else 'Command', 'ignored', t, 0]
        for i, t in enumerate(lines)
    ]


class FlowTests(unittest.TestCase):
    def test_progress_reset_only_targets_original_story_variables(self):
        source = {'Ending': rows(
            '@set G_xSwitchEndingSeen_hero=1 if:endingType=="hero"',
            '@set G_titleEndingBackground=titleEndingBackground',
            '@set G_titleEndingGlitch=yValTitleEndingGlitch',
            '@set G_xSwitchIsDebugStart=1 if:isDebugMode==true',
            '@set G_MenuChoice=4', '@set G_WindowSettings=1',
        )}
        result = scenes.story_reset_commands(source)
        self.assertIn('@set G_gameLoopCount=0', result)
        self.assertIn('@set G_titleEndingBackground=""', result)
        self.assertIn('@set G_xSwitchEndingSeen_hero=0', result)
        self.assertFalse(any(any(s in cmd for s in ('Debug', 'MenuChoice', 'Settings')) for cmd in result))

    def test_follows_choices_subroutines_and_returns_until_play_resumes(self):
        source = {'Scenario_Mage2': rows(
            '# Start', '@choice A goto:.Left', '@choice B goto:.Right', '@stop',
            '# Left', '@gosub .Shared', '@goto .Done', '# Right', '@gosub .Shared',
            '# Done', '@goto Dungeon.ExploreStart', '# Unrelated', '@stop',
            '# Shared', '@return',
        )}
        route = scenes.ScriptMap(source).trace('Scenario_Mage2', 'Start')
        self.assertEqual(route['exits'], ['Dungeon.ExploreStart'])
        self.assertEqual(route['issues'], [])
        self.assertEqual(route['choices'], 2)
        self.assertTrue({4, 7, 13}.issubset(route['visited']['Scenario_Mage2']))
        self.assertNotIn(11, route['visited']['Scenario_Mage2'])

    def test_conditional_transfers_respect_chosen_route(self):
        source = {'Scenario_Mage4': rows(
            '# Start', '@if xSwitchMageChoiceNotMaryoku==1',
            '@gosub .Other', '@else', '@gosub .Here', '@endif', '@return',
            '# Other', '@goto Battle', '# Here', '@return',
        )}
        route = scenes.ScriptMap(source).trace('Scenario_Mage4', 'Start',
                                               {'xSwitchMageChoiceNotMaryoku': 0})
        self.assertEqual(route['exits'], [])
        self.assertEqual(route['issues'], [])
        self.assertTrue(route['returns'])
        self.assertNotIn(7, route['visited']['Scenario_Mage4'])

    def test_unknown_transfer_and_battle_are_never_silently_accepted(self):
        source = {'Scenario_Hero2': rows(
            '# Start', '@goto .Missing if:xFlag==1', '@gosub Battle', '@return',
        )}
        route = scenes.ScriptMap(source).trace('Scenario_Hero2', 'Start')
        self.assertTrue(route['issues'])
        self.assertTrue(route['battle'])
        self.assertFalse(route['returns'])

    def test_scene_exit_intercept_before_dispatcher(self):
        source = {'Opening3': rows(
            '# heroScene', '@goto .hanasiChoice', '# hanasiChoice', '@goto .heroScene',
        )}
        route = scenes.ScriptMap(source).trace('Opening3', 'heroScene',
                                               boundaries=('Opening3.hanasiChoice',))
        self.assertEqual(route['exits'], ['Opening3.hanasiChoice'])
        self.assertNotIn(2, route['visited']['Opening3'])


@unittest.skipUnless(os.environ.get('V15_SCRIPTS') and os.environ.get('V14_GALLERY'),
                     'set V15_SCRIPTS and V14_GALLERY to verify the actual game data')
class OriginalDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scripts = json.loads(Path(os.environ['V15_SCRIPTS']).read_text('utf-8'))
        cls.gallery = json.loads(Path(os.environ['V14_GALLERY']).read_text('utf-8'))
        cls.catalog = scenes.build_catalog(scripts, cls.gallery)

    def test_original_art_frame_variants_survive_in_order(self):
        expected = [s for s in self.gallery['scenes'] if s['source'] == 'Extras']
        self.assertEqual(len(expected), 15)
        self.assertEqual(self.catalog['artworks'], expected)
        self.assertIn('layers2', expected[0]['frames'][0])

    def test_scenes_cover_choices_without_duplicating_branches_as_rooms(self):
        routes = {s['id']: s for s in self.catalog['scenes']}
        mage = routes['Scenario_Mage2.ToDungeon2']
        self.assertEqual(mage['status'], 'script-reviewed')
        self.assertEqual(len(mage['galleryIds']), 8)
        self.assertIn('Dungeon.ExploreStart', mage['exits'])
        self.assertNotIn('Scenario_Mage2.HoldHands', routes)
        hero = routes['Opening3.heroScene']
        self.assertEqual(hero['exits'], ['Opening3.hanasiChoice'])
        self.assertEqual(hero['status'], 'script-reviewed')
        self.assertNotIn('Opening.TutorialSlimeBattleBefore', routes)

    def test_every_stock_id_has_an_explicit_coverage_outcome(self):
        reported = self.catalog['coverage']['byGalleryId']
        self.assertEqual(set(reported), {s['id'] for s in self.gallery['scenes']})
        self.assertEqual(len(reported), 364)
        pending = self.catalog['coverage']['pendingBySource']
        self.assertEqual(sum(pending.values()), sum(v == 'pending' for v in reported.values()))
        self.assertIn('Battle', pending)
        issues = self.catalog['coverage']['candidateIssues']
        self.assertNotIn('Scenario_Warrior5.WarriorBattleBefore', issues)
        self.assertTrue(any(s['id'] == 'Scenario_Warrior5.WarriorBattleBefore'
                            and s['status'] == 'script-reviewed' for s in self.catalog['scenes']))
        self.assertFalse(any(s['status'] == 'live-verified' for s in self.catalog['scenes']))

    def test_villainess_requires_the_native_attack_and_collects_both_cuts(self):
        routes = {s['id']: s for s in self.catalog['scenes']}
        route = routes['Battle.Action.VillainessSecondForm']
        self.assertEqual((route['source'], route['label']), ('Battle', 'Start'))
        self.assertEqual(route['galleryIds'], ['Battle-9082', 'Battle-9125'])
        self.assertEqual(route['exits'], ['Battle.InitializeCommand'])
        action = route['actionAtFirstCommand']
        self.assertEqual(action['target'], 'Battle.PlayerAttack')
        self.assertIn('@set selectCommand=-1', action['commands'])
        self.assertFalse(any('SecondFormTransitionCore' in cmd for cmd in action['commands']))
        self.assertIn('@set enemy1Health=1', action['commands'])
        self.assertTrue(action['skipTiming'])
        self.assertGreaterEqual(len(route['evidenceRows']), 6)

    def test_mage_support_cuts_match_the_companion_that_the_native_phase_calls(self):
        routes = {s['id']: s for s in self.catalog['scenes']}
        for phase, expected in ((2, ['Battle-12455', 'Battle-12644']),
                                (3, ['Battle-12465', 'Battle-12742'])):
            route = routes[f'Battle.Action.MagePriestPhase{phase}']
            self.assertEqual(route['galleryIds'], expected)
            self.assertIn(f'@set xSwitchSystemDebugPriestPhase={phase}', route['setupCommands'])
            self.assertIn('@gosub Battle.PriestFinalAfterFormStartSetupText', route['actionAtFirstCommand']['commands'])
        self.assertNotIn('Battle.Action.MagePriestPhase1', routes)

    def test_mage_reinforcements_play_together_before_the_separate_battle_scenes(self):
        active = [s for s in self.catalog['scenes'] if s['group'] == 'Mage' and s['chapter'] == 5
                  and s['status'] == 'script-reviewed']
        ids = [s['id'] for s in active]
        rescue = 'Scenario_Mage5.WakimitiRoute_AfterBattle2'
        self.assertIn(rescue, ids)
        self.assertEqual(ids[ids.index(rescue):ids.index(rescue)+3],
                         [rescue, 'Battle.Action.MagePriestPhase2', 'Battle.Action.MagePriestPhase3'])
        scene = active[ids.index(rescue)]
        rescue_cg = next(s['id'] for s in self.gallery['scenes'] if s['source'] == 'Battle' and
                         s['label'] == 'PriestFinalMageNotMaryokuForm1CounterText')
        self.assertEqual(scene['galleryIds'], ['Scenario_Mage5-2101', 'Scenario_Mage5-2300', 'Battle-12443', rescue_cg])
        self.assertIn('Battle.PriestFinalResummonEnemy', scene['exits'])
        action = scene['presets'][0]['actionAtFirstCommand']
        self.assertEqual(action['target'], 'Battle.PlayerAttack')
        self.assertTrue(action['selectBoss'])
        self.assertIn('@gosub Battle.PriestFinalAfterFormStartSetupText', action['commands'])
        self.assertEqual(len(scene['presets']), 1)
        self.assertEqual(scene['presets'][0]['choices'], 6)
        self.assertIn('@set xSwitchMageChoiceNotMaryoku=1', scene['setupCommands'])
        self.assertIn('@set dungeonId=9', scene['setupCommands'])

    def test_mage_final_routes_and_broken_promise_are_playable(self):
        active = {s['id']:s for s in self.catalog['scenes'] if s['status'] == 'script-reviewed'}
        before = active['Scenario_Mage5.PriestBattleBefore']
        self.assertEqual(len(before['presets']), 2)
        for label in ('NotWakimitiRoute','WakimitiRoute','WakimitiRoute_AfterBattle1'):
            self.assertIn('Battle.InitializeCommand', active['Scenario_Mage5.'+label]['exits'])
        ending = active['Battle.Action.MageBrokenPromise']
        self.assertIn('Scenario_Mage5-1147', ending['galleryIds'])
        self.assertIn('Scenario_Mage5-1224', ending['galleryIds'])
        self.assertIn('@goto Scenario_Mage5.PriestBattleBadRouteBattleFinaleEnd', ending['presets'][0]['finishCommands'])

    def test_mage_steps_in_front_of_the_original_charged_attack(self):
        scene = next((s for s in self.catalog['scenes'] if s['id']=='Battle.Action.DropoutMageCharge'), None)
        self.assertIsNotNone(scene)
        self.assertEqual(scene['galleryIds'], ['Battle-10712', 'Battle-10771'])
        self.assertEqual(len(scene['presets']), 2)
        for p in scene['presets']:
            self.assertIn('@storeEnemyNextActionSet enemyId:1 actionSetName:"dropoutGrandAttackVsMage"',
                          p['actionAtFirstCommand']['commands'])
            self.assertIn('@gosub Battle.DropoutMageChargeModeBranch', p['actionAtFirstCommand']['commands'])

    def test_mage_dropout_second_form_and_return(self):
        active = {s['id']: s for s in self.catalog['scenes']}
        scene = active['Battle.Action.MageDropoutSecondForm']
        self.assertEqual(len(scene['presets']), 2)
        strike, steal = [p['actionAtFirstCommand'] for p in scene['presets']]
        self.assertEqual(strike['target'], 'Battle.PlayerAttack')
        self.assertIn('@gosub Action.StealEnemyWeaponFromCurrentTarget', steal['commands'])
        self.assertIn('@set xSwitchReturnSteal=1', steal['commands'])
        rescue = active['Battle.Action.MageDropoutReturn']
        self.assertIn('@gosub Battle.DropoutSurvive4TurnsBranch', rescue['actionAtFirstCommand']['commands'])
        self.assertLess(list(active).index(scene['id']),list(active).index(rescue['id']))
        self.assertLess(list(active).index(rescue['id']),list(active).index('Scenario_Mage3.DropoutBattleAfter'))

    def test_villainess_regeneration_keeps_the_four_witnesses_in_one_entry(self):
        scene = next(s for s in self.catalog['scenes'] if s['id']=='Battle.Action.VillainessRegeneration')
        self.assertEqual(scene['group'], 'Shared')
        self.assertEqual(len(scene['presets']), 4)
        self.assertEqual(set(scene['galleryIds']), {'Battle-4237','Battle-4255','Battle-4260','Battle-4269'})
        for variant in scene['presets']:
            self.assertIn('@gosub Battle.TurnEndEffectsLoop', variant['actionAtFirstCommand']['commands'])
            self.assertIn('Battle-4237', variant['galleryIds'])


if __name__ == '__main__':
    unittest.main()
