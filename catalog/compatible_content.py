"""Re-index gallery content against the original files of a structurally compatible player."""
from bisect import bisect_right
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from addressables import bundle_locations
from backgrounds_render_assets import build as build_rooms
from build_catalog import build as build_gallery
from inspect_game import inspect

ROLES = {'Hero', 'Mage', 'Warrior', 'Priest'}


def validate_content(index, rooms, *, active_bundles=None):
    assets = index['assets']
    scenes = index['scenes']
    by_id = {s['id']: s for s in scenes}
    if not assets or not scenes or len(by_id) != len(scenes):
        raise ValueError('Empty or duplicate gallery scenes')
    if [a['id'] for a in assets] != list(range(len(assets))):
        raise ValueError('Non-contiguous gallery asset IDs')
    if len({a['path'] for a in assets}) != len(assets):
        raise ValueError('Duplicate gallery asset paths')
    if not ROLES.issubset(s['group'] for s in scenes):
        raise ValueError('Missing companion route')

    def bundle(name):
        if active_bundles is not None and name not in active_bundles:
            raise ValueError(f'Unregistered active bundle {name}')

    for a in assets:
        bundle(a['bundle'])
    size = index['resourcesSize']
    refs = set()

    def text_ref(ref):
        start, n = ref['offset'], ref['length']
        if ref['kind'] not in ('text', 'choice') or start < 0 or n <= 0 or start + n > size:
            raise ValueError(f'Invalid dialogue reference at {start}')
        refs.add((start, n))

    def room(bg):
        name = bg['prefab']
        if name and not rooms['prefabs'].get(name):
            raise ValueError(f'Missing scenery prefab {name}')
        for layer in bg['layers']:
            key = layer['actor'] + '/' + layer['appearance']
            if key not in rooms['layers'] or layer['actor'] not in rooms['actors']:
                raise ValueError(f'Missing scenery texture or actor {key}')

    def texture_pointer(ref):
        if len(ref) != 2 or not isinstance(ref[1], int) or not ref[1]:
            raise ValueError(f'Invalid scene texture pointer {ref!r}')
        bundle(ref[0])

    for ref in rooms['layers'].values():
        texture_pointer(ref)
    for planes in rooms['prefabs'].values():
        for p in planes:
            texture_pointer(p['texture'])
            if p['units'] <= 0 or min(p['rect'][2:]) <= 0:
                raise ValueError('Invalid scenery sprite dimensions')
    for actor, (x, y, ppu) in rooms['actors'].items():
        if not all(math.isfinite(v) for v in (x, y, ppu)) or ppu <= 0:
            raise ValueError(f'Invalid background actor geometry {actor}')
    for b in index['titleBackgrounds'].values():
        room(b)
    used = set()
    roles_with_text = set()
    link_count = 0
    for s in scenes:
        if not s['frames']: raise ValueError(f"Empty scene {s['id']}")
        if 'choice' in s: text_ref(s['choice'])
        if s.get('alsoGroups', []) and set(s['alsoGroups']) != set(s.get('alsoFrames', {})):
            raise ValueError(f"Invalid shared scene links in {s['id']}")
        for role, i in s.get('alsoFrames', {}).items():
            if role not in ROLES or not 0 <= i < len(s['frames']):
                raise ValueError(f"Invalid frame link in {s['id']}")
        for item in [s, *s['frames']]:
            for link in item.get('branches', []):
                dest = link['sceneId']
                if (dest not in by_id or dest == s['id'] or by_id[dest]['source'] != s['source']
                        or by_id[dest].get('choice') != link['choice']):
                    raise ValueError(f'Invalid branch destination {dest}')
                text_ref(link['choice'])
                link_count += 1
        for f in s['frames']:
            room(f['background'])
            for suffix in ('', '2'):
                ids = f.get('layers' + suffix, f['layers'])
                bindings = f.get('bindings' + suffix, f['bindings'])
                if not ids or len(ids) != len(bindings) or len(ids) != len(f['layout']):
                    raise ValueError(f"Incomplete image layers in {s['id']}")
                if any(not isinstance(i, int) or i < 0 or i >= len(assets) for i in ids):
                    raise ValueError(f"Unregistered foreground in {s['id']}")
                used.update(ids)
            for ref in f['lines']:
                text_ref(ref)
            if any(ref['kind'] == 'text' for ref in f['lines']): roles_with_text.add(s['group'])
    if not ROLES.issubset(roles_with_text) or not link_count:
        raise ValueError('Missing linked choices or localized companion dialogue')
    if used != {a['id'] for a in assets if a['kind'] != 'technical'}:
        raise ValueError('Incomplete gallery artwork coverage')
    return refs


def validate_local_text(refs, resources, table_path):
    table = json.loads(table_path.read_bytes())
    entries = {
        offset: text.encode('utf8')
        for rows in table.values()
        for _, kind, _, text, offset in rows if text and kind in ('GenericText', 'Command')
    }
    starts = sorted(entries)
    with resources.open('rb') as stream:
        for start, n in sorted(refs):
            i = bisect_right(starts, start) - 1
            if i < 0: raise ValueError(f'No original Simplified Chinese source at {start}')
            begin = starts[i]
            body = entries[begin][start - begin:start - begin + n]
            stream.seek(start)
            if len(body) != n or stream.read(n) != body or not body.decode('utf8').strip():
                raise ValueError(f'Original Simplified Chinese reference mismatch at {start}')


def prepare_content(game, stock_catalog_path, scratch, *, stock_title_path=None, stock_title_name=None):
    """Return only metadata. Full local scenario text stays in a per-invocation temporary directory."""
    game, stock, scratch = map(Path, (game, stock_catalog_path, scratch))
    scratch.mkdir(parents=True, exist_ok=True)
    active = set(bundle_locations(stock.read_bytes()))
    sources = {}
    if stock_title_path is not None:
        if stock_title_name is None:
            names = [name for name in active if name.startswith('naninovelstartupui_')]
            if len(names) != 1: raise ValueError('Cannot resolve the active original title bundle')
            stock_title_name = names[0]
        if stock_title_name not in active:
            raise ValueError(f'Unregistered original title bundle {stock_title_name}')
        sources[stock_title_name] = Path(stock_title_path).resolve(strict=True)
    with TemporaryDirectory(prefix='catalog-', dir=scratch) as folder:
        stage = Path(folder)
        inspect(game, stage, stock_catalog=stock, bundle_sources=sources)
        index, missing = build_gallery(game, stage)
        if missing: raise ValueError(f'Unsupported gallery appearance {sorted(missing)[0]}')
        rooms = build_rooms(game, stage, index, bundle_sources=sources)
        refs = validate_content(index, rooms, active_bundles=active)
        validate_local_text(refs, game / 'Annihilated_Data/resources.assets', stage / 'zh.json')
        # If a future release puts an illustration in the title bundle itself, subsequent decoding
        # must continue using its pristine copy during an update of an already installed gallery.
        used = {a['bundle'] for a in index['assets']}
        used.update(ref[0] for ref in rooms['layers'].values())
        used.update(p['texture'][0] for planes in rooms['prefabs'].values() for p in planes)
        if used.intersection(sources):
            index['_sourceBundles'] = {name: str(path) for name, path in sources.items() if name in used}
        return index, rooms
