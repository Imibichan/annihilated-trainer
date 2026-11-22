"""Keep stable gallery IDs and artwork geometry. Native source rows are resolved at launch."""


def make_replay_index(gallery):
    scenes = []
    artwork_asset_ids = set()
    for original in gallery['scenes']:
        row = {key: original[key] for key in ('id', 'source', 'label', 'line')}
        if row['source'] == 'Ending':
            row['storyOrigins'] = [{k: origin[k] for k in ('source', 'line')}
                                   for origin in original.get('storyOrigins', [])]
        if row['source'] == 'Extras':
            if len(original['frames']) != 1:
                raise ValueError(f"独立画稿 {row['id']} 的画面数量有变化")
            frame = original['frames'][0]
            display = {k: frame[k] for k in ('layers', 'bindings', 'layers2', 'bindings2') if k in frame}
            artwork_asset_ids.update(display['layers'])
            artwork_asset_ids.update(display.get('layers2', ()))
            row.update(title=original['title'], type=original['type'], frames=[display])
        scenes.append(row)

    assets = []
    for original in gallery['assets']:
        if original['id'] in artwork_asset_ids:
            geometry = {k: original[k] for k in ('id', 'rectW', 'rectH')}
            if original.get('localizedGeometry'):
                geometry['localizedGeometry'] = {k: original['localizedGeometry'][k] for k in ('rectW', 'rectH')}
            assets.append(geometry)
    if {a['id'] for a in assets} != artwork_asset_ids:
        raise ValueError('原作独立画稿缺少显示尺寸')
    return {'assets': assets, 'scenes': scenes}
