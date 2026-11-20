import json
import os
from pathlib import Path
import sys
import unittest


SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE / 'replay')]
from replay_index import make_replay_index
from dungeon_scenes import add_dungeon_helpers, build_dungeon_scenes
from program import make_program
from scenes import build_catalog


@unittest.skipUnless(os.getenv('V14_GALLERY') and os.getenv('V15_SCRIPTS'), 'requires original data')
class ReplayIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gallery = json.loads(Path(os.environ['V14_GALLERY']).read_bytes())
        cls.scripts = json.loads(Path(os.environ['V15_SCRIPTS']).read_bytes())
        cls.index = make_replay_index(cls.gallery)

    def test_only_independent_art_keeps_appearance_and_geometry(self):
        before = [s for s in self.gallery['scenes'] if s['source'] == 'Extras']
        after = [s for s in self.index['scenes'] if s['source'] == 'Extras']
        self.assertEqual([s['id'] for s in before], [s['id'] for s in after])
        self.assertEqual(len(after), 15)
        self.assertEqual([s['id'] for s in after if 'layers2' in s['frames'][0]], ['Extras-74', 'Extras-436'])
        self.assertTrue(all('frames' not in s for s in self.index['scenes'] if s['source'] != 'Extras'))
        self.assertEqual(len(self.index['assets']), 17)
        for old, new in zip(before, after):
            self.assertEqual(new['title'], old['title'])
            frame = new['frames'][0]
            for key in ('layers', 'bindings', 'layers2', 'bindings2'):
                self.assertEqual(frame.get(key), old['frames'][0].get(key))

    def test_all_generated_edits_and_source_coverage_match_the_full_catalogue(self):
        def compile_program(gallery):
            result = build_catalog(self.scripts, gallery)
            dungeon = build_dungeon_scenes(self.scripts, gallery)
            edits = make_program(self.scripts, result['scenes'] + dungeon, result['artworks'], gallery['assets'])
            add_dungeon_helpers(edits, self.scripts)
            return edits, result['scenes'], dungeon, result['coverage']
        self.assertEqual(compile_program(self.gallery), compile_program(self.index))


if __name__ == '__main__':
    unittest.main()
