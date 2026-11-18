"""Compose original room textures and prefab sprites locally using the game's static camera."""
import json
from functools import lru_cache
import math
from pathlib import Path
import sys


def world_position(x, y, z):
    return ((x - 50) * .192, (y - 50) * .108, z)


def multiply(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def apply(matrix, vec):
    return tuple(sum(a * b for a, b in zip(row, vec)) for row in matrix)


def euler(r):
    # Unity's authored Euler order is Z, X, Y.
    x, y, z = map(math.radians, r)
    cx, cy, cz = map(math.cos, (x, y, z))
    sx, sy, sz = map(math.sin, (x, y, z))
    return multiply(((cy, 0, sy), (0, 1, 0), (-sy, 0, cy)),
                    multiply(((1, 0, 0), (0, cx, -sx), (0, sx, cx)), ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))))


def camera_space(point, camera):
    position, rotation = camera
    return apply(zip(*euler(rotation)), [v - u for v, u in zip(point, position)])


def project(point, camera, size):
    x, y, z = camera_space(point, camera)
    f = size[1] / (2 * math.tan(math.radians(1.5)))
    return (size[0] / 2 + f * x / z, size[1] / 2 - f * y / z)


def effective_camera(frame):
    camera = frame.get('camera', {})
    xyz = camera.get(camera.get('positionMode', 'offset'), (0, 0, -100))
    if any(p['z'] - xyz[2] < 1 for p in frame.get('layout', [])):
        return ((0, 0, -100), (0, 0, 0))
    return tuple(xyz), tuple(camera.get('rotation', (0, 0, 0)))


