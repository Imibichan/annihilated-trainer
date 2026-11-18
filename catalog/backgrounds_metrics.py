"""Inspect sprite framing from the player's installed textures; export numbers only."""
import argparse
import collections
import json
import sys
from pathlib import Path


def sprite_values(sprite):
    rect = sprite.m_Rect
    return {
        'rectW': int(rect.width),
        'rectH': int(rect.height),
        'pixelsPerUnit': float(sprite.m_PixelsToUnits),
        'pivotX': float(sprite.m_Pivot.x),
        'pivotY': float(sprite.m_Pivot.y)
    }


def extract(game, stage, reader_path=None, *, bundle_sources=None):
    if reader_path: sys.path.insert(0, str(reader_path.resolve()))
    import UnityPy
    data = game / 'Annihilated_Data'
    bundles = data / 'StreamingAssets/aa/StandaloneWindows64'
    groups = collections.defaultdict(set)
    from addressables import address_paths
    from inspect_game import installed_resource_entries
    source = stage / 'catalog-stock.bin'
    if not source.is_file(): source = data / 'StreamingAssets/aa/catalog.bin'
    aliases = address_paths(source.read_bytes())
    needed = set(aliases.values())
    actor_for = {path: key.split('/')[2] for key, path in aliases.items()}
    geometry = None

    def texture_geometry(width, height, actor):
        nonlocal geometry
        if geometry is None:
            from backgrounds_render_assets import actor_geometry
            geometry = actor_geometry(data, UnityPy)
        px, py, ppu = geometry[actor]
        return {'rectW': width, 'rectH': height, 'pixelsPerUnit': ppu, 'pivotX': px, 'pivotY': py}

    images = json.loads((stage / 'images.json').read_text(encoding='utf8'))
    for b, path, kind, *details in images:
        if kind == 'Texture2D' and path in needed: groups[b].add(path)
    result = {}
    for bundle, files in groups.items():
        env = UnityPy.load(str((bundle_sources or {}).get(bundle, bundles / bundle)))
        samples = collections.defaultdict(list)
        textures = {}
        for path, ptr in env.container.items():
            if path not in files: continue
            if ptr.type.name == 'Texture2D':
                tex = ptr.read()
                textures[path] = (int(tex.m_Width), int(tex.m_Height))
            elif ptr.type.name == 'Sprite':
                spr = ptr.read()
                samples[path].append((spr.m_Name, sprite_values(spr)))
        for path, (w, h) in textures.items():
            options = samples[path]
            full = [
                m for name, m in options if name == Path(path).stem or (m['rectW'] == w and m['rectH'] == h)
            ]
            if full:
                values = dict(full[0], geometry='sprite')
            elif options:
                # Naninovel backgrounds resolve the Texture2D, even for a source image with
                # several imported sub-sprites. Never use a random fragment as its extents.
                units = {v['pixelsPerUnit'] for _, v in options}
                if len(units) != 1: raise ValueError((path, units))
                values = dict(rectW=w,
                              rectH=h,
                              pixelsPerUnit=units.pop(),
                              pivotX=.5,
                              pivotY=.5,
                              geometry='texture')
            else:
                values = dict(texture_geometry(w, h, actor_for[path]), geometry='texture')
            result[path] = dict(values, textureW=w, textureH=h)
    # Localized title cards are distinct resources. Preserve their own sprite metadata.
    mgr = UnityPy.load(str(data / 'globalgamemanagers'))
    resources = UnityPy.load(str(data / 'resources.assets'))
    objs = {o.path_id: o for o in resources.objects}
    extra = {}
    prefix = 'naninovel/localization/zh-cn/backgrounds/'
    actor_names = {key.split('/')[2].lower(): key.split('/')[2] for key in aliases}
    for key, pointer in installed_resource_entries(
            mgr, (prefix + 'mainbackground/cg/', prefix + 'optionalcgbackground')):
        obj = objs[pointer['m_PathID']]
        if obj.type.name == 'Sprite': extra[key] = sprite_values(obj.read())
        elif obj.type.name == 'Texture2D' and key not in extra:
            actor = actor_names.get(key[len(prefix):].split('/')[0])
            if actor:
                tex = obj.read()
                extra[key] = texture_geometry(tex.m_Width, tex.m_Height, actor)
    (stage / 'sprite-metrics.json').write_text(json.dumps({
        'assets': result,
        'localized': extra
    }),
                                               encoding='utf8')
    print(f'{len(result)} source textures, {len(extra)} localized sprites')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'stage'):
        p.add_argument(key, type=Path)
    p.add_argument('--reader-path', type=Path)
    extract(**vars(p.parse_args()))
