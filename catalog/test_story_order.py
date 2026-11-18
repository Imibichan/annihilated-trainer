"""Regression examples pinned to the stock v1.4 gallery's source positions."""
import json
import os
import unittest
from pathlib import Path
from story_order import Source, apply_story_order


class PublishedOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index = Path(os.environ.get('GALLERY_ORDER_TEST_INDEX',Path(__file__).with_name('gallery.json')))
        cls.scenes = json.loads(index.read_bytes())['scenes']
        cls.by_id = {s['id']: s for s in cls.scenes}

    def expect(self, scene_id, role, floor):
        s = self.by_id[scene_id]
        self.assertEqual((s['group'], s['chapter']), (role, floor), scene_id)

    def precedes(self, *ids):
        positions = [self.scenes.index(self.by_id[i]) for i in ids]
        self.assertEqual(positions, sorted(positions), ids)

    def test_mage_battle_inside_original_encounter(self):
        self.expect('Battle-12742', 'Mage', 5)
        self.precedes('Scenario_Mage3-35', 'Scenario_Mage3-614', 'Battle-10712', 'Battle-10771')
        self.precedes('Scenario_Mage5-2300', 'Battle-12583', 'Battle-12644',
                      'Battle-12742', 'Scenario_Mage5-2561')

    def test_genuine_first_floor_detours_and_trial_endings(self):
        for group, line in [('Hero',27),('Mage',45),('Priest',74),('Warrior',117)]:
            self.expect(f'TrialEnd-{line}', group, 1)
            self.expect('TrialEnd-182-' + group, group, 7)
            self.assertEqual(self.by_id['TrialEnd-182-' + group]['sequenceKind'], 'trial')
        self.precedes('Scenario_Mage1-415', 'TrialEnd-45', 'Scenario_Mage1-633')

    def test_other_routes_and_shared_combat(self):
        self.expect('Opening3-2284', 'Hero', 0)
        self.precedes('Scenario_Warrior5-85', 'Battle-9494', 'Battle-9860', 'Scenario_Warrior5-627')
        self.precedes('Scenario_Priest5-323','Battle-13117','Battle-13230','Scenario_Priest5-445')
        self.expect('GameOver-88','Shared',7)
        self.expect('Scenario-472','Shared',3)
        self.expect('Battle-14769','Shared',2)
        self.expect('Scenario_Hero4-1233','Shared',4)
        self.assertEqual({x['source'] for x in self.by_id['Scenario_Hero4-1233']['storyOrigins']},
                         {'Scenario_Hero4','Scenario_Priest4','Scenario_Warrior4'})
        self.precedes('Scenario_Priest5-664','Scenario_Priest5-812','Scenario_Priest5-851',
                      'Scenario_Priest5-918','Scenario_Priest5-968','Scenario_Priest5-1163-Sayonara',
                      'Scenario_Priest5-1163-Suki','Scenario_Priest5-1163-Mugon','Scenario_Priest5-1246')

    def test_unplaced_art_and_random_event_sections(self):
        for s in self.scenes:
            if s['source'] in ('Extras','Dungeon'):
                self.expect(s['id'],'Shared',7)
                self.assertEqual(s['sequenceKind'],{'Extras':'unplaced','Dungeon':'random'}[s['source']])
        self.assertNotIn('alsoGroups',self.by_id['Scenario_Mage3-386'])

    def test_ending_title_was_selected_by_same_ending_type(self):
        self.precedes('Ending-92','Ending-129','Ending-120','Title-429')
        self.assertEqual(self.scenes.index(self.by_id['Title-431']),
                         self.scenes.index(self.by_id['Ending-138'])+1)
        self.precedes('Ending-205','Title-439')
        self.precedes('Ending-186','Title-439')


class StaticTraversal(unittest.TestCase):
    @staticmethod
    def rows(text):
        return [[i,'Label' if t.startswith('#') else 'Command','',t,0] for i,t in enumerate(text)]

    def test_jump_and_nested_choice_order_survive_permuted_labels(self):
        flow = self.rows(['# start','@back Intro','@choice "X" goto:.a','@choice "Y" goto:.b','@stop',
                          '# finish','@back Last','@return','# b','@back B','@goto .finish',
                          '# a','@back A','@goto .finish'])
        scene_order = Source(flow).local_order([1,6,9,12],[[('a',{}),('b',{})]])
        self.assertEqual(sorted(scene_order,key=scene_order.get),[1,12,9,6])

    def test_missing_optional_trigger_moves_only_affected_record(self):
        dungeon = self.rows(['@gosub Scenario_{tempPartnerName}{tempScenarioDungeonId}.ToDungeon{tempScenarioDungeonId}',
                             '@gosub Scenario_{tempPartnerName}{dungeonId}.{bossId}{temp}'])
        src = {'Dungeon':dungeon,'Battle':self.rows(['# HatsugenTest22']),
               'Scenario_Mage3':self.rows(['# ToDungeon3','@back Castle'])}
        scenes = [dict(id='battle',source='Battle',label='DropoutMageChargeModeBranch',line=0),
                  dict(id='story',source='Scenario_Mage3',label='ToDungeon3',line=1)]
        apply_story_order(scenes,src,{})
        self.assertEqual([(s['id'],s['group'],s['chapter'],s['sequenceKind']) for s in scenes],
                         [('story','Mage',3,'story'),('battle','Shared',7,'conditional')])
