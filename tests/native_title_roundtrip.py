"""Exercise the title fix on a fresh private game using the local installed game."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import UnityPy
import catalog_crc
from title_bindings import Prefab

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from replay.isolation import MARKER, prepare_copy
from replay.private_title import ensure_replay_title


class TitleRoundtrip(unittest.TestCase):
    def run_roundtrip(self, fallback):
        source = Path('G:/Steam/steamapps/common/Annihilated')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1],
                                         prefix='native-title-') as tmp:
            game = prepare_copy(source, Path(tmp) / 'private', stock_fallback=fallback).root
            aa = game / 'Annihilated_Data/StreamingAssets/aa'
            marker = json.loads((game / MARKER).read_bytes())
            bundle = game / marker["titleFile"]
            stock = hashlib.sha256(bundle.read_bytes()).hexdigest()
            blob = (aa/'catalog.bin').read_bytes()
            offset = catalog_crc.locate(blob,bundle)
            before = UnityPy.load(bundle.read_bytes())
            view = Prefab(before,game)
            unrelated = {key.path_id:hashlib.sha256(key.get_raw_data()).digest()
                         for key in view.file.objects.values()}
            root_id = view.root
            native_children = set(view.children(view.root))
            root_components = set(view.components(view.root))
            first = ensure_replay_title(source,game)
            self.assertTrue(first['changed'])
            self.assertEqual(stock, marker["sourceTitleSha256"])
            if marker["galleryBaseline"] == "installed":
                self.assertEqual(stock, hashlib.sha256((source / marker["titleFile"]).read_bytes()).hexdigest())
            fixed = UnityPy.load(bundle.read_bytes())
            v = Prefab(fixed,game)
            self.assertEqual(v.root,root_id)
            self.assertTrue(v.row(v.root)['m_IsActive'])
            self.assertTrue(all(not v.row(k)['m_IsActive'] for k in native_children))
            title = v.row(v.component(v.root,('Elringus.Naninovel.Runtime','Naninovel.UI.TitleMenu')))
            self.assertEqual(title['m_Enabled'],1)
            for key in ('modalUI','blockInputWhenVisible','focusMode'):
                self.assertEqual(title[key],0)
            self.assertEqual(title['focusObject']['m_PathID'],0)
            self.assertEqual(v.row(v.component(v.root,('UnityEngine.UI','UnityEngine.UI.GraphicRaycaster')))['m_Enabled'],0)
            self.assertEqual(v.row(v.component(v.root,'Canvas'))['m_Enabled'],0)
            self.assertEqual(set(unrelated),set(v.file.objects))
            for oid, digest in unrelated.items():
                if oid not in native_children | root_components:
                    self.assertEqual(hashlib.sha256(v.file.objects[oid].get_raw_data()).digest(),digest)
            out = (aa/'catalog.bin').read_bytes()
            self.assertEqual(catalog_crc.locate(out,bundle),offset)
            self.assertEqual(blob[:offset]+blob[offset+8:],out[:offset]+out[offset+8:])
            self.assertFalse(ensure_replay_title(source,game)['changed'])
            self.assertEqual(out,(aa/'catalog.bin').read_bytes())
            # A killed installer can have fully written the title while the old
            # catalog is still registered. Restarting must finish this commit.
            (aa/'catalog.bin').write_bytes(blob)
            self.assertTrue(ensure_replay_title(source,game)['changed'])
            self.assertEqual(out,(aa/'catalog.bin').read_bytes())
            print(f"Private TitleMenu remains active. Suppressed {len(native_children)} children. "
                  f"Verified {len(unrelated)-len(native_children)-len(root_components)} unrelated "
                  f"objects bytewise. CRC={first['crc']:08x}, size={first['size']}.")

    def test_installed_baseline(self):
        self.run_roundtrip(None)

    def test_current_game_supersedes_stale_fallback(self):
        self.run_roundtrip(Path(r'C:/Users/Administrator/Documents/Codex/2026-11-18/v1-3/.work/scene-fix/fixture-stock-build'))

if __name__=='__main__':
    unittest.main()
