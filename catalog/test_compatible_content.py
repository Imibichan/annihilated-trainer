"""Compatibility checks exercise identities, resource origins and local text offsets."""
import copy
import json
import hashlib
import struct
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from compatible_content import validate_content, validate_local_text
from addressables import bundle_locations
from backgrounds_render import BackgroundRenderer
from build_catalog import catalog_identity, Library


class ContentCompatibilityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(Path(__file__).with_name('gallery.json').read_bytes())
        cls.rooms = json.loads(Path(__file__).with_name('backgrounds_assets.json').read_bytes())

    def test_structural_checks_accept_original_without_hardcoded_version(self):
        validate_content(self.index, self.rooms)

    def test_missing_external_hash_uses_supplied_original_catalog(self):
        with TemporaryDirectory() as folder:
            marker = Path(folder) / 'catalog.hash'
            self.assertEqual(catalog_identity(marker, b'updated'),
                             'sha256:' + hashlib.sha256(b'updated').hexdigest())
            marker.write_text('changed-version', encoding='utf8')
            self.assertEqual(catalog_identity(marker, b'updated'), 'changed-version')

    def test_updated_translation_image_is_selected_by_current_resource_name(self):
        original = 'Naninovel/Backgrounds/MainBackground/CG/new-art'
        cn = original.replace('Naninovel/', 'Naninovel/Localization/zh-CN/', 1)
        images = [['current.bundle', 'Assets/new-art.png', 'Texture2D', 84]]
        known = {original: images[0][1]}
        self.assertEqual(Library(images, known, {cn.lower()}).assets[0]['resource'], cn)
        self.assertNotIn('resource', Library(images, known).assets[0])

    def test_inconsistent_floor_and_branch_do_not_produce_partial_gallery(self):
        rooms = {**self.rooms, 'prefabs': dict(self.rooms['prefabs'])}
        del rooms['prefabs']['stairs']
        with self.assertRaisesRegex(ValueError, 'stairs'):
            validate_content(self.index, rooms)
        ix = copy.deepcopy(self.index)
        choice = next(s for s in ix['scenes'] if s.get('branches'))['branches'][0]
        choice['sceneId'] = 'removed-scene'
        with self.assertRaisesRegex(ValueError, 'removed-scene'):
            validate_content(ix, self.rooms)

    def test_missing_dialogue_and_empty_index_fail(self):
        with self.assertRaises(ValueError):
            validate_content({**self.index, 'scenes': []}, self.rooms)
        ix = copy.deepcopy(self.index)
        for s in ix['scenes']:
            for f in s['frames']:
                f['lines'] = []
        with self.assertRaises(ValueError):
            validate_content(ix, self.rooms)

    def test_actor_geometry_is_injected_per_installation(self):
        from unittest.mock import patch
        with patch.dict('sys.modules', UnityPy=object()):
            renderer = BackgroundRenderer(Path.cwd(), index=self.rooms)
            self.assertIs(renderer.index, self.rooms)

    def test_only_active_bundle_provider_records_count(self):
        data = bytearray(b'\0' * 12)

        def string(value):
            data.extend(struct.pack('<I', len(value)))
            ptr = len(data)
            data.extend(value)
            return ptr

        suffix = string(b'AssetBundleProvider')
        joined = 0x40000000 | len(data)
        data.extend(struct.pack('<II', suffix, 0xffffffff))
        string(b'obsolete_abcd.bundle')
        address = string(b'current_9876.bundle')
        location = string(
            rb'{UnityEngine.AddressableAssets.Addressables.RuntimePath}\StandaloneWindows64\current_9876.bundle'
        )
        record = struct.pack('<III', address, location, joined)
        data.extend(record)
        self.assertEqual(bundle_locations(data), ('current_9876.bundle', ))
        data.extend(record)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            bundle_locations(data)

    def test_verified_current_localized_spans_follow_moved_text(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            physical = root / 'resources.assets'
            raw = '勇者说。'.encode('utf8')
            physical.write_bytes(b'\0' * 64 + raw)
            table = root / 'zh.json'
            table.write_text(json.dumps({'scenario': [[1, 'GenericText', '', '勇者说。', 64]]}), encoding='utf8')
            validate_local_text({(64, 6)}, physical, table)
            with self.assertRaises(ValueError):
                validate_local_text({(48, 6)}, physical, table)
            with self.assertRaises(ValueError):
                validate_local_text({(64, len(raw) + 1)}, physical, table)