def quaternion(q):
    x, y, z, w = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w),
             2 * (x * z + y * w)), (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def invert(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    # Inverse homographies can be normalized by the bottom-right cofactor.
    adj = ((e * i - f * h, c * h - b * i, b * f - c * e), (f * g - d * i, a * i - c * g, c * d - a * f),
           (d * h - e * g, b * g - a * h, a * e - b * d))
    divisor = adj[2][2]
    if abs(divisor) < 1e-18: return None
    return tuple(v / divisor for row in adj for v in row)[:8]


def composite_plane(canvas, image, world_at, camera):
    from PIL import Image, ImageDraw
    ow, oh = canvas.size
    iw, ih = image.size
    top_left = camera_space(world_at(0, 0), camera)
    px = camera_space(world_at(iw, 0), camera)
    py = camera_space(world_at(0, ih), camera)
    u = tuple((v - t) / iw for v, t in zip(px, top_left))
    v = tuple((v - t) / ih for v, t in zip(py, top_left))
    p11 = tuple(a + b - c for a, b, c in zip(px, py, top_left))
    perimeter = [top_left, px, p11, py]
    if max(q[2] for q in perimeter) <= .01: return
    focal = oh / (2 * math.tan(math.radians(1.5)))
    m = [[focal * q[0] + ow / 2 * q[2] for q in (u, v, top_left)],
         [-focal * q[1] + oh / 2 * q[2] for q in (u, v, top_left)], [q[2] for q in (u, v, top_left)]]
    inv = invert(m)
    if inv is None: return
    out = image.transform(canvas.size, Image.Transform.PERSPECTIVE, inv, resample=Image.Resampling.BILINEAR)
    if min(q[2] for q in perimeter) <= .01:
        # Tilted road planes can extend behind the eye. Clip the geometry to the front hemisphere.
        poly = []
        for a, b in zip(perimeter, perimeter[1:] + perimeter[:1]):
            if a[2] >= .01: poly.append(a)
            if (a[2] >= .01) != (b[2] >= .01):
                t = (.01 - a[2]) / (b[2] - a[2])
                poly.append(tuple(s + (v - s) * t for s, v in zip(a, b)))
        mask = Image.new('L', canvas.size)
        ImageDraw.Draw(mask).polygon([(ow / 2 + focal * x / z, oh / 2 - focal * y / z) for x, y, z in poly],
                                     fill=255)
        from PIL import ImageChops
        out.putalpha(ImageChops.multiply(out.getchannel('A'), mask))
    canvas.alpha_composite(out)


def tinted(image, color):
    if min(color) >= .9999: return image
    return image.point([round(i * max(0, min(value, 1))) for value in color for i in range(256)])


def sea_battle_flash(background, layer):
    return (background['prefab'] == 'sea' and layer['actor'] == 'ColorFlashBackground'
            and layer['appearance'] == 'darkblood' and layer['tint'] == '#FFFFFFAA'
            and min(layer['scaleX'], layer['scaleY']) >= 999999)


class BackgroundRenderer:

    def __init__(self, game, reader_path=None, *, index=None, bundle_sources=None):
        if reader_path:
            sys.path.insert(0, str(Path(reader_path).resolve()))
        import UnityPy
        self.reader = UnityPy
        self.folder = Path(game) / 'Annihilated_Data/StreamingAssets/aa/StandaloneWindows64'
        self.index = index if index is not None else json.loads(
            Path(__file__).with_name('backgrounds_assets.json').read_bytes())
        self.bundle_sources = bundle_sources or {}
        self.bundle = lru_cache(maxsize=1)(self._open)
        self.texture = lru_cache(maxsize=12)(self._texture)

    def _open(self, bundle):
        env = self.reader.load(str(self.bundle_sources.get(bundle, self.folder / bundle)))
        return next(obj.assets_file for obj in env.objects if obj.type.name == 'AssetBundle')

    def _texture(self, bundle, oid):
        return self.bundle(bundle).objects[oid].read().image.convert('RGBA')

    def close(self):
        self.texture.cache_clear()
        self.bundle.cache_clear()

    @staticmethod
    def key(frame):
        bg = frame['background']
        return (bg['prefab'], tuple(bg['prefabOffset']), json.dumps(bg['layers'], sort_keys=True),
                effective_camera(frame) if bg['layers'] or bg['prefab'] else None)

    def _room_plane(self, layer):
        texture = self.index['layers'][layer['actor'] + '/' + layer['appearance']]
        image = self.texture(*texture)
        tint = layer['tint'].lstrip('#')
        if len(tint) == 6: tint += 'FF'
        image = tinted(image, [int(tint[n:n + 2], 16) / 255 for n in range(0, 8, 2)])
        w, h = image.size
        center = world_position(layer['x'], layer['y'], layer['z'])
        rotation = euler([layer[k] for k in ('rotX', 'rotY', 'rotZ')])
        px, py, units = self.index['actors'][layer['actor']]

        def point(x, y):
            delta = apply(rotation, ((x - w * px) * layer['scaleX'] / units,
                                     (h * (1 - py) - y) * layer['scaleY'] / units, 0))
            return tuple(v + d for v, d in zip(center, delta))

        return image, point

    def _prefab_plane(self, plane, offset):
        source = self.texture(*plane['texture'])
        x, y, w, h = (round(v) for v in plane['rect'])
        top = source.height - y - h
        image = source if (x, top, w, h) == (0, 0, *source.size) else source.crop((x, top, x + w, top + h))
        image = tinted(image, plane['tint'])
        chain = [(pos, quaternion(q), scale) for pos, q, scale in reversed(plane['transforms'])]
        fx, fy = plane['flip']
        pivot_x, pivot_y = plane['pivot']

        def point(x, y):
            vec = ((x - w * pivot_x) / plane['units'] * (-1 if fx else 1),
                   (h * (1 - pivot_y) - y) / plane['units'] * (-1 if fy else 1), 0)
            for pos, rotation, scale in chain:
                rotated = apply(rotation, [a * b for a, b in zip(vec, scale)])
                vec = tuple(a + b for a, b in zip(pos, rotated))
            return tuple(a + b for a, b in zip(vec, offset))

        return image, point

    def render(self, frame, width=1280, height=720):
        from PIL import Image
        bg = frame['background']
        camera = effective_camera(frame)
        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 255))
        ordered = []
        for layer in bg['layers']:
            ordered.append((0, -layer['z'], self._room_plane, (layer, )))
        for plane in self.index['prefabs'].get(bg['prefab'], []):
            center_z = bg['prefabOffset'][2] + sum(p[0][2] for p in plane['transforms'])
            ordered.append((plane['sort'], -center_z, self._prefab_plane, (plane, bg['prefabOffset'])))
        for _, __, make, args in sorted(ordered, key=lambda row: row[:2]):
            if make == self._room_plane and sea_battle_flash(bg, args[0]):
                # Ratios measured against the game's otherwise unobstructed 960x540 room.
                # The original material grades the underwater shot more subtly than alpha
                # compositing the raw 1x1 magenta texture onto the already-rendered room.
                canvas = tinted(canvas, (.816, .780, .778, 1))
                continue
            image, world = make(*args)
            composite_plane(canvas, image, world, camera)
        return canvas
