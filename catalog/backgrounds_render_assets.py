"""Build the scenery renderer's numeric index from the player's original Unity files."""
import argparse
import json
import sys
import re
import struct
from functools import lru_cache
from pathlib import Path

from addressables import address_paths, bundle_locations
from backgrounds import BG_PREFIXES
from inspect_game import installed_resource_entries


def actor_geometry(data_folder, unity):
    manager = unity.load(str(data_folder / 'globalgamemanagers'))
    names = installed_resource_entries(manager, 'naninovel/configuration/backgroundsconfiguration')
    oid = next(ptr['m_PathID'] for k, ptr in names if k == 'naninovel/configuration/backgroundsconfiguration')
    env = unity.load(str(data_folder / 'resources.assets'))
    data = next(o for o in env.objects if o.path_id == oid).get_raw_data()
    # ActorMetadata.Guid is a Unity string followed by its managed-reference ID.
    # OrthoActorMetadata then serializes the normalized pivot and PixelsPerUnit.
    guids = list(re.finditer(rb'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', data))
    if len(guids) < 2: raise ValueError('Missing background actor metadata')
    count = len(guids) - 1
    # First entry is the default metadata. The actor-ID array precedes the per-actor entries.
    # Read actual array order; MainBackground need not be its first key.
    candidates = []
    for pos in range(guids[0].end(), guids[1].start() - 4, 4):
        if struct.unpack_from('<I', data, pos)[0] != count: continue
        actors = []
        p = pos + 4
        for _ in range(count):
            if p + 4 > guids[1].start(): break
            n = struct.unpack_from('<I', data, p)[0]
            label = data[p + 4:p + 4 + n]
            if not 0 < n < 256 or not re.fullmatch(rb'[\w.-]+', label): break
            actors.append(label.decode('ascii'))
            p += 4 + ((n + 3) & ~3)
        if len(set(actors)) == count and 'MainBackground' in actors and struct.unpack_from('<I', data,
                                                                                           p)[0] == count:
            candidates.append(actors)
    if len(candidates) != 1: raise ValueError('Unrecognized background actor metadata map')
    return {
        actor: list(struct.unpack_from('<fff', data,
                                       guid.end() + 8))
        for actor, guid in zip(candidates[0], guids[1:])
    }


