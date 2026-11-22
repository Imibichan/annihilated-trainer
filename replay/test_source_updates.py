"""Regression checks for shifted labels, missing native callbacks, and Steam CG updates."""
import json
import os
from pathlib import Path
import unittest

from program import compile_replays
from program_checks import ProgramChecks
from scenes import ScriptMap, build_catalog
from source_anchors import SourceBlocks, resolve_gallery


class SemanticAnchorTests(unittest.TestCase):
    def test_duplicate_artwork_requires_the_correct_context(self):
        rows = [
            [0, 'Label', 'a', '# Scene'], [1, 'Command', '1', '@set item=1'],
            [2, 'Command', 'x', '@back "CG/shared"'], [3, 'Command', '2', '@set item=2'],
            [4, 'Empty', '', ''], [5, 'Command', 'x', '@back "CG/shared"'],
        ]
        blocks = SourceBlocks(rows)
        self.assertEqual(blocks.resolve(['Scene', 'x', '2', 'CG/shared']), 5)
        self.assertIsNone(blocks.resolve(['Scene', 'x', '', 'CG/shared']))
        self.assertIsNone(blocks.resolve(['Scene', 'x', 'missing', 'CG/shared']))

    def test_updated_gender_resource_keeps_its_original_observation(self):
        row = [3, 'Command', 'changed', '@back "CG/sharedMe{playerType}" time:1']
        blocks = SourceBlocks([[0, 'Label', 'a', '# Scene'], row])
        self.assertEqual(blocks.resolve(['Scene', 'old', '', 'CG/shared']), 3)

    def test_native_branch_with_duplicated_label_stays_out_of_the_menu(self):
        rows = [[0, 'Label', 'a', '# Start'], [1, 'Command', 'g', '@goto .Choice'],
                [2, 'Label', 'b', '# Choice'], [3, 'Command', 'r', '@return'],
                [4, 'Label', 'b', '# Choice'], [5, 'Command', 'r', '@return']]
        route = ScriptMap({'Story': rows}).trace('Story', 'Start')
        self.assertTrue(any('重名' in reason for reason in route['issues']))

    def test_relocated_relative_jumps_and_ambiguous_targets_are_rejected(self):
        scripts = {'Source': [[0, 'Label', 's', '# Start'], [1, 'Command', 'g', '@goto .Start']],
                   'Menu': [[0, 'Label', 'm', '# Start']]}
        checks = ProgramChecks(scripts)
        with self.assertRaisesRegex(ValueError, '局部跳转'):
            checks.validate({'Menu': {1: ('Source', 1)}})
        with self.assertRaisesRegex(ValueError, '重名'):
            checks.validate({'Source': {1: ('Source', 1), 2: '# Start'}})


@unittest.skipUnless(os.getenv('V14_GALLERY') and (os.getenv('V15_SCRIPTS') or os.getenv('V16_GAME')),
                     'requires the installed game or its decoded script rows and the gallery index')
class NativeUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv('V16_GAME'):
            from script_assets import read_script_rows
            cls.scripts = read_script_rows(Path(os.environ['V16_GAME']))
        else:
            cls.scripts = json.loads(Path(os.environ['V15_SCRIPTS']).read_bytes())
        cls.gallery = json.loads(Path(os.environ['V14_GALLERY']).read_bytes())

    def test_script_row_insertions_preserve_all_entries_and_guard_the_moved_quickload(self):
        scripts = dict(self.scripts)
        for name in ('Opening3', 'Battle', 'Dungeon', 'Scenario_Priest5'):
            scripts[name] = [[0, 'Comment', 'extra', ';', 0]] + [
                [row[0]+1, *row[1:]] for row in scripts[name]]
        edits, report = compile_replays(scripts, self.gallery)
        self.assertEqual((report['scenes'], report['artworks'], report['excluded']), (204, 15, {}))
        current = next(r[0] for r in scripts['Opening3'] if r[3].strip().lower() == '@quickload')
        self.assertEqual(edits['Opening3'][current], f'@goto .V15BeforeLoad{current}')

    def test_unindexed_illustration_is_discovered_from_a_current_native_callback(self):
        source = 'Scenario_Mage1'
        scripts = dict(self.scripts)
        commands = [list(row) for row in scripts[source]]
        start = next(r[0] for r in commands if r[1] == 'Label' and r[3].strip() == '# Outcast2')
        index = start+1
        commands.insert(index, [index, 'Command', 'new-image', '@back "CG/futureMageMe{playerType}"', 0])
        scripts[source] = [[i, *r[1:]] for i, r in enumerate(commands)]
        catalog = build_catalog(scripts, self.gallery)
        key = source + '.Outcast2/CG/futureMageMe{playerType}'
        self.assertEqual(catalog['coverage']['nativeIllustrations'][key], 'script-reviewed')
        scene = next(s for s in catalog['scenes'] if s['id'] == source+'.Outcast2')
        self.assertIn(key, scene['galleryIds'])

    def test_an_incompatible_roulette_choice_only_excludes_its_own_scene(self):
        scripts = dict(self.scripts)
        scripts['Dungeon'] = [list(r) for r in scripts['Dungeon']]
        row = next(r for r in scripts['Dungeon'] if 'goto:.eventHero1_avoid' in r[3])
        row[3] = row[3].replace('.eventHero1_avoid', '.RenamedChoice')
        edits, report = compile_replays(scripts, self.gallery)
        self.assertEqual((report['scenes'], report['artworks']), (203, 15))
        self.assertEqual(set(report['excluded']), {'Scenario_Hero1.Outcast1'})
        self.assertNotIn('@gosub Scenario_Hero1.Outcast1', edits['Test2'].values())

    def test_missing_scene_script_leaves_other_chapters_playable(self):
        scripts = dict(self.scripts)
        del scripts['Scenario_Mage4']
        edits, report = compile_replays(scripts, self.gallery)
        self.assertEqual((report['scenes'], report['artworks']), (198, 15))
        self.assertTrue(all(uid.startswith('Scenario_Mage4.') for uid in report['excluded']))
        self.assertIn('@gosub Scenario_Priest5.PriestBattleAfterHighLoop', edits['Test2'].values())

    @unittest.skipUnless(os.getenv('V16_GAME'), 'requires current native Steam Addressables')
    def test_missing_one_gender_asset_drops_only_the_affected_preset_or_artwork(self):
        from addressables import address_paths
        from script_assets import AA
        game = Path(os.environ['V16_GAME'])
        addresses = set(address_paths((game / AA / 'catalog.bin').read_bytes()))
        prefix = 'Naninovel/Backgrounds/MainBackground/CG/'
        addresses.remove(prefix + 'mage4souMaryokuOmowazuSonoKatawaraESuwarikondeMe2')
        addresses.remove(prefix + 'cutinMe2')
        _, report = compile_replays(self.scripts, self.gallery, artwork_addresses=addresses)
        self.assertEqual((report['scenes'], report['artworks']), (204, 14))
        self.assertIn('Extras-74', report['excluded'])
        self.assertEqual(set(report['excludedPresets']['Scenario_Mage4.SlimeBattleAfter']), {'取回魔力'})

    @unittest.skipUnless(os.getenv('V16_GAME'), 'requires current native Steam build with the new artwork')
    def test_updated_illustrations_play_in_the_correct_native_branch(self):
        scripts = self.scripts
        catalog = build_catalog(scripts, self.gallery)
        by_id = {s['id']: s for s in catalog['scenes']}
        mage = by_id['Scenario_Mage4.SlimeBattleAfter']['presets']
        priest = by_id['Scenario_Priest4.Slime2']['presets']
        added = [
            ('Scenario_Mage4', 'SlimeBattleAfterMaryokuRoute', 'CG/mage4souMaryokuOmowazuSonoKatawaraESuwarikondeMe{playerType}'),
            ('Scenario_Mage4', 'SlimeBattleAfterMaryokuRoute', 'CG/mage4souMaryokuUshiroKaraHikaemeNiKakattaKoeNiMe{playerType}'),
            ('Scenario_Mage4', 'SlimeBattleAfterMaryokuRoute', 'deadAfterMeChoice'),
            ('Scenario_Priest4', 'Slime2SanHigh', 'CG/priest4souMayottaKenWoMitibikuYouni'),
        ]
        for source, label, art in added:
            main, alt = mage if source == 'Scenario_Mage4' else priest
            self.assertIn(source+'.'+label+'/'+art, main['galleryIds'])
            self.assertNotIn(source+'.'+label+'/'+art, alt['galleryIds'])
        self.assertIn('@set xSwitchMageChoiceGetMaryoku=1', mage[0]['setupCommands'])
        self.assertIn('@set xSwitchChoicePriestLook=0', priest[0]['setupCommands'])
        rows, missing = resolve_gallery(scripts, self.gallery)
        self.assertFalse(missing)
        high_loop = next(r for r in rows if r['id'] == 'Scenario_Priest5-968')
        self.assertIn('CG/priest5souHighLoopMiorosuMe{playerType}', scripts[high_loop['source']][high_loop['line']][3])
        self.assertIn(high_loop['id'], by_id['Scenario_Priest5.PriestBattleAfterHighLoop']['galleryIds'])
        edits, _ = compile_replays(scripts, self.gallery)
        for row in rows:
            if row is high_loop or row['id'] in catalog['coverage']['nativeIllustrations']:
                self.assertNotIn(row['line'], edits.get(row['source'], {}))
