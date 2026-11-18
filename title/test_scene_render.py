"""Check the measured 16:9 game projection against the full released gallery index."""
import json
import math
from pathlib import Path
import unittest

from scene_render import STILLS, contain_scale
from ui_art import camera_for, projected

class Composition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=json.loads((Path(__file__).resolve().parents[1]/'catalog/gallery.json').read_text(encoding='utf8'))
        cls.scenes={s['id']:s for s in cls.catalog['scenes']}
        cls.assets=cls.catalog['assets']

    def test_measured_old_ending_crops(self):
        h=2*84*math.tan(math.radians(1.5))
        for frame,(measured_w,measured_h) in zip(self.scenes['Ending-186']['frames'],((2.46426,3.83125),(2.62972,3.29568))):
            asset=self.assets[frame['layers'][0]]
            self.assertAlmostEqual(asset['textureW']/100/(16/9*h),measured_w,delta=.015)
            self.assertAlmostEqual(asset['textureH']/100/h,measured_h,delta=.025)

    def test_every_still_and_localized_variant_fits(self):
        count=0
        for scene in self.scenes.values():
            if scene['source'] not in STILLS:continue
            for f in scene['frames']:
                if len(f['layers'])!=1:continue
                for i in f['layers']+f.get('layers2',[]):
                    a=self.assets[i]
                    for info in [a]+([a['localizedGeometry']] if a.get('localizedGeometry') else []):
                        w,h=info['rectW'],info['rectH']
                        left,bottom,right,top,_=projected(scene,f,a,f['layout'][0],(0,0,w,h),(w,h))
                        self.assertGreaterEqual(min(left,bottom),.02-1e-5)
                        self.assertLessEqual(max(top,right),.98+1e-5)
                        count+=1
        self.assertGreater(count,160)

    def test_illustration_fit_uses_both_axes_and_authored_limit(self):
        a={'rectW':2400,'rectH':480,'localizedGeometry':{'rectW':2700,'rectH':510}}
        self.assertLess(contain_scale(a,aspect=4/3),contain_scale(a))
        self.assertLess(contain_scale(a),contain_scale({'rectW':2400,'rectH':480}))
        self.assertEqual(contain_scale(a,authored_limit=.1),.1)

    def test_entire_index_finite_camera_geometry_and_relative_depth(self):
        for scene in self.scenes.values():
            for f in scene['frames']:
                eye,rot=camera_for(scene,f)
                for rows in [f['layers']]+([f['layers2']] if f.get('layers2') else []):
                    self.assertEqual(len(rows),len(f['layout']))
                    for i,p in zip(rows,f['layout']):
                        a=self.assets[i];w,h=a['rectW'],a['rectH']
                        rect=projected(scene,f,a,p,(0,0,w,h),(w,h))
                        self.assertTrue(all(math.isfinite(x) for x in rect))
                        self.assertGreater(rect[2],rect[0])
                        self.assertGreater(rect[3],rect[1])

if __name__=='__main__':unittest.main()
