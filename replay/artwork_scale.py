"""Fit native independent artwork to the replay camera, preserving localized framing."""
import math


def contain_scale(asset, authored_limit=None, aspect=16 / 9):
    # Fixed 3-degree vertical field of view, camera at -100, background at -16.
    height = 2 * (100 - 16) * math.tan(math.radians(3 / 2))
    geometries = [asset]
    if asset.get('localizedGeometry'):
        geometries.append(asset['localizedGeometry'])
    limits = []
    for geometry in geometries:
        width, sprite_height = geometry['rectW'], geometry['rectH']
        if width <= 0 or sprite_height <= 0 or aspect <= 0:
            raise ValueError('Invalid illustration geometry')
        # Stock Naninovel background actors display 100 pixels per world unit.
        limits.append(.96 * min(height * aspect * 100 / width, height * 100 / sprite_height))
    if authored_limit is not None and authored_limit > 0:
        limits.append(authored_limit)
    return min(limits)
