"""Run offline fixture tests; set ANNIHILATED_GAME and ANNIHILATED_STAGE for the installed-build audit."""
import hashlib
import json
import os
import struct
from pathlib import Path
import unittest

from addressables import address_paths
from backgrounds import BG_PREFIXES, camera_default, update_camera
from build_catalog import Builder, Library, ROOT, SPEAKERS, translations


def source(index, kind, text, line_hash=''):
    return [index, kind, line_hash, text, 0]


class TextMappingTests(unittest.TestCase):

    def test_camera_tracks_authored_space_and_relative_movements(self):
        camera = camera_default()
        update_camera(camera, {'pos': '1,2,{vcamDefaultZ+10}'})
        self.assertEqual(camera['positionMode'], 'pos')
        self.assertEqual(camera['pos'], [1, 2, -90])
        update_camera(camera, {'offset': '0,0,-100'})
        update_camera(camera, {'offsetadd': ',,10', 'rotation': '0.25,0,0'})
        self.assertEqual(camera['positionMode'], 'offset')
        self.assertEqual(camera['offset'], [0, 0, -90])
        self.assertEqual(camera['rotation'], [.25, 0, 0])
        update_camera(camera, {'offset': ',{runtimeY},'})
        self.assertTrue(camera['dynamic'])

    def test_localization_hash_and_utf8_substring(self):
        raw = '  Mage:  “我们走吧。”'
        local = [[0, 'Label', '', '# a1', 0], [1, 'GenericText', '', raw, 100]]
        result = translations([source(35, 'GenericText', 'unused', 'a1')], local)[35]
        self.assertEqual(result['speaker'], '魔法师')
        self.assertEqual(raw.encode()[result['offset'] - 100:][:result['length']].decode(), '“我们走吧。”')

    def test_quoted_expression_and_two_speakers(self):
        raw = '@print "{TranslateName("partner")}回过头。" waitInput:false'
        second = 'Warrior＆Me{playerType}: “一起走。”'
        loc = [[0, 'Label', '', '# a1', 0], [1, 'Command', '', raw, 300], [2, 'Label', '', '# b2', 0],
               [3, 'GenericText', '', second, 600]]
        m = translations([source(0, 'Command', '', 'a1'), source(1, 'GenericText', '', 'b2')], loc)
        o = m[0]['offset'] - 300
        self.assertEqual(raw.encode()[o:o + m[0]['length']].decode(), '{TranslateName("partner")}回过头。')
        self.assertEqual(m[1]['speaker'], '战士、士兵')

    def test_repeated_hash_preserves_localization_order(self):
        loc = [[0, 'Label', '', '# same', 0], [1, 'GenericText', '', '一', 100], [2, 'Label', '', '# same', 0],
               [3, 'GenericText', '', '二', 400]]
        m = translations([source(i, 'GenericText', '', 'same') for i in (4, 11)], loc)
        self.assertEqual([m[4]['offset'], m[11]['offset']], [100, 400])

    def test_roulette_metadata_excluded(self):
        raw = '@choice "探路[search][dex:7;success:2/death:2]" goto:.Search'
        m = translations([source(1, 'Command', '', 'a')],
                         [[0, 'Label', '', '# a', 0], [1, 'Command', '', raw, 0]])[1]
        self.assertEqual(raw.encode()[m['offset']:m['offset'] + m['length']].decode(), '探路')
        self.assertEqual(m['kind'], 'choice')


class BranchTests(unittest.TestCase):

    def setUp(self):
        paths = ['Assets/Test/A.png', 'Assets/Test/B.png', 'Assets/Test/C.png', 'Assets/Test/D.png']
        actors = [
            'MainBackground/CG/A1', 'MainBackground/CG/A2', 'OptionalCGBackground/C', 'MainBackground/CG/D'
        ]
        self.lib = Library([['bundle', p, 'Texture2D', i] for i, p in enumerate(paths)], {
            ROOT + k: p
            for k, p in zip(actors, paths)
        })
        self.builder = Builder(self.lib)

    def test_branch_carry_and_explicit_layer_ids(self):
        cmd = [
            '@back CG/A{playerType} pos:50,50,-16', '@back C id:OptionalCGBackground pos:50,50,-17',
            '@choice "left" goto:.Left', '@choice "right" goto:.Right', '@stop', '# Left',
            '@hide OptionalCGBackground', 'first', '@goto .Done', '# Right', 'second', '@goto .Done',
            '# Done', '@back CG/D', 'last'
        ]
        kinds = [
            'Label' if t.startswith('#') else ('Command' if t.startswith('@') else 'GenericText') for t in cmd
        ]
        rows = [source(i, k, t) for i, (k, t) in enumerate(zip(kinds, cmd))]
        loc = {i: {'offset': 1000 + i, 'length': 2, 'kind': 'text', 'speaker': ''} for i in (2, 3, 7, 10, 14)}
        self.builder.script('Opening2', rows, loc)
        right = next(s for s in self.builder.scenes if s['label'] == 'Right')
        left = next(s for s in self.builder.scenes if s['label'] == 'Left')
        self.assertEqual(left['frames'][-1]['layers'], [0])
        self.assertEqual(right['frames'][-1]['layers'], [0, 2])
        self.assertEqual(right['frames'][-1]['layers2'], [1, 2])
        self.assertEqual(right['frames'][-1]['bindings'][1], {
            'actor': 'OptionalCGBackground',
            'appearance': 'C'
        })
        self.assertEqual(right['choice']['offset'], 1003)
        self.assertEqual(left['choice']['offset'], 1002)


class ShippedCatalogTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(Path(__file__).with_name('gallery.json').read_text(encoding='utf8'))
        cls.scenes = cls.data['scenes']
        cls.frames = [f for s in cls.scenes for f in s['frames']]

    def test_all_assets_reachable_and_unique(self):
        assets = self.data['assets']
        self.assertEqual([a['id'] for a in assets], list(range(len(assets))))
        self.assertEqual(len({a['path'] for a in assets}), len(assets))
        reached = {i for f in self.frames for i in f['layers'] + f.get('layers2', [])}
        self.assertEqual(reached, {a['id'] for a in assets if a['kind'] != 'technical'})
        for f in self.frames:
            self.assertTrue(any(assets[i]['kind'] == 'art' for i in f['layers']))
        self.assertFalse(any(s.get('type') == 'effect' for s in self.scenes))
        self.assertEqual(set(s['group'] for s in self.scenes),
                         {'Hero', 'Mage', 'Warrior', 'Priest', 'Shared'})
        self.assertEqual(len(set(s['id'] for s in self.scenes)), len(self.scenes))
        for group in ('Hero', 'Mage', 'Warrior', 'Priest'):
            sections = [s['chapter'] for s in self.scenes if s['group'] == group]
            self.assertEqual(sections, sorted(sections))
            self.assertTrue(set(range(1, 6)) <= set(sections))

    def test_real_branch_and_texture_alias_examples(self):
        choices = [
            s for s in self.scenes if s['source'] == 'Scenario_Priest5' and s['label'] == 'ChoicePriestLast'
            and s['frames'][0].get('branch') in ('Sayonara', 'Mugon', 'Suki')
        ]
        self.assertEqual(len(choices), 3)
        self.assertEqual(len({s['frames'][0]['layers2'][-1] for s in choices}), 3)
        self.assertTrue(all(s['frames'][0]['lines'][0]['kind'] == 'choice' for s in choices))
        self.assertTrue(all(s['frames'][0]['lines'][1]['kind'] == 'text' for s in choices))
        self.assertTrue(
            any(b['appearance'] == 'CG/deadMeAfterChoice'
                and self.data['assets'][i]['path'].endswith('/deadAfterMeChoice.png') for f in self.frames
                for i, b in zip(f['layers'], f['bindings'])))
        self.assertEqual(len([a for a in self.data['assets'] if 'resource' in a]), 5)

    def test_opening_scenery_and_ending_specials(self):
        scene = next(s for s in self.scenes if s['id'] == 'Opening2-15')
        bg = scene['frames'][0]['background']
        slots = {(layer['actor'], layer['appearance']) for layer in bg['layers']}
        self.assertIn(('SceneBackground', 'cave_moss'), slots)
        self.assertIn(('RoadBackground', 'first'), slots)
        self.assertFalse(any(actor == 'FrameBackground' for actor, appearance in slots))
        stairs = next(s for s in self.scenes if s['id'] == 'Scenario_Mage2-52')['frames'][0]['background']
        self.assertEqual(stairs['prefab'], 'stairs')
        self.assertFalse(any(l['actor'].startswith('ColorFlash') for l in stairs['layers']))
        self.assertTrue(any(l['appearance'] == 'black' for l in stairs['sourceScreens']))
        title = next(s for s in self.scenes if s['source'] == 'Title' and 'MageSecret' in s['label'])
        self.assertEqual(title['frames'][0]['background']['name'], 'maou_gyokuza')
        self.assertAlmostEqual(title['frames'][0]['layout'][0]['scale'], 0.38734)
        ending = next(s for s in self.scenes if s['source'] == 'Ending' and s['label'] == 'hero')
        self.assertEqual(ending['frames'][0]['background']['mode'], 'plain')
        self.assertAlmostEqual(ending['frames'][0]['layout'][0]['scale'], 0.35)
        self.assertAlmostEqual(ending['frames'][0]['layout'][0]['x'], 43.75)
        for asset in self.data['assets']:
            self.assertGreater(asset['rectW'], 0)
            self.assertGreater(asset['rectH'], 0)
            self.assertGreater(asset['pixelsPerUnit'], 0)

    def test_visible_joint_role_links_and_origin_preservation(self):
        scenes = {s['id']: s for s in self.scenes}
        joint = scenes['Scenario_Warrior5-1620']
        self.assertEqual(joint['group'], 'Warrior')
        index = joint['alsoFrames']['Mage']
        self.assertIn('warrior5idolepilogue', joint['frames'][index]['bindings'][-1]['appearance'].lower())
        solo = scenes['Scenario_Hero4-361']
        self.assertNotIn('Priest', solo.get('alsoGroups',
                                            []))  # soldier + priest in this cut, no hero painted
        self.assertEqual(scenes['Opening3-71']['group'], 'Shared')
        for s in self.scenes:
            self.assertEqual(set(s.get('alsoFrames', {})), set(s.get('alsoGroups', [])))
            self.assertNotIn(s['group'], s.get('alsoGroups', []))
            self.assertTrue(all(0 <= i < len(s['frames']) for i in s.get('alsoFrames', {}).values()))

    def test_scenery_dungeon_callbacks_and_camera_geometry(self):
        for f in self.frames:
            self.assertIn(f['camera']['positionMode'], ('pos', 'offset'))
            self.assertTrue(f['background']['mode'] in ('script', 'inherited', 'variable', 'plain',
                                                        'standalone'))
            z = [l['z'] for l in f['background']['layers']]
            self.assertEqual(z, sorted(z, reverse=True))
        dungeon = next(s for s in self.scenes if s['source'] == 'Dungeon')
        for f in dungeon['frames']:
            p = f['layout'][0]
            self.assertEqual((p['scale'], p['x'], p['y'], p['z']), (.35, 50, 53, -16.1))
            self.assertIn('sea', f['background']['alternateNames'])
        mage_fall = next(s for s in self.scenes
                         if s['source'] == 'Scenario_Mage1' and s['label'] == 'MergeSearch')
        self.assertIn('dungeon_blue', {f['background']['name'] for f in mage_fall['frames']})
        titles = self.data['titleBackgrounds']
        self.assertEqual(titles['sky_night']['prefab'], 'sky_night')
        self.assertEqual(titles['maou_gyokuza']['prefab'], 'maou_gyokuza')
        self.assertEqual(titles['stairs']['prefab'], 'stairs')
        for asset in self.data['assets']:
            if 'resource' in asset: self.assertGreater(asset['localizedGeometry']['pixelsPerUnit'], 0)

    def test_same_illustration_can_follow_the_original_room_transition(self):
        by_id = {s['id']: s for s in self.scenes}
        for sid, sequence in [('Scenario_Mage4-1344', ['dungeon_red', 'dungeon_blue']),
                              ('Scenario_Warrior3-1672', ['sea', 'dungeon_blue'])]:
            first, second = by_id[sid]['frames'][:2]
            self.assertEqual(first['layers'], second['layers'])
            self.assertEqual([first['background']['name'], second['background']['name']], sequence)
            self.assertGreater(second['line'], first['line'])
            self.assertNotEqual(first['lines'], second['lines'])
        self.assertEqual(by_id['Scenario_Mage4-1344']['frames'][1]['layout'][0]['y'], 50)

    def test_verified_choice_links_target_distinct_local_scenes(self):
        scenes = {s['id']: s for s in self.scenes}
        expected = {f'Scenario_Hero1-{i}' for i in (743, 777, 805)}
        origin = scenes['Scenario_Hero1-599']
        self.assertEqual({b['sceneId'] for b in origin['branches']}, expected)
        self.assertTrue(
            any({b['sceneId']
                 for b in f.get('branches', [])} == expected for f in origin['frames']))
        s = scenes['Scenario_Priest5-1163-Suki']
        self.assertEqual({b['sceneId'].split('-')[-1] for b in s['branches']}, {'Mugon', 'Sayonara'})
        for s in self.scenes:
            for item in [s] + s['frames']:
                links = item.get('branches', [])
                self.assertEqual(len(links), len({b['sceneId'] for b in links}))
                for b in links:
                    target = scenes[b['sceneId']]
                    self.assertNotEqual(target['id'], s['id'])
                    self.assertEqual(target['source'], s['source'])
                    self.assertEqual(target['choice'], b['choice'])

    def test_bindings_and_depth_for_each_frame(self):
        for f in self.frames:
            self.assertEqual(len(f['layers']), len(f['bindings']))
            self.assertEqual(len(f.get('layers2', f['layers'])), len(f.get('bindings2', f['bindings'])))
            depths = [b['z'] for b in f['layout']]
            self.assertEqual(depths, sorted(depths, reverse=True))
            self.assertEqual(len({b['actor'] for b in f['bindings']}), len(f['bindings']))
            for l in f['lines']:
                self.assertIn(l['kind'], ('text', 'choice'))
                self.assertGreater(l['length'], 0)
                self.assertGreaterEqual(l['offset'], 0)
                self.assertLessEqual(l['offset'] + l['length'], self.data['resourcesSize'])

    @unittest.skipUnless(
        os.environ.get('ANNIHILATED_GAME') and os.environ.get('ANNIHILATED_STAGE'),
        'Set ANNIHILATED_GAME and ANNIHILATED_STAGE for the real installation audit')
    def test_all_installed_pictures_and_localized_bytes(self):
        game = Path(os.environ['ANNIHILATED_GAME']) / 'Annihilated_Data'
        stage = Path(os.environ['ANNIHILATED_STAGE'])
        data = (game / 'resources.assets').read_bytes()
        aa = game / 'StreamingAssets' / 'aa'
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.data['resourcesSha256'])
        # Official I2Languages entries use aligned Japanese, English and Simplified Chinese strings.
        for role in ('Hero', 'Mage', 'Warrior', 'Priest', 'Outcast', 'Villainess', 'Dropout', 'Dealer'):
            key = ('Character/' + role.lower()).encode('ascii')
            i = data.index(struct.pack('<I', len(key)) + key) + 4
            pos = ((i + len(key) + 3) & ~3) + 8
            labels = []
            for _ in range(3):
                size = struct.unpack_from('<I', data, pos)[0]
                pos += 4
                labels.append(data[pos:pos + size].decode('utf8'))
                pos = (pos + size + 3) & ~3
            self.assertEqual(labels[2], SPEAKERS[role])
        self.assertEqual((aa / 'catalog.hash').read_text().strip(), self.data['catalogHash'])
        stock = stage / 'catalog-stock.bin'
        binary = (stock if stock.is_file() else aa / 'catalog.bin').read_bytes()
        addresses = {k.lower(): v for k, v in address_paths(binary).items()}
        scenery = {k.lower() for k in address_paths(binary, BG_PREFIXES)}
        prefabs = {
            Path(v).stem
            for v in address_paths(binary, ('Naninovel/Backgrounds/', ), path_suffix='.prefab').values()
        }
        for bg in list(self.data['titleBackgrounds'].values()) + [f['background'] for f in self.frames]:
            if bg['prefab']: self.assertIn(bg['prefab'], prefabs)
            for l in bg['layers'] + bg.get('sourceScreens', []):
                self.assertIn((ROOT + l['actor'] + '/' + l['appearance']).lower(), scenery)
        assets = self.data['assets']
        self.assertEqual(set(addresses.values()), {a['path'] for a in assets})
        inventory = {(r[0], r[1])
                     for r in json.loads((stage / 'images.json').read_text(encoding='utf8'))
                     if r[2] == 'Texture2D'}
        for a in assets:
            self.assertIn((a['bundle'], a['path']), inventory)
            self.assertTrue((aa / 'StandaloneWindows64' / a['bundle']).is_file())
        for f in self.frames:
            for art, bindings in ((f['layers'], f['bindings']), (f.get('layers2', f['layers']),
                                                                 f.get('bindings2', f['bindings']))):
                for aid, b in zip(art, bindings):
                    self.assertEqual(addresses[(ROOT + b['actor'] + '/' + b['appearance']).lower()],
                                     assets[aid]['path'])
        official = {}
        for rows in json.loads((stage / 'zh.json').read_text(encoding='utf8')).values():
            for _, kind, _, text, start in rows:
                if kind in ('GenericText', 'Command'):
                    official[start] = text.encode()
        import bisect
        starts = sorted(official)
        for s in self.scenes:
            refs = [l for f in s['frames'] for l in f['lines']]
            if 'choice' in s: refs.append(s['choice'])
            for row in refs:
                start = row['offset']
                offset = starts[bisect.bisect_right(starts, start) - 1]
                body = data[start:start + row['length']]
                self.assertEqual(official[offset][start - offset:start - offset + len(body)], body)
                value = body.decode()
                self.assertFalse(value.startswith('@'))
                self.assertNotIn('[back ', value)
                self.assertEqual(value.count('{'), value.count('}'))


if __name__ == '__main__':
    unittest.main()
