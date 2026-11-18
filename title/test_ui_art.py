"""Exercise gallery-only rendering and compare two physically measured frames."""
import json
from pathlib import Path
import unittest
from ui_art import Paint, projected, camera_for, paint_events, settled_frame
from PIL import Image

class GalleryOnly(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((Path(__file__).resolve().parents[1]/'catalog/gallery.json').read_text(encoding='utf8'))
  cls.ending=next(s for s in cls.data['scenes'] if s['id']=='Ending-186')
 def test_ending_rects_match_visible_pixels_in_real_game(self):
  for fi,expected in [(0,(182,7,778,529)),(1,(154,37,816,503))]:
   f=self.ending['frames'][fi]; a=self.data['assets'][f['layers'][0]]; w,h=a['rectW'],a['rectH']
   left,bottom,right,top,angle=projected(self.ending,f,a,f['layout'][0],(0,0,w,h),(w,h))
   sample=(left*960,(1-top)*540,right*960,(1-bottom)*540)
   for x,y in zip(sample,expected):self.assertAlmostEqual(x,y,delta=7)
 def test_camp_uses_illustration_pose_after_original_camera_settles(self):
  scenes={s["id"]:s for s in self.data["scenes"]}
  def rect(id):
   s=scenes[id];f=s["frames"][0];a=self.data["assets"][f["layers"][0]]
   w,h=a["rectW"],a["rectH"]
   return projected(s,f,a,f["layout"][0],(0,0,w,h),(w,h))
  self.assertEqual(rect("Scenario_Mage2-52"),rect("Scenario_Mage2-151"))
 def test_camp_framing_survives_an_inserted_dialogue_line(self):
  camp=next(s for s in self.data["scenes"] if s["source"]=="Scenario_Mage2" and s["label"]=="ToDungeon2")
  f=camp["frames"][0];a=self.data["assets"][f["layers"][0]];w,h=a["rectW"],a["rectH"]
  args=(f,a,f["layout"][0],(0,0,w,h),(w,h))
  self.assertEqual(projected(camp,*args),projected(dict(camp,id="Scenario_Mage2-79"),*args))
 def test_complete_frame_fits_rotated_layers_without_moving_them_independently(self):
  from scene_render import fitted_rects, bounds
  old=[(-.4,-.25,.7,1.3,-20),(.21,.16,.86,.82,12)]
  result=fitted_rects(old)
  for r in result:
   l,b,rr,t=bounds(r)
   self.assertGreaterEqual(min(l,b,1-rr,1-t),.01999)
  factor=(result[0][2]-result[0][0])/(old[0][2]-old[0][0])
  for j in range(4):
   self.assertAlmostEqual(result[0][j]-result[1][j],factor*(old[0][j]-old[1][j]))
  self.assertEqual([r[4] for r in result],[-20,12])
 def test_complete_view_preserves_clear_offcentre_composition_and_enlarges_small_insert(self):
  from scene_render import fitted_rects
  picture=(.12,.1,.70,.88,0)
  self.assertEqual(fitted_rects([picture]),[picture])
  tiny=(.4,.46,.52,.56,0);out=fitted_rects([tiny])[0]
  self.assertGreater(out[2]-out[0],.4)
 def test_alpha_visibility_measures_the_ink_instead_of_the_texture_rectangle(self):
  from scene_render import visible_fraction
  rect=(-.5,0,.5,1,0)
  left=bytes(255 if i%32<16 else 0 for i in range(32*32))
  right=bytes(255-value for value in left)
  self.assertEqual(visible_fraction(rect,left),0)
  self.assertEqual(visible_fraction(rect,right),1)
  self.assertAlmostEqual(visible_fraction(rect,bytes([255])*1024),.5)
 def test_empty_staging_cue_uses_immediate_authored_wider_lens_with_same_art(self):
  scene=next(s for s in self.data['scenes'] if s['id']=='Scenario_Warrior5-1620')
  fitted=settled_frame(scene,2)
  self.assertEqual(fitted['layers'],scene['frames'][2]['layers'])
  self.assertEqual(fitted['camera'],scene['frames'][3]['camera'])
  self.assertEqual(camera_for(scene,fitted)[0][2],-70)
  disjoint=dict(scene,frames=[scene['frames'][2],dict(scene['frames'][3],layers=[-1])])
  self.assertIs(settled_frame(disjoint,0),disjoint['frames'][0])
 def test_full_picture_rolls_to_separate_native_page_with_constant_cost(self):
  from types import SimpleNamespace
  painter=SimpleNamespace(scroller=234)
  for state in (True,False):
   stop,select=Paint.framing_calls(painter,state)
   self.assertEqual([call['m_MethodName'] for call in (stop,select)],['StopMovement','set_horizontalNormalizedPosition'])
   self.assertEqual(select['m_Target']['m_PathID'],234)
   self.assertEqual(select['m_Arguments']['m_FloatArgument'],float(state))
   self.assertEqual(select['m_TargetAssemblyTypeName'],'UnityEngine.UI.ScrollRect, UnityEngine.UI')
 def test_scene_overlay_keeps_native_semitransparent_colour_on_both_projections(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  gallery=Mock();gallery.ids=SimpleNamespace(raw_image=2,renderer=1)
  for opacity in (153,204,238):
   Paint.image(SimpleNamespace(gallery=gallery),3,'test',4,opacity=opacity)
   self.assertAlmostEqual(gallery.component.call_args.kwargs['m_Color']['a'],opacity/255)
 def test_draw_selectors_cannot_invoke_a_script_or_global_service(self):
  actions=paint_events(112,[221,222],1,[(331,332),(333,334)],2)
  self.assertEqual({c['m_TargetAssemblyTypeName'] for c in actions},{'UnityEngine.GameObject, UnityEngine.CoreModule'})
  self.assertEqual({c['m_MethodName'] for c in actions},{'SetActive'})
  self.assertEqual({c['m_Target']['m_PathID'] for c in actions if c['m_Arguments']['m_BoolArgument']},{112,222,334})
 def test_layer_crop_keeps_same_center_and_relative_size(self):
  f=self.ending['frames'][0]; a=self.data['assets'][f['layers'][0]]; w,h=a['rectW'],a['rectH']
  l,b,r,t,angle=projected(self.ending,f,a,f['layout'][0],(w/4,h/4,w*3/4,h*3/4),(w,h))
  l0,b0,r0,t0,_=projected(self.ending,f,a,f['layout'][0],(0,0,w,h),(w,h))
  self.assertAlmostEqual(r-l,(r0-l0)/2);self.assertAlmostEqual(t-b,(t0-b0)/2)
  self.assertAlmostEqual(l+r,l0+r0);self.assertAlmostEqual(b+t,b0+t0)
if __name__=='__main__':unittest.main()