def build(game, stage, catalog, reader_path=None, *, bundle_sources=None):
    if reader_path:
        sys.path.insert(0, str(reader_path.resolve()))
    import UnityPy
    aa = game / 'Annihilated_Data/StreamingAssets/aa'
    bundles = aa / 'StandaloneWindows64'
    original = stage / 'catalog-stock.bin'
    raw = (original if original.exists() else aa / 'catalog.bin').read_bytes()
    aliases = address_paths(raw, BG_PREFIXES)
    allowed_prefabs = address_paths(raw, ('Naninovel/Backgrounds/', ), path_suffix='.prefab')
    data = catalog if isinstance(catalog, dict) else json.loads(catalog.read_text(encoding='utf8'))
    rooms = list(data['titleBackgrounds'].values())
    rooms.extend(frame['background'] for scene in data['scenes'] for frame in scene['frames'])
    needed = {layer['actor'] + '/' + layer['appearance'] for r in rooms for layer in r['layers']}
    images = json.loads((stage / 'images.json').read_text(encoding='utf8'))
    texture_refs = {path: [b, oid] for b, path, k, oid, *_ in images if k == 'Texture2D'}
    textures = {name: texture_refs[aliases['Naninovel/Backgrounds/' + name]] for name in sorted(needed)}
    prefab_paths = {
        path
        for path in allowed_prefabs.values() if Path(path).stem in {r['prefab']
                                                                    for r in rooms}
    }
    prefabs = {}
    file_map = stage / 'bundle-files.json'
    active_files = json.loads(file_map.read_bytes()) if file_map.is_file() else {}

    @lru_cache(maxsize=3)
    def external_file(cab):
        owner = active_files.get(cab)
        if owner is None: raise ValueError(f'Cannot resolve active prefab dependency {cab}')
        env = UnityPy.load(str((bundle_sources or {}).get(owner, bundles / owner)))
        file = next((obj.assets_file for obj in env.objects if obj.assets_file.name == cab), None)
        if file is None: raise ValueError(f'Missing serialized dependency {cab} in {owner}')
        return owner, file

    def resolve(file, current_bundle, file_id, oid):
        if file_id:
            cab = file.externals[file_id - 1].path.rsplit('/', 1)[-1]
            current_bundle, file = external_file(cab)
        return current_bundle, file.objects[oid]

    for name in bundle_locations(raw):
        path_on_disk = (bundle_sources or {}).get(name, bundles / name)
        env = UnityPy.load(str(path_on_disk))
        for path, ptr in env.container.items():
            if path not in prefab_paths or not ptr.path_id or ptr.type.name != 'GameObject':
                continue
            file = ptr.deref().assets_file
            planes = []

            def visit(go, parents):
                tree = go.read_typetree()
                if not tree['m_IsActive']: return
                components = [file.objects[c['component']['m_PathID']] for c in tree['m_Component']]
                trans = components[0].read_typetree()
                xyz = lambda key: [trans[key][k] for k in 'xyz']
                quat = [trans['m_LocalRotation'][k] for k in 'xyzw']
                chain = parents + [[xyz('m_LocalPosition'), quat, xyz('m_LocalScale')]]
                for comp in components[1:]:
                    if comp.type.name != 'SpriteRenderer': continue
                    render = comp.read_typetree()
                    if not render['m_Enabled']: continue
                    spr_ref = render['m_Sprite']
                    if not spr_ref['m_PathID']: continue
                    sprite_owner, sprite_obj = resolve(file, name, spr_ref['m_FileID'], spr_ref['m_PathID'])
                    sprite = sprite_obj.read()
                    rd = sprite.m_RD
                    texture_owner, tex = resolve(sprite_obj.assets_file, sprite_owner, rd.texture.m_FileID,
                                                 rd.texture.m_PathID)
                    if tex.type.name != 'Texture2D':
                        raise ValueError(f'Invalid prefab sprite texture in {path}')
                    rect = [getattr(sprite.m_Rect, k) for k in ('x', 'y', 'width', 'height')]
                    planes.append({
                        'name': tree['m_Name'],
                        'texture': [texture_owner, tex.path_id],
                        'transforms': chain,
                        'rect': rect,
                        'pivot': [sprite.m_Pivot.x, sprite.m_Pivot.y],
                        'units': sprite.m_PixelsToUnits,
                        'sort': render['m_SortingOrder'],
                        'tint': [render['m_Color'][k] for k in 'rgba'],
                        'flip': [render['m_FlipX'], render['m_FlipY']]
                    })
                for child in trans['m_Children']:
                    child_go = file.objects[child['m_PathID']].read_typetree()['m_GameObject']['m_PathID']
                    visit(file.objects[child_go], chain)

            visit(ptr.deref(), [])
            prefabs[Path(path).stem] = planes
    if {Path(path).stem for path in prefab_paths} != set(prefabs):
        raise ValueError('Missing a required scenery prefab')
    return {
        'layers': textures,
        'prefabs': prefabs,
        'actors': actor_geometry(game / 'Annihilated_Data', UnityPy)
    }


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'stage', 'catalog', 'output'):
        p.add_argument(name, type=Path)
    p.add_argument('--reader-path', type=Path)
    args = p.parse_args()
    index = build(args.game, args.stage, args.catalog, args.reader_path)
    args.output.write_text(json.dumps(index, sort_keys=True, separators=(',', ':')), encoding='utf8')
    print(len(index['layers']), 'named layers,', len(index['prefabs']), 'prefabs,',
          sum(map(len, index['prefabs'].values())), 'prefab sprites')
