"""Draw gallery artwork only with ordinary title-canvas RawImages and local Unity textures."""
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import copy
import gc
import math
import sys

from build_title import active, event, ptr, rgba, xy
from scene_render import STILLS, contain_scale, fitted_rects, visible_fraction

ASPECT = 16 / 9
HEIGHT_FACTOR = 2 * math.tan(math.radians(1.5))


def camera_for(scene, frame):
    camera = frame["camera"]
    position = tuple(camera.get(camera.get("positionMode", "offset"), [0, 0, -100]))
    if ((scene["source"] in STILLS and len(frame["layers"]) == 1)
            or min(p["z"] for p in frame["layout"]) - position[2] < 1):
        return (0, 0, -100), (0, 0, 0)
    return position, camera["rotation"]


def projected(scene, frame, asset, pose, crop, size):
    """Convert Naninovel percent positions and the measured perspective to root-canvas anchors."""
    (cx, cy, cz), angles = camera_for(scene, frame)
    scale, angle, x, y, z = (pose[k] for k in ("scale", "rotation", "x", "y", "z"))
    if scene["source"] in STILLS and len(frame["layers"]) == 1:
        limit = scale if scene["source"] in ("Ending", "Title") else None
        scale, angle, x, y, z = contain_scale(asset, limit), 0, 50, 50, -16
    # In the camp's first cue the original approaches the fire, then settles here
    # for the seven following conversations over this exact same illustration.
    if (scene["source"] == "Scenario_Mage2" and scene.get("label") == "ToDungeon2"
            and len(frame["layers"]) == 1 and frame["bindings"][0]["appearance"] == "CG/mage2sou01Me1"):
        scale, x, y = .19, 47, 42.7
    if scale >= 9999 and Path(asset["path"]).stem.lower() == "priestkaisou08":
        scale, x, y = .43, 50, 50
    left, top, right, bottom = crop
    w, h = size
    # The source actor draws its entire texture centered (100 actor pixels per world unit).
    # Move the cropped drawable around its original pivot before the screen-space rotation.
    dx = ((left + right) / 2 - w / 2) * scale / 100
    dy = (h / 2 - (top + bottom) / 2) * scale / 100
    roll = math.radians(angle)
    wx = (x - 50) * .192 + dx * math.cos(roll) - dy * math.sin(roll) - cx
    wy = (y - 50) * .108 + dx * math.sin(roll) + dy * math.cos(roll) - cy
    wz = z - cz
    pitch = math.radians(angles[0])
    if angles[1] or angles[2]:
        raise ValueError("Unexpected camera yaw/roll in the gallery catalog")
    depth = wz * math.cos(pitch) - wy * math.sin(pitch)
    height = HEIGHT_FACTOR * depth
    mid_x = .5 + wx / (height * ASPECT)
    mid_y = .5 + (wy * math.cos(pitch) + wz * math.sin(pitch)) / height
    half_x = (right - left) * scale / (200 * height * ASPECT)
    half_y = (bottom - top) * scale / (200 * height)
    return mid_x - half_x, mid_y - half_y, mid_x + half_x, mid_y + half_y, angle


def settled_frame(scene,index):
    frame=scene["frames"][index]
    if frame.get("lines") or index+1>=len(scene["frames"]):return frame
    following=scene["frames"][index+1]
    if (not following.get("lines") or not 0<=following["line"]-frame["line"]<=3
            or not set(frame["layers"]).issubset(following["layers"])):return frame
    # Construction cues can show the same art a line before the source camera
    # pulls back for the actual dialogue. Use the settled lens for that freeze.
    z=frame["layout"][0]["z"]
    before=z-camera_for(scene,frame)[0][2]
    after=z-camera_for(scene,following)[0][2]
    if before>0 and after>2*before:
        return dict(frame,camera=following["camera"])
    return frame


def paint_events(host, frames, index, variants, variant):
    return [active(host, True), *[active(node, i == index) for i, node in enumerate(frames)],
            *[active(node, i + 1 == variant) for i, node in enumerate(variants[index])]]


@dataclass
class Surface:
    texture: int
    crop: tuple
    size: tuple
    alpha: bytes = b""


