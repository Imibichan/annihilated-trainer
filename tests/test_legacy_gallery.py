"""The migration CLI restores only verified, owned title/catalog pairs."""
from pathlib import Path
import contextlib
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import legacy_gallery as migration

AA = Path('Annihilated_Data/StreamingAssets/aa')
TITLE = AA / 'StandaloneWindows64/naninovelstartupui_assets_all_3b70a54d9568632d966864a781231a5e.bundle'
FILES = (TITLE, AA/'catalog.bin')
STATE = '.annihilated-cg-gallery'

def registered_catalog():
    """A minimal real Addressables local-provider record, with no game assets."""
    data=bytearray(16)
    def string(value):
        encoded=value.encode()
        data.extend(struct.pack('<I',len(encoded)))
        offset=len(data)
        data.extend(encoded)
        return offset
    suffix=string('AssetBundleProvider')
    node=len(data)
    data.extend(struct.pack('<II',suffix,0xffffffff))
    name=string(TITLE.name)
    location=string('{UnityEngine.AddressableAssets.Addressables.RuntimePath}/StandaloneWindows64/'+TITLE.name)
    data.extend(struct.pack('<III',name,location,0x40000000|node))
    return bytes(data)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.game = (Path(temp.name)/'游戏 游戏').resolve()
        (self.game/TITLE).parent.mkdir(parents=True)
        (self.game/'Annihilated.exe').write_bytes(b'fixture')
        self.state = self.game/STATE
        self.state.mkdir()
        catalog=registered_catalog()
        self.stage_files([b'local patched title',catalog+b'patched'], [b'local original title',catalog])

    def stage_files(self, patched, originals):
        rows = []
        for index, name in enumerate(FILES):
            (self.game/name).write_bytes(patched[index])
            (self.state/f'original-{index}.bin').write_bytes(originals[index])
            rows.append(dict(path=name.as_posix(),original=hashlib.sha256(originals[index]).hexdigest(),
                             patched=hashlib.sha256(patched[index]).hexdigest()))
        self.manifest = dict(schema=1,phase='enabled',files=rows,version={},revision=90)
        self.save_manifest()

    def save_manifest(self):
        (self.state/'manifest.json').write_text(json.dumps(self.manifest),encoding='utf8')

    def call(self, verb, code, prefix=None):
        stdout,stderr = io.StringIO(),io.StringIO()
        with contextlib.redirect_stderr(stderr),contextlib.redirect_stdout(stdout):
            self.assertEqual(migration.main([verb,str(self.game)]),code)
        if prefix:
            self.assertTrue(stderr.getvalue().startswith(prefix),stderr.getvalue())
        return stderr.getvalue()

    def hashes(self):
        return [hashlib.sha256((self.game/p).read_bytes()).hexdigest() for p in FILES]

    @unittest.skipUnless(os.getenv('V15_LEGACY_STOCK') and os.getenv('V15_LEGACY_ENABLED'),
                         'requires an original stock game and locally installed published V1.4 gallery')
    def test_actual_published_pair_restores_to_stock(self):
        stock = Path(os.environ['V15_LEGACY_STOCK'])
        live = Path(os.environ['V15_LEGACY_ENABLED'])
        before = [hashlib.sha256((live/p).read_bytes()).hexdigest() for p in FILES]
        self.assertEqual(before[0],migration.PUBLISHED_TITLE)
        self.stage_files([(live/p).read_bytes() for p in FILES],[(stock/p).read_bytes() for p in FILES])
        self.call('status',0)
        self.call('disable',0)
        self.call('status',10)
        self.call('disable',0)
        self.assertEqual(self.hashes(),[r['original'] for r in self.manifest['files']])
        self.assertEqual([hashlib.sha256((live/p).read_bytes()).hexdigest() for p in FILES], before)
        shutil.rmtree(self.state)
        self.call('status',10)
        self.call('disable',0)
        self.assertFalse(self.state.exists())

    def test_mixed_previous_entries_are_recovered_without_patched_cache(self):
        self.manifest['phase']='enabling'
        self.manifest.pop('revision')
        self.manifest['files'][0]['previous']=hashlib.sha256(b'previous').hexdigest()
        self.save_manifest()
        (self.game/TITLE).write_bytes(b'previous')
        self.call('status',1,'RECOVERY_REQUIRED ')
        self.call('disable',0)
        self.call('status',10)

    def test_missing_backup_or_unknown_live_file_keeps_everything(self):
        first=self.hashes()
        (self.state/'original-0.bin').unlink()
        message=self.call('disable',1)
        self.assertIn('备份',message)
        self.assertEqual(self.hashes(),first)
        (self.game/TITLE).write_bytes(b'foreign')
        second=self.hashes()
        self.call('disable',1)
        self.assertEqual(self.hashes(),second)

    def test_ordinary_failure_rolls_back_entire_installed_pair(self):
        before=self.hashes()
        rename=os.replace
        def fail(source,dest):
            if Path(dest) == self.game/FILES[1]:
                raise PermissionError('busy')
            return rename(source,dest)
        with patch.object(os,'replace',side_effect=fail):
            self.call('disable',1)
        self.assertEqual(self.hashes(),before)
        self.call('status',0)

    def test_manifest_cannot_redirect_a_restore_to_another_file(self):
        self.manifest['files'][0]['path']='Annihilated.exe'
        self.save_manifest()
        before=self.hashes()
        self.call('disable',1)
        self.assertEqual((self.game/'Annihilated.exe').read_bytes(),b'fixture')
        self.assertEqual(self.hashes(),before)

    def test_no_enable_verb_or_unowned_restore(self):
        self.call('enable',1)
        shutil.rmtree(self.state)
        before=self.hashes()
        self.call('disable',1)
        self.assertEqual(before,self.hashes())
        self.assertFalse(self.state.exists())

    def test_forced_interruption_reports_recovery_then_restores_originals(self):
        rename=os.replace
        def interrupt(source,dest):
            if Path(dest)==self.game/FILES[1]:
                raise KeyboardInterrupt
            return rename(source,dest)
        with patch.object(os,'replace',side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.call('disable',0)
        mixed=self.hashes()
        self.call('status',1,'RECOVERY_REQUIRED ')
        self.assertEqual(self.hashes(),mixed)
        self.call('disable',0)
        self.assertEqual(self.hashes(),[r['original'] for r in self.manifest['files']])

if __name__=='__main__':
    unittest.main()
