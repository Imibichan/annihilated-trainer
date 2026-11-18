"""Inspect the local Unity resource containers and Naninovel source lines as data."""
import argparse
import gc
import json
import re
import struct
import sys
from pathlib import Path

LINE_TYPE = re.compile(
    rb'(GenericTextScriptLine|CommandScriptLine|LabelScriptLine|CommentScriptLine|EmptyScriptLine)\x00{0,3}\x09\x00\x00\x00Naninovel\x00{3}\x1a\x00\x00\x00Elringus\.Naninovel\.Runtime\x00\x00'
)
U32 = struct.Struct('<I')


def installed_resource_entries(manager, prefixes):
    resource_map = next(o for o in manager.objects if o.type.name == 'ResourceManager')
    for key, ptr in resource_map.read_typetree()['m_Container']:
        if not key.startswith(prefixes): continue
        file_id = ptr['m_FileID']
        if file_id < 1 or file_id > len(resource_map.assets_file.externals):
            raise ValueError(f'Invalid installed resource pointer {key}')
        location = resource_map.assets_file.externals[file_id - 1].path.replace('\\', '/').rsplit('/', 1)[-1]
        if location != 'resources.assets':
            raise ValueError(f'Unsupported localized resource container {location}')
        yield key, ptr


def read_lines(reader):
    raw = reader.get_raw_data()
    name_end = (32 + U32.unpack_from(raw, 28)[0] + 3) & ~3
    count = U32.unpack_from(raw, name_end)[0]
    expected_refs = struct.unpack_from(f'<{count}q', raw, name_end + 4)
    end_table = name_end + 4 + 8 * count
    rows = []
    for match in LINE_TYPE.finditer(raw, end_table):
        idx, n = struct.unpack_from('<II', raw, match.end())
        rid = struct.unpack_from('<q', raw, match.start() - 12)[0]
        if idx >= count or rid != expected_refs[idx]:
            continue
        h = match.end() + 8
        line = h + ((n + 3) & ~3)
        size = U32.unpack_from(raw, line)[0]
        pos = line + 4
        rows.append([
            idx, match[1].decode().removesuffix('ScriptLine'), raw[h:h + n].decode('ascii'),
            raw[pos:pos + size].decode('utf8'),
            int(reader.byte_start) + pos
        ])
    if [r[0] for r in rows] != list(range(count)):
        raise ValueError(f'Could not decode all {count} source lines for {reader.path_id} (read {len(rows)})')
    return rows


def inspect(game, stage, reader_path=None, stock_catalog=None, *, bundle_sources=None):
    if reader_path:
        sys.path.insert(0, str(Path(reader_path).resolve()))
    import UnityPy
    root = game / 'Annihilated_Data'
    aa = root / 'StreamingAssets' / 'aa'
    catalog = (stock_catalog or aa / 'catalog.bin').read_bytes()
    from addressables import address_paths, bundle_locations
    from backgrounds import BG_PREFIXES
    bundles = bundle_locations(catalog)
    bundle_sources = bundle_sources or {}
    stage.mkdir(parents=True, exist_ok=True)
    (stage / 'catalog-stock.bin').write_bytes(catalog)
    resman = UnityPy.load(str(root / 'globalgamemanagers'))
    resources = UnityPy.load(str(root / 'resources.assets'))
    resobjs = {o.path_id: o for o in resources.objects}
    res_file = (root / 'resources.assets').open('rb')
    translations = {}
    for key, ptr in installed_resource_entries(resman, 'naninovel/localization/zh-cn/scripts/'):
        rows = read_lines(resobjs[ptr['m_PathID']])
        for i, kind, h, text, offset in rows:
            if text:
                data = text.encode('utf8')
                res_file.seek(offset)
                if res_file.read(len(data)) != data:
                    raise ValueError(f'Physical text offset mismatch in {key} line {i}')
        translations[key.rsplit('/', 1)[1]] = rows
    res_file.close()
    (stage / 'zh.json').write_text(json.dumps(translations, ensure_ascii=False), encoding='utf8')
    del resources, resobjs, resman, translations
    gc.collect()
    scripts = {}
    assets = []
    serialized_files = {}
    required_paths = set(address_paths(catalog, BG_PREFIXES).values()) | set(address_paths(catalog).values())
    texture_owners = {}
    for bundle in bundles:
        path = bundle_sources.get(bundle, aa / 'StandaloneWindows64' / bundle)
        if not path.is_file(): raise FileNotFoundError(path)
        env = UnityPy.load(str(path))
        files = {o.assets_file.name for o in env.objects if o.type.name == 'AssetBundle'}
        if not files: raise ValueError(f'No AssetBundle object in active bundle {bundle}')
        for cab in files:
            previous = serialized_files.setdefault(cab, bundle)
            if previous != bundle: raise ValueError(f'Ambiguous active serialized file {cab}')
        for filename, ptr in env.container.items():
            if filename.endswith('.nani') and filename.startswith('Assets/Novel/'):
                key = Path(filename).stem
                if key in scripts: raise ValueError(f'Duplicate active source script {key}')
                scripts[key] = read_lines(ptr.deref())
            if ptr.path_id and Path(filename).suffix.lower() in ('.png', '.jpg', '.jpeg', '.psd', '.tga',
                                                                 '.tiff',
                                                                 '.bmp') and ptr.type.name in ('Texture2D',
                                                                                               'Sprite'):
                info = [bundle, filename, ptr.type.name, ptr.path_id]
                if ptr.type.name == 'Texture2D' and filename in required_paths:
                    owner = (bundle, ptr.path_id)
                    if texture_owners.setdefault(filename, owner) != owner:
                        raise ValueError(f'Ambiguous active texture {filename}')
                if ptr.type.name == 'Sprite' and ('/cg/' in filename.lower()
                                                  or 'optionalcgbackground' in filename.lower()):
                    sprite = ptr.read()
                    rect = sprite.m_Rect
                    info.extend([sprite.m_Name, [int(v) for v in (rect.x, rect.y, rect.width, rect.height)]])
                assets.append(info)
        del env
    (stage / 'scripts.json').write_text(json.dumps(scripts, ensure_ascii=False), encoding='utf8')
    (stage / 'images.json').write_text(json.dumps(assets, ensure_ascii=False), encoding='utf8')
    (stage / 'bundle-files.json').write_text(json.dumps(serialized_files), encoding='utf8')
    from backgrounds_metrics import extract
    extract(game, stage, Path(reader_path) if reader_path else None, bundle_sources=bundle_sources)
    print(f'{len(bundles)} bundles, {len(scripts)} source scripts, {len(assets)} image container entries')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('game', type=Path)
    ap.add_argument('stage', type=Path)
    ap.add_argument('--reader-path')
    ap.add_argument('--stock-catalog',
                    type=Path,
                    help='Optional original address catalog for a modded installation')
    inspect(**vars(ap.parse_args()))
