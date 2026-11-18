import json
import os
from pathlib import Path
import unittest

from backgrounds_render import BackgroundRenderer, project, sea_battle_flash, world_position


class ProjectionTests(unittest.TestCase):

    def test_native_scene_position_and_central_perspective(self):
        self.assertEqual(world_position(50, 50, 100), (0, 0, 100))
        self.assertAlmostEqual(world_position(50, 84.4, 80)[1], 3.7152)
        camera = ((0, 0, -100), (0, 0, 0))
        self.assertEqual(project((0, 0, 100), camera, (1920, 1080)), (960, 540))
        self.assertGreater(project((1, 0, 100), camera, (1920, 1080))[0], 960)
        self.assertLess(project((0, 1, 100), camera, (1920, 1080))[1], 540)

    @unittest.skipUnless(os.getenv('ANNIHILATED_GAME'), 'Installed player required')
    def test_real_stair_cave_and_sky_pixels(self):
        catalog = json.loads(Path(__file__).with_name('gallery.json').read_bytes())
        rooms = {s['id']: s['frames'][0] for s in catalog['scenes']}
        r = BackgroundRenderer(os.environ['ANNIHILATED_GAME'], reader_path=os.getenv('ANNIHILATED_READER'))
        checks = [rooms['Scenario_Mage2-52'], rooms['Opening2-15']]
        checks.extend({'background': catalog['titleBackgrounds'][name]} for name in ('sky', 'sky_night'))
        cave = next(l for l in checks[1]['background']['layers'] if l['actor'] == 'SceneBackground')
        texture, world = r._room_plane(cave)
        self.assertEqual(r.index['actors']['SceneBackground'], [.5, .5, 32.])
        self.assertAlmostEqual(world(texture.width, 0)[0] - world(0, 0)[0],
                               texture.width * cave['scaleX'] / 32,
                               places=6)
        self.assertEqual(r.index['actors']['MainBackground'], [.5, .5, 100.])
        self.assertEqual(r.index['prefabs']['stairs'][0]['transforms'][-1][0], [0., 0., 100.])
        colors = []
        for f in checks:
            img = r.render(f, 320, 180)
            self.assertEqual(img.size, (320, 180))
            self.assertEqual(img.mode, 'RGBA')
            self.assertIsNone(img.convert('RGB').getcolors(64))
            colors.append(img.convert('RGB').resize((1, 1)).getpixel((0, 0)))
        self.assertEqual(len(set(colors)), 4)
        graded = [(s['id'], i) for s in catalog['scenes'] for i, f in enumerate(s['frames'])
                  if any(sea_battle_flash(f['background'], l) for l in f['background']['layers'])]
        self.assertEqual(graded, [('Scenario_Warrior3-1672', 0)])
