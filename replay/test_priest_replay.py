import json
import os
from collections import defaultdict
from pathlib import Path
import unittest

try:
    from . import priest_replay, scenes
except ImportError:
    import priest_replay
    import scenes


@unittest.skipUnless(os.environ.get('V15_SCRIPTS') and os.environ.get('V14_GALLERY'),
                     'requires the original extracted scripts and gallery')
class PriestRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = json.loads(Path(os.environ['V15_SCRIPTS']).read_text('utf-8'))
        from source_anchors import resolve_gallery
        gallery = json.loads(Path(os.environ['V14_GALLERY']).read_text('utf-8'))
        cls.gallery, _ = resolve_gallery(cls.scripts, gallery)
        cls.flow = scenes.ScriptMap(cls.scripts)
        cls.entries = []
        priest_replay.integrate(cls.entries, cls.flow, cls.gallery)
        cls.by_label = {entry['label']: entry for entry in cls.entries}

    def test_second_floor_opposite_decisions_have_distinct_aftermaths(self):
        abandoned = self.by_label['MageHeroBattleAfter']
        self.assertIn('@set xSwitchPriestNakamaMisuteru=1', abandoned['setupCommands'])
        self.assertIn('@set backgroundName="cave_moss"', abandoned['setupCommands'])
        self.assertTrue(abandoned['naturalReturn'])
        kept = self.by_label['VillainessBattleAfter']
        self.assertEqual(kept['presets'][0]['choices'], 3)
        self.assertTrue(kept['naturalReturn'])
        self.assertNotEqual(abandoned['id'], kept['id'])

    def test_fourth_floor_bad_ending_returns_to_third_floor_and_next_fight(self):
        options = self.by_label['SlimeBattleAfter']['presets']
        low = next(p for p in options if '@set xSwitchChoicePriestLook=1' in p['setupCommands'])
        self.assertIn('Ending-223', low['galleryIds'])
        self.assertNotIn('Ending-111', low['galleryIds'])
        self.assertGreaterEqual(low['choices'], 3)
        self.assertEqual(low['exits'], ['Battle.InitializeCommand'])
        self.assertFalse(low['naturalTitle'])
        high = next(p for p in options if '@set xSwitchChoicePriestRefuseHand=1' in p['setupCommands'])
        self.assertEqual(high['exits'], ['Battle.InitializeCommand'])
        self.assertNotIn('Ending-223', high['galleryIds'])

    def test_fourth_floor_rescue_keeps_real_choice_and_repeat_restriction(self):
        first, repeat = self.by_label['defaultSlimeBattleAfter']['presets']
        self.assertEqual(first['choices'], 2)
        self.assertTrue(first['naturalReturn'])
        self.assertTrue(first['naturalTitle'])
        self.assertIn('Ending-234', first['galleryIds'])
        self.assertNotIn('Ending-234', repeat['galleryIds'])
        self.assertFalse(repeat['naturalTitle'])
        self.assertIn('@set partnerHealth=1', first['setupCommands'])

    def test_high_loop_finale_contains_final_strike_three_farewells_and_full_epilogue(self):
        scene = self.by_label['PriestBattleAfterHighLoop']
        self.assertEqual(scene['presets'][0]['choices'], 3)
        self.assertTrue(scene['naturalTitle'])
        self.assertIn('Ending-250', scene['galleryIds'])
        self.assertNotIn('Ending-242', scene['galleryIds'])
        self.assertIn('@gosub Scenario_Priest5.PriestBattlePostBattleFinisher', scene['setupCommands'])
        labels = self.flow.sources['Scenario_Priest5'].labels
        expected = [r['id'] for r in self.gallery if r['source'] == 'Scenario_Priest5' and
                    labels['PriestBattlePostBattleFinisher'] <= r['line'] < labels['ChoicePriestNod']]
        self.assertTrue(set(expected).issubset(scene['galleryIds']))
        self.assertFalse(any(p['issues'] for scene in self.entries for p in scene['presets']))

    def test_single_action_controls_and_private_demon_phase_bootstrap(self):
        edits = defaultdict(dict)
        priest_replay.patch_program(edits, self.scripts)
        source = self.flow.sources['Scenario_Priest5']
        for i in range(source.labels['PriestBattleAfterHighLoop'], source.labels['ChoicePriestNod']):
            self.assertNotIn(i, edits['Scenario_Priest5'])
        patched_lines = {k: [v for v in rows.values() if isinstance(v, str)] for k, rows in edits.items()}
        self.assertTrue(any('PriestHeartBladeSelected' in v for v in patched_lines['Scenario_Priest5']))
        self.assertTrue(any('PriestFinalPriestRouteDefaultSelected' in v for v in patched_lines['Battle']))
        from script_assets import TEMPLATES
        for lines in patched_lines.values():
            for line in lines:
                self.assertTrue(line.startswith('# ') or line[1:].split()[0] in TEMPLATES, line)
        original = self.flow.sources['Battle'].text
        for idx in edits['Battle']:
            if idx < len(original):
                self.assertTrue(original[idx].split()[0] in ('@stop', '@summonAttackBar') or
                                original[idx] == '@set xGlausFinalPhase=1', original[idx])
        for phase in (2, 3):
            self.assertIn(f'@set xGlausFinalPhase={phase} if:v15Scene>0&&addEnemyResourceNames=="demonLordForm{phase}"',
                          patched_lines['Battle'])

    def test_setup_compiles_using_existing_donors_or_host_commands(self):
        donors = {row[3].strip() for rows in self.scripts.values() for row in rows if row[1] == 'Command'}
        for entry in self.entries:
            for preset in entry['presets']:
                for cmd in preset['setupCommands']:
                    self.assertTrue(cmd in donors or cmd.startswith(('@gosub ', '@set ')), cmd)
        before = [s['id'] for s in self.entries]
        priest_replay.integrate(self.entries, self.flow, self.gallery)
        self.assertEqual([s['id'] for s in self.entries], before)
        self.assertEqual(len(before), len(set(before)))

    def test_fourth_form_is_triggered_in_initialized_combat(self):
        entry = next(s for s in self.entries if s['id'] == 'Battle.Action.PriestFourthForm')
        self.assertEqual(entry['source'], 'Battle')
        self.assertEqual(entry['label'], 'Start')
        self.assertIn('@set xSwitchSystemDebugPriestPhase=3', entry['setupCommands'])
        self.assertIn('@set G_gameLoopCount=9', entry['setupCommands'])
        self.assertEqual(entry['presets'][0]['actionAtFirstCommand']['target'], 'Battle.PlayerAttack')
        self.assertEqual(entry['presets'][0]['exits'], ['Battle.InitializeCommand'])
        self.assertIn('Scenario_Priest5-664', entry['galleryIds'])
        broken = entry['presets'][1]
        self.assertIn('@set xSwitchSystemDebugPriestPhase=4', broken['setupCommands'])
        self.assertIn('Battle.PriestFinalBuildDestroyModeHand', broken['exits'])
        self.assertTrue(broken['actionAtFirstCommand']['selectBoss'])

    def test_fourth_floor_history_recollection_has_real_prior_save_flags(self):
        history = self.by_label['ToDungeon4']['presets'][-1]
        for flag in ('G_gameOverPriestPartnerCount', 'G_gameClearHeroCount', 'G_gameKilledByPriestCount'):
            self.assertIn('@set '+flag+'=1', history['setupCommands'])
        self.assertNotIn('Scenario_Priest4-381', history['galleryIds'])

    def test_dropouts_second_form_is_triggered_by_the_players_attack(self):
        scene = next(s for s in self.entries if s['id'] == 'Battle.Action.PriestDropout')
        for p in scene['presets']:
            self.assertIn('@set addEnemyResourceNames="dropout"', p['setupCommands'])
            self.assertEqual(p['actionAtFirstCommand']['target'], 'Battle.PlayerAttack')
        self.assertIn('@gosub .DropoutTransformCommonBody', [row['text'] for row in scene['evidenceRows']])

    def test_final_battle_uses_native_death_classifier_and_original_repeat_count(self):
        entries = {s['id']: s for s in self.entries}
        fail = entries['Battle.Action.PriestCurseShortage']['presets']
        self.assertEqual(len(fail), 6)
        for count, p in enumerate(fail):
            cmds = p['actionAtFirstCommand']['commands']
            self.assertIn('@set xPriestFinalPriestRouteGameOverCount='+str(count), cmds)
            self.assertIn('@gosub Battle.DeathCheckOnPlayer', cmds)
            self.assertIn('GameOver.Choice', p['exits'])
        counters = entries['Battle.Action.PriestCounter']['presets']
        self.assertIn('@set enemy{xPriestFinalSlot}StateBlock=0', counters[0]['actionAtFirstCommand']['commands'])
        self.assertIn('@set curse=10', counters[1]['actionAtFirstCommand']['commands'])

    def test_demon_lord_counters_follow_opening_with_three_original_combat_boundaries(self):
        ids = [s['id'] for s in self.entries]
        first = ids.index('Scenario_Priest5.DemonLordBattleBefore')+1
        for phase, (cut, appearance) in enumerate((
                ('Battle-13117', 'outcastAllyCutLight'), ('Battle-13178', 'dropoutAllyCutLight'),
                ('Battle-13230', 'villainessAllyCutLight')), 1):
            scene = self.entries[first+phase-1]
            self.assertEqual(scene['id'], f'Battle.Action.PriestGlausForm{phase}')
            self.assertEqual(scene['galleryIds'], [cut])
            row = next(r for r in self.gallery if r['id'] == cut)
            self.assertIn('"CG/'+appearance+'"', self.flow.sources['Battle'].text[row['line']])
            self.assertEqual(row['label'], f'GlausFinalForm{phase}CounterText')
            self.assertEqual(scene['label'], 'Start')
            self.assertIn(f'@set addEnemyResourceNames="demonLordForm{phase}"', scene['setupCommands'])
            self.assertIn('@gosub Battle.GlausFinalSetupTemporaryPartner', scene['setupCommands'])
            action = scene['actionAtFirstCommand']
            self.assertEqual(action['target'], 'Battle.PlayerAttack')
            self.assertIn('@set selectionEnemyTargetId=GetEnemyStr(xGlausFinalSlot)', action['commands'])
            self.assertFalse(any('CounterText' in c for c in scene['setupCommands']+action['commands']))
            self.assertEqual(scene['exits'], ['Battle.InitializeCommand'])
