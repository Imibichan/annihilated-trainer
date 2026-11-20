import json
import os
from pathlib import Path
import unittest

import hero_replay
from scenes import ScriptMap, build_catalog


@unittest.skipUnless(os.getenv('V15_SCRIPTS') and os.getenv('V14_GALLERY'), 'requires the original game data')
class HeroReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = json.loads(Path(os.environ['V15_SCRIPTS']).read_bytes())
        cls.gallery = json.loads(Path(os.environ['V14_GALLERY']).read_bytes())
        cls.flow = ScriptMap(cls.scripts)
        cls.rows = build_catalog(cls.scripts, cls.gallery)['scenes']
        hero_replay.integrate(cls.rows, cls.flow, cls.gallery['scenes'])
        cls.menu = {s['id']: s for s in cls.rows if s['status'] == 'script-reviewed'}

    def test_arrow_trap_keeps_the_native_choice_and_the_returning_character_dialogue(self):
        scene = self.menu['Scenario_Hero1.Outcast1']
        self.assertTrue(scene['naturalReturn'])
        self.assertFalse(scene['exits'])
        self.assertEqual(scene['presets'][0]['choices'], 1)
        self.assertFalse(any('rouletteOnlyResult=' in cmd for cmd in scene['setupCommands']))
        self.assertEqual(len(self.rows), len({s['id'] for s in self.rows}))

    def test_argument_before_final_battle_keeps_both_answers_and_stops_at_the_hand(self):
        scene = self.menu['Scenario_Hero5.PriestBattleBefore']
        self.assertEqual(scene['exits'], ['Battle.InitializeCommand'])
        self.assertEqual(scene['presets'][0]['choices'], 2)
        self.assertIn('Scenario_Hero5-1517', scene['galleryIds'])

    def test_last_blow_uses_two_presets_and_keeps_gameover_out_of_retry(self):
        scene = self.menu['Scenario_Hero5.PriestBattleAfter']
        win, miss, manual = scene['presets']
        self.assertEqual((scene['source'], scene['label']), ('Battle', 'Start'))
        for mode, p in enumerate((win, miss, manual), 1):
            self.assertIn(f'@set v15HeroFinisherMode={mode}', p['actionAtFirstCommand']['commands'])
            self.assertEqual(p['finishCommands'][-1], '@goto Scenario_Hero5.PriestBattleAfter')
        self.assertIn('Ending-120', win['galleryIds'])
        self.assertNotIn('Ending-120', miss['galleryIds'])
        self.assertIn('Scenario_Hero5-1727', miss['galleryIds'])
        self.assertIn('GameOver.GameOverBeforeCore', miss['exits'])
        self.assertEqual(set(manual['galleryIds']), set(win['galleryIds'] + miss['galleryIds']))
        self.assertTrue(win['naturalTitle'])

    def test_elite_aftermaths_keep_book_and_trust_conditions(self):
        book = self.menu['Scenario_Hero3.Dropout3_EliteAfter']
        self.assertTrue(book['naturalReturn'])
        self.assertEqual(len(book['presets']), 2)
        giant = self.menu['Scenario_Hero4.Slime3_EliteAfter']
        self.assertTrue(giant['naturalReturn'])
        self.assertIn('@set xSwitchHeroDropoutChoiceNotBelieve=0', giant['setupCommands'])

    def test_first_three_phase_counters_are_reached_by_hitting_the_boss(self):
        for phase in (1, 2, 3):
            scene = self.menu[f'Battle.Action.HeroPriestPhase{phase}']
            self.assertEqual(scene['exits'], ['Battle.InitializeCommand'])
            self.assertIn(f'@set xSwitchSystemDebugPriestPhase={phase}', scene['setupCommands'])
            action = scene['actionAtFirstCommand']
            self.assertTrue(action['selectBoss'])
            self.assertIn('@set selectionEnemyTargetId=GetEnemyStr(xPriestFinalSlot)', action['commands'])
            self.assertEqual(action['target'], 'Battle.PlayerAttack')
            self.assertNotIn('CounterText', '\n'.join(action['commands']))
            self.assertIn(f'@gosub .PriestFinalHeroForm{phase}CounterText', [r['text'] for r in scene['evidenceRows']])
            without, with_relic = scene['presets']
            relic = {1: 'doll', 2: 'destructionMagicSword', 3: 'magiaTakt'}[phase]
            self.assertNotIn('@set v15HeroRelicSlot=itemAddedIndex', without['setupCommands'])
            self.assertEqual(with_relic['setupCommands'][-3:], [
                f'@set addItem="{relic}"', '@gosub Func.AddItem', '@set v15HeroRelicSlot=itemAddedIndex'])
            used = with_relic['actionAtFirstCommand']
            self.assertEqual(used['commands'][0], '@set z=RecordBattleUsedItem(v15HeroRelicSlot)')
            self.assertEqual(used['commands'][1:], action['commands'])

    def test_fourth_phase_keeps_curse_award_and_charging_dialogue_before_next_card(self):
        scene = self.menu['Scenario_Hero5.PriestBattleAfter']
        self.assertNotIn('Battle.Action.HeroPriestPhase4', self.menu)
        self.assertIn('Battle.InitializeCommand', scene['exits'])
        self.assertEqual(scene['actionAtFirstCommand']['target'], 'Battle.PlayerAttack')
        self.assertNotIn('@gosub Battle.PriestFinalHeroFinisherIntro', scene['actionAtFirstCommand']['commands'])
        proof = [r['text'] for r in scene['evidenceRows']]
        self.assertIn('@set enemyStealItem="tumikasaCurse"', proof)
        self.assertIn('@set heroLinkLightningPhase=31', proof)
        for scene_id in ('Battle.Action.HeroPriestPhase3', 'GameOver.HeroFinalNeverGiveUp'):
            ids = [row['id'] for row in self.rows]
            self.assertLess(ids.index(scene_id), ids.index('Scenario_Hero5.PriestBattleAfter'))

    def test_final_cards_keep_native_preview_animation_and_limit_gauge_override_to_presets(self):
        from program import make_program
        changes = make_program(self.scripts, [self.menu['Scenario_Hero5.PriestBattleAfter']], [])
        if '# V15HeroCardStop' not in changes['Battle'].values():
            hero_replay.patch_program(changes, self.scripts)
        battle = changes['Battle']
        stock = self.flow.sources['Battle']
        label = stock.labels['PriestFinalHeroLinkLightningChoice']
        stop = stock.text.index('@stop', label)
        self.assertEqual(battle[stop], '@goto .V15HeroCardStop')
        for i in range(label, stop):
            self.assertNotIn(i, battle)
        charge = stock.labels['PriestFinalHeroFinisherGauge']
        gauge = next(i for i in range(charge, charge + 24) if stock.text[i].startswith('@summonAttackBar'))
        self.assertEqual(battle[gauge], '@gosub .V15HeroGaugeInput')
        self.assertIn(('Battle', gauge), battle.values())
        self.assertTrue(any(isinstance(s, str) and s.startswith('@goto .V15HeroGaugeReturn if:') and
                            'v15Scene==301' in s and 'v15HeroFinisherMode<=2' in s for s in battle.values()))
        for text in ('@gosub .HeroLinkLightningAnimationStart', '@goto .PriestFinalHeroFinisherMiss',
                     '@goto .PriestFinalHeroFinisherHitAttack'):
            self.assertNotIn(stock.text.index(text, charge), battle)
        self.assertNotIn('# V15HeroCardStop', make_program(self.scripts, [], [])['Battle'].values())

    def test_defeat_count_uses_gameover_classifier_and_keeps_the_native_choice(self):
        scene = self.menu['GameOver.HeroFinalNeverGiveUp']
        self.assertEqual((scene['source'], scene['label']), ('GameOver', 'gameover'))
        self.assertEqual(len(scene['presets']), 4)
        for count, preset in enumerate(scene['presets'], 1):
            self.assertIn(f'@set xPriestFinalLoopCount={count}', preset['setupCommands'])
            self.assertIn('@gosub Battle.PriestFinalPlayerDeathTextCheck', preset['setupCommands'])
            self.assertFalse(any('DeathGameOverTextType=' in c for c in preset['setupCommands']))
            self.assertEqual(preset['choices'], 1)
            self.assertEqual(preset['exits'], ['GameOver.GameOverBeforeCore'])