class Paint:
    def __init__(self, gallery, game, catalog, *, background_index=None):
        self.gallery = gallery
        self.root = gallery.node(gallery.gallery, "IllustrationSurface")
        gallery.graphic(self.root, rgba(0, 0, 0), False)
        # The art is a sibling behind the controls and menus. No action replaces the title's world.
        order = gallery.edit(gallery.rects[gallery.gallery])["m_Children"]
        order.insert(0, order.pop())
        # Keep the selected shot shared across both pages. Only a two-event horizontal
        # scroll changes between them. The empty middle page and per-form masks isolate
        # even an extreme original close-up from the neighbouring view.
        self.panels=gallery.node(self.root,"Panels")
        gallery.edits[gallery.rects[self.panels]].update(m_AnchorMin=xy(0,0),m_AnchorMax=xy(3,1),m_Pivot=xy(0,.5))
        self.origin=gallery.node(self.panels,"FrameOrigin")
        gallery.edits[gallery.rects[self.origin]].update(m_AnchorMin=xy(0,0),m_AnchorMax=xy(1/3,1))
        self.scroller=gallery.component(self.root,gallery.ids.scroll,m_Content=ptr(gallery.rects[self.panels]),
            m_Viewport=ptr(gallery.rects[self.root]),m_Horizontal=True,m_Vertical=False,m_MovementType=2,
            m_Inertia=False,m_ScrollSensitivity=0,m_HorizontalScrollbar=ptr(0),m_VerticalScrollbar=ptr(0))
        self.recorded=defaultdict(list)
        for scene in catalog["scenes"]:
            for frame in scene["frames"]:
                for suffix in ("","2") if frame.get("layers2") else ("",):
                    bindings=frame.get("bindings"+suffix,frame["bindings"])
                    for ident,pose,binding in zip(frame["layers"+suffix],frame["layout"],bindings):
                        key=(scene["source"],binding["actor"],ident)
                        self.recorded[key].append((frame["line"],pose))
        self.template = None
        self.texture_type = None
        self.texture_template = None
        self.surface = {}
        self.backs = {}
        self.background_renderer = None
        self.background_index = background_index
        self.bundle_sources = catalog.get('_sourceBundles', {})
        self.scenes = {}
        self.assets = catalog["assets"]
        self.game = Path(game)
        required = {i for scene in catalog["scenes"] for f in scene["frames"]
                    for i in (f["layers"] + (f.get("layers2") or []))}
        self.full_detail = {i for scene in catalog["scenes"] if scene["source"] in STILLS
                            for f in scene["frames"] if len(f["layers"]) == 1
                            for i in (f["layers"] + (f.get("layers2") or []))}
        self.read_foregrounds(required)

    def read_foregrounds(self, required):
        import UnityPy
        groups = defaultdict(list)
        for i in sorted(required):
            a = self.assets[i]
            groups[a["bundle"]].append(a)
        data = self.game / "Annihilated_Data"
        bundles = data / "StreamingAssets" / "aa" / "StandaloneWindows64"
        localized = {}
        if any(self.assets[i].get("resource") for i in required):
            mgr = UnityPy.load(str(data / "globalgamemanagers"))
            resources = UnityPy.load(str(data / "resources.assets"))
            objs = {o.path_id: o for o in resources.objects}
            table = next(o for o in mgr.objects if o.type.name == "ResourceManager").read_typetree()["m_Container"]
            keys = {self.assets[i]["resource"].lower() for i in required if self.assets[i].get("resource")}
            for name, pointer in table:
                if name not in keys:
                    continue
                obj = objs[pointer["m_PathID"]]
                if obj.type.name == "Texture2D":
                    localized[name] = obj.read().image
                elif obj.type.name == "Sprite" and name not in localized:
                    localized[name] = obj.read().m_RD.texture.deref().read().image
            if keys != localized.keys():
                raise ValueError("Missing original translated gallery art")
        for n, (bundle, items) in enumerate(groups.items()):
            pack = UnityPy.load(str(self.bundle_sources.get(bundle,bundles / bundle)))
            wanted = {a["path"] for a in items}
            textures = {p: ref.deref() for p, ref in pack.container.items()
                        if p in wanted and ref.m_PathID and ref.type.name == "Texture2D"}
            for asset in items:
                obj = textures[asset["path"]]
                if self.template is None:
                    self.template = copy.copy(obj)
                    self.template.reader = self.gallery.af.reader
                    self.template.assets_file = self.gallery.af
                    self.texture_template = obj.read_typetree()
                    self.texture_type = len(self.gallery.af.types)
                    self.gallery.af.types.append(obj.serialized_type)
                key = asset.get("resource", "").lower()
                img = localized[key] if key in localized else obj.read().image
                self.surface[asset["id"]] = self.texture("CG_" + str(asset["id"]), img, trim=True,
                                            limit=1920 if asset["id"] in self.full_detail else 1200)
            if n % 4 == 0:
                gc.collect()

    def texture(self, name, image, trim, limit=1200):
        from PIL import Image
        import etcpak
        img = image.convert("RGBA")
        w, h = img.size
        bounds = img.getchannel("A").getbbox()
        if not bounds:
            # A transparent overlay may be one layer of a valid composite.
            return Surface(0, (0, 0, 1, 1), (w, h))
        if trim:
            l, t, r, b = bounds
            bounds = (max(0, l-2), max(0, t-2), min(w, r+2), min(h, b+2))
        else:
            bounds = (0, 0, w, h)
        img = img.crop(bounds)
        alpha = img.getchannel("A").resize((32,32),Image.Resampling.BOX).tobytes() if trim else b""
        ratio = min(1, limit / max(img.size))
        # Block-compressed native textures use integral 4 x 4 blocks.
        dims = tuple(max(4, 4 * round(v * ratio / 4)) for v in img.size)
        if img.size != dims:
            img = img.resize(dims, Image.Resampling.LANCZOS)
        opaque = img.getchannel("A").getextrema()[0] == 255
        encode = etcpak.compress_bc1 if opaque else etcpak.compress_bc3
        raw = encode(img.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes(), *dims)
        obj = copy.copy(self.template)
        obj.assets_file = self.gallery.af
        obj.reader = self.gallery.af.reader
        obj.path_id = self.gallery.allocate()
        obj.type_id = self.texture_type
        self.gallery.added.append(obj.path_id)
        self.gallery.af.objects[obj.path_id] = obj
        values = dict(self.texture_template, m_Name=name, m_Width=dims[0], m_Height=dims[1],
                      m_TextureFormat=10 if opaque else 12, m_MipCount=1, m_CompleteImageSize=len(raw),
                      m_ColorSpace=1, m_IsReadable=False, m_MipsStripped=0, m_StreamingMipmaps=False,
                      m_StreamData={"offset":0,"size":0,"path":""})
        values["image data"] = raw
        obj.save_typetree(values)
        return Surface(obj.path_id, bounds, (w, h), alpha)

    def image(self, parent, name, texture, rect=None, opacity=255):
        g = self.gallery
        node = g.node(parent, name)
        g.component(node, g.ids.renderer)
        g.component(node, g.ids.raw_image, m_Texture=ptr(texture), m_RaycastTarget=False, m_Color=rgba(1,1,1,opacity/255))
        if rect:
            left, bottom, right, top, angle = rect
            half = math.radians(angle) / 2
            g.edits[g.rects[node]].update(m_AnchorMin=xy(left,bottom), m_AnchorMax=xy(right,top),
                                          m_LocalRotation=dict(x=0.,y=0.,z=math.sin(half),w=math.cos(half)))
        return node

    def draw_background(self, parent, scene, frame):
        # Gallery uses an opaque black base. Plain black and transparent standalone backgrounds need no texture.
        bg = frame["background"]
        if not bg["prefab"] and all(layer["actor"].startswith("ColorFlashBackground")
                and layer["appearance"].lower() == "black" for layer in bg["layers"]):
            return
        if self.background_renderer is None:
            try:
                from backgrounds_render import BackgroundRenderer
            except ModuleNotFoundError:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "catalog"))
                from backgrounds_render import BackgroundRenderer
            self.background_renderer = BackgroundRenderer(self.game,index=self.background_index,bundle_sources=self.bundle_sources)
        renderer = self.background_renderer
        position, rotation = camera_for(scene, frame)
        frame = dict(frame, camera={"positionMode":"pos","pos":position,"offset":position,"rotation":rotation})
        key = renderer.key(frame)
        if key not in self.backs:
            image = renderer.render(frame, width=1280, height=720)
            self.backs[key] = self.texture("Backdrop_" + str(len(self.backs)), image, trim=False)
            if len(self.backs) % 6 == 0:
                # Game bundles own file/object reference cycles. The ordinary thresholds
                # count Python objects rather than native image buffers.
                gc.collect()
        if self.backs[key].texture:
            self.image(parent, "OriginalScenery", self.backs[key].texture)
            self.image(parent, "CompleteScenery", self.backs[key].texture,(2,0,3,1,0))

    def framing_calls(self,full):
        assembly="UnityEngine.UI.ScrollRect, UnityEngine.UI"
        return [event(self.scroller,assembly,"StopMovement"),
                event(self.scroller,assembly,"set_horizontalNormalizedPosition",4,1.0 if full else 0.0)]

    def page_mask(self,parent,name,offset):
        g=self.gallery
        go=g.node(parent,name)
        g.edits[g.rects[go]].update(m_AnchorMin=xy(offset,0),m_AnchorMax=xy(offset+1,1))
        g.graphic(go,rgba(1,1,1),False)
        g.component(go,g.ids.mask,m_ShowMaskGraphic=False)
        return go

    def draw_form(self,form,scene,frame,ids,bindings):
        layers=[]
        for index,(ident,pose) in enumerate(zip(ids,frame["layout"],strict=True)):
            surface=self.surface[ident]
            if not surface.texture:continue
            asset=self.assets[ident]
            def rect_for(layout):
                return projected(scene,frame,asset,layout,surface.crop,surface.size)
            rect=rect_for(pose)
            fraction=visible_fraction(rect,surface.alpha)
            if fraction<.025:
                # Some layers enter only after several lines. Recover that recorded pose
                # before applying a generic framing correction.
                for candidate in frame.get("poseAlternatives",[]):
                    alternate=rect_for(candidate[index])
                    visibility=visible_fraction(alternate,surface.alpha)
                    if visibility>.5:
                        rect,fraction=alternate,visibility
                        pose=candidate[index]
                        break
            if fraction<.025 and len(ids)==1:
                # A freeze during an exit may leave no art on screen. Prefer the same
                # artist-defined pose of the same actor/texture just before the cut.
                key=(scene["source"],bindings[index]["actor"],ident)
                recent=sorted(((line,p) for line,p in self.recorded[key]
                                if 0<frame["line"]-line<=40),key=lambda item:-item[0])
                for _,candidate in recent:
                    alternate=rect_for(candidate)
                    if visible_fraction(alternate,surface.alpha)>.5:
                        rect=alternate
                        pose=candidate
                        break
                else:
                    rect=fitted_rects([rect])[0]
                fraction=visible_fraction(rect,surface.alpha)
            layers.append((index,surface.texture,rect,fraction,pose.get("opacity",255)))
        story=self.page_mask(form,"StoryLayers",0)
        complete=self.page_mask(form,"CompleteLayers",2)
        # A character or effect that the script has deliberately moved entirely
        # offstage must not reappear in a later room when the user views the full art.
        included=[fraction>.002 for _,_,_,fraction,_ in layers]
        if not any(included):included=[True]*len(layers)
        full=fitted_rects([rect for _,_,rect,_,_ in layers],included)
        for (index,texture,rect,_,opacity),whole,show in zip(layers,full,included):
            self.image(story,"Layer"+str(index+1),texture,rect,opacity)
            drawn=self.image(complete,"Layer"+str(index+1),texture,whole,opacity)
            if not show:self.gallery.edits[drawn]["m_IsActive"]=False

    def scene(self, scene):
        if scene["id"] in self.scenes:
            return self.scenes[scene["id"]]
        g = self.gallery
        host = g.node(self.origin, "Painting_" + scene["id"], enabled=False)
        frames, variants = [], []
        for n, original in enumerate(scene["frames"]):
            f=settled_frame(scene,n)
            rack = g.node(host, "Shot" + str(n+1), enabled=False)
            frames.append(rack)
            self.draw_background(rack, scene, f)
            layouts = [f["layers"]]
            if f.get("layers2") and f["layers2"] != f["layers"]:
                layouts.append(f["layers2"])
            forms = []
            for v, ids in enumerate(layouts):
                form = g.node(rack, "Art" + str(v+1), enabled=v==0)
                forms.append(form)
                bindings=f.get("bindings2",f["bindings"]) if v else f["bindings"]
                self.draw_form(form,scene,f,ids,bindings)
            variants.append(forms)
        self.scenes[scene["id"]] = host, frames, variants
        return host, frames, variants
