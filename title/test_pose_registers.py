"""Source-cue regressions for branch merges and dynamic image choices."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"catalog"))
from build_catalog import Builder,merge_target,snapshot,apply_pose,forget_appearance

class PoseRegisters(unittest.TestCase):
 def test_rejoining_appearances_keep_shared_actor_pose_until_next_explicit_art(self):
  a=Builder.layer((1,1),-16.1);a.update(scale=.2,x=50,y=50)
  b=dict(a,pair=(2,2))
  carry={};merge_target(carry,'join',{'OptionalCGBackground':a});merge_target(carry,'join',{'OptionalCGBackground':b})
  merged=carry['join']['OptionalCGBackground']
  self.assertEqual((merged['scale'],merged['z']),(.2,-16.1))
  self.assertEqual(snapshot(carry['join']),[])
 def test_choice_actor_uses_literal_transform_from_the_native_command(self):
  v=Builder.layer((1,1),-16.4)
  apply_pose(v,{'pos':'50,46,-16.4','scale':'0.25','tint':'#FFFFFFFF'})
  self.assertEqual((v['scale'],v['x'],v['y'],v['z']),(.25,50.,46.,-16.4))
 def test_replacing_non_indexed_appearance_preserves_native_actor_transform(self):
  state={'MainBackground':Builder.layer((1,2),-16)}
  apply_pose(state['MainBackground'],{'pos':'50,46,-16','scale':'.4','tint':'#FFFFFF99'})
  forget_appearance(state,'MainBackground')
  self.assertEqual(snapshot(state),[])
  layer=state['MainBackground']
  layer.update(pair=(1,2),visible=True)
  apply_pose(layer,{'tint':'#FFFFFFCC'})
  self.assertEqual((layer['scale'],layer['y'],layer['opacity']),(.4,46,204))
if __name__=='__main__':unittest.main()
