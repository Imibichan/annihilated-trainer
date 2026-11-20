"""Integration test with the installed Unity asset reader and an original game fixture."""
from pathlib import Path
import hashlib
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from replay import script_assets
import UnityPy
import catalog_crc

STOCK=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(r'C:/Users/Administrator/Documents/Codex/2026-11-18/v1-3/.work/scene-fix/stock-fresh')
AA=Path('Annihilated_Data/StreamingAssets/aa')

class NativeRoundtrip(unittest.TestCase):
    def test_native_playback_graph_and_catalog(self):
        bundle=next((STOCK/AA/'StandaloneWindows64').glob('naninovel_assets_naninovel*'))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1],prefix='native-roundtrip-') as tmp:
            target=Path(tmp)
            (target/AA/'StandaloneWindows64').mkdir(parents=True)
            shutil.copyfile(STOCK/AA/'catalog.bin', target/AA/'catalog.bin')
            old_catalog=(target/AA/'catalog.bin').read_bytes()
            edits={'Test2': dict(enumerate(['# Menu','@choice "返回目录" goto:.Menu if:G_mark==2','@set G_mark=2;x="a b"','@gosub First.InitialSettings','@goto .Menu if:x=="a b"','@hideUI TitleUI','@clearChoice *','@back "CG/sample" id:MainBackground scale:0.3 pos:50,50,10 time:0','@wait i','@hidePrinter','@stop','@title',('First',0),'@set x="{temp} if:literal {temp}" if:{key}Value>0'])), 'First':{0:'@goto Test2.Menu'}}
            edits['Test2'][14] = '@storeEnemyNextActionSet enemyId:1 actionSetName:"dropoutGrandAttackVsMage"'
            edits['Test2'][15] = '@storeEnemyNextActionSet enemyId:{v15WarriorEnemy} actionSetName:"warriorFinalBerserkStrength"'
            result=script_assets.patch_scripts(STOCK,target,edits)
            blob=(target/AA/'catalog.bin').read_bytes()
            out=target/AA/'StandaloneWindows64'/bundle.name
            with out.open('rb') as stream:
                env=UnityPy.load(stream)
                t=env.assets[0].container['Assets/Novel/Test2.nani'].deref().read_typetree()
            by_id={r['rid']:r for r in t['references']['RefIds']}
            rows=[by_id[r['rid']] for r in t['lines']]
            cmds=[by_id[r['data']['command']['rid']] if 'command' in r['data'] else None for r in rows]
            data=[c['data'] if c else {} for c in cmds]
            self.assertEqual(len(rows),16)
            self.assertEqual(rows[0]['data']['labelText'],'Menu')
            self.assertEqual(data[1]['ChoiceSummary']['value'],'返回目录')
            self.assertEqual(data[1]['GotoPath']['value']['value']['value'],'Menu')
            self.assertEqual(data[1]['ConditionalExpression']['value'],'G_mark==2')
            self.assertEqual(data[1]['IsTrans']['value'],0)
            self.assertEqual(data[2]['Expression']['value'],'G_mark=2;x="a b"')
            self.assertEqual(data[3]['Path']['value']['name']['value'],'First')
            self.assertEqual(data[4]['ConditionalExpression']['value'],'x=="a b"')
            self.assertEqual(data[5]['UINames']['value'][0]['value'],'TitleUI')
            self.assertEqual(data[7]['AppearanceAndTransition']['value']['name']['value'],'CG/sample')
            self.assertEqual([v['value'] for v in data[7]['ScenePosition']['value']],[50.0,50.0,10.0])
            self.assertEqual(data[8]['WaitMode']['value'],'i')
            self.assertEqual(cmds[12]['type']['class'],'OnNovelTopForDontReleaseNovel')
            expr=data[13]['Expression']['dynamicValue']
            cond=data[13]['ConditionalExpression']['dynamicValue']
            self.assertEqual(expr['ValueText'],'x="{temp} if:literal {temp}"')
            self.assertEqual(expr['Expressions'],['{temp}','{temp}'])
            self.assertEqual(cond['ValueText'],'{key}Value>0')
            self.assertEqual(expr['PlaybackSpot']['lineIndex'],13)
            self.assertEqual(expr['PlaybackSpot']['scriptName'],'Test2')
            self.assertEqual(data[14]['EnemyId']['value'],1)
            self.assertEqual(data[14]['EnemyId']['dynamicValue']['Expressions'],[])
            self.assertEqual(data[14]['ActionSetName']['value'],'dropoutGrandAttackVsMage')
            self.assertEqual(data[15]['EnemyId']['dynamicValue']['Expressions'],['{v15WarriorEnemy}'])
            self.assertEqual(data[15]['EnemyId']['dynamicValue']['PlaybackSpot']['lineIndex'],15)
            self.assertEqual([d['playbackSpot']['lineIndex'] for d in data[1:]],list(range(1,16)))
            self.assertTrue(all(d['playbackSpot']['scriptName']=='Test2' for d in data[1:]))
            first_orig=script_assets.read_script_rows(STOCK)['First']
            first_dst=script_assets.read_script_rows(target)['First']
            self.assertEqual([r[:3] for r in first_orig],[r[:3] for r in first_dst])
            self.assertEqual([r[3] for r in first_orig[1:]],[r[3] for r in first_dst[1:]])
            crc=0
            for f in env.file.files.values():
                crc=zlib.crc32(getattr(f,'reader',f).view,crc)
            offset=catalog_crc._record(blob,out,(crc,out.stat().st_size))
            self.assertEqual((crc,out.stat().st_size),struct.unpack_from('<II',blob,offset))
            self.assertEqual(old_catalog[:offset]+old_catalog[offset+8:],blob[:offset]+blob[offset+8:])
            self.assertEqual(result['crc'],crc)
            self.assertEqual((STOCK/AA/'catalog.bin').read_bytes(),old_catalog)
            print(f'Roundtrip {len(rows)} generated rows, untouched {len(first_orig)-1} stock rows; CRC={crc:08x}, size={out.stat().st_size}')

if __name__=='__main__':
    unittest.main()
