"""Build the native gallery inside the shipped CustomTitleUI prefab."""
import argparse
import copy
import gc
import json
import sys
from pathlib import Path
from functools import cache


from title_bindings import TITLE_PATH, validate_modified, validate_stock


def ptr(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


def xy(x, y):
    return {"x": x, "y": y}


def rgba(r, g, b, a=1):
    return dict(r=r, g=g, b=b, a=a)


def event(target, assembly, method, mode=1, arg=None):
    args = {"m_ObjectArgument": ptr(0), "m_ObjectArgumentAssemblyTypeName": "UnityEngine.Object, UnityEngine",
            "m_IntArgument": 0, "m_FloatArgument": 0, "m_StringArgument": "", "m_BoolArgument": False}
    if mode in (3, 4, 5, 6):
        args[{3:"m_IntArgument", 4:"m_FloatArgument", 5:"m_StringArgument", 6:"m_BoolArgument"}[mode]] = arg
    return {"m_Target": ptr(target), "m_TargetAssemblyTypeName": assembly, "m_MethodName": method,
            "m_Mode": mode, "m_Arguments": args, "m_CallState": 2}


def active(go, value):
    return event(go, "UnityEngine.GameObject, UnityEngine.CoreModule", "SetActive", 6, value)


def text_change(label, value):
    return event(label, "TMPro.TextMeshProUGUI, Unity.TextMeshPro", "set_text", 5, value)


class Gallery:
    def __init__(self, env, game=None, binding=None):
        self.env = env
        self.ids = binding or validate_stock(env, game)
        self.af = env.container[self.ids.title_path].deref().assets_file
        self.next_id = 83000001
        self.added = []
        self.edits = {}
        self.rects = {self.ids.root: self.ids.root_rect}
        self.art_groups = []
        self.pages = []
        self.button_labels = {}

    @cache
    def source(self, template):
        return self.af.objects[template].read_typetree()

    def edit(self, oid):
        if oid not in self.edits:
            self.edits[oid] = copy.deepcopy(self.source(oid))
        return self.edits[oid]

    def allocate(self):
        while self.next_id in self.af.objects:
            self.next_id += 1
        oid = self.next_id
        self.next_id += 1
        return oid

    def new(self, tid, **updates):
        obj = copy.copy(self.af.objects[tid])
        oid = self.allocate()
        obj.path_id = oid
        self.af.objects[oid] = obj
        self.added.append(oid)
        self.edits[oid] = {**self.source(tid), **updates}
        return oid

    def component(self, go, template, **updates):
        oid = self.new(template, m_GameObject=ptr(go), **updates)
        self.edits[go]["m_Component"].append({"component":ptr(oid)})
        return oid

    def attach(self, go, template, **updates):
        self.edit(go)
        return self.component(go, template, **updates)

    def node(self, parent, name, box=None, enabled=True):
        go = self.new(self.ids.entry, m_Name=name, m_Component=[], m_IsActive=enabled)
        p = self.rects[parent]
        if box is None:
            lo, hi, pos, size = xy(0,0), xy(1,1), xy(0,0), xy(0,0)
        else:
            x,y,w,h = box
            lo = hi = xy(.5,.5)
            pos, size = xy(x,y), xy(w,h)
        rect = self.component(go, self.ids.rect, m_AnchorMin=lo, m_AnchorMax=hi, m_AnchoredPosition=pos,
                              m_SizeDelta=size, m_Pivot=xy(.5,.5), m_Father=ptr(p), m_Children=[])
        self.rects[go] = rect
        self.edit(p)["m_Children"].append(ptr(rect))
        return go

    def graphic(self, go, color, mouse):
        self.component(go, self.ids.renderer)
        return self.component(go, self.ids.graphic, m_Sprite=ptr(0), m_Material=ptr(0), m_Color=color,
                              m_RaycastTarget=mouse, m_Type=0)

    def label(self, parent, name, caption, box, size, left=False, localize=True):
        go = self.node(parent,name,box)
        self.component(go,self.ids.renderer)
        t = self.component(go, self.ids.entry_text, m_text=caption, m_RaycastTarget=False, m_fontSize=size,
                           m_fontSizeBase=size, m_enableAutoSizing=False, m_HorizontalAlignment=1 if left else 2,
                           m_VerticalAlignment=256 if left else 512, m_overflowMode=3, m_isRichText=False)
        if localize:
            self.component(go,self.ids.font_localizer,enableDebugLog=False)
        return t

    def button(self,parent, name, caption, box, size=32):
        btn = self.node(parent, name, box)
        graphic = self.graphic(btn,rgba(.32,.47,.55,.96),True)
        colors=copy.deepcopy(self.source(self.ids.standard_button)["m_Colors"])
        for key, value in (("m_NormalColor",.66),("m_SelectedColor",.92),("m_HighlightedColor",1)):
            colors[key]=rgba(value,value,value)
        comp = self.component(btn,self.ids.standard_button,m_TargetGraphic=ptr(graphic),m_Colors=colors,
                              m_OnClick={"m_PersistentCalls":{"m_Calls":[]}})
        self.button_labels[comp]=self.label(btn,name+"Label",caption,None,size)
        return comp

    def text_button(self,parent,name,caption,box,size=28):
        label=self.label(parent,name,caption,box,size)
        go=self.edits[label]["m_GameObject"]["m_PathID"]
        self.edits[label]["m_RaycastTarget"]=True
        colors=copy.deepcopy(self.source(self.ids.standard_button)["m_Colors"])
        for key,value in (("m_NormalColor",.80),("m_HighlightedColor",1),("m_SelectedColor",1)):
            colors[key]=rgba(value,value,value)
        return self.component(go,self.ids.standard_button,m_TargetGraphic=ptr(label),m_Colors=colors,
                              m_OnClick={"m_PersistentCalls":{"m_Calls":[]}})

    def hit_button(self,parent,name):
        go=self.node(parent,name)
        graphic=self.graphic(go,rgba(1,1,1,0),True)
        return go,self.component(go,self.ids.standard_button,m_TargetGraphic=ptr(graphic),m_Transition=0,
                                 m_OnClick={"m_PersistentCalls":{"m_Calls":[]}})

    def wire(self, button, *calls):
        self.edit(button)["m_OnClick"] = {"m_PersistentCalls":{"m_Calls":list(calls)}}

    def shade(self, parent):
        self.graphic(parent,rgba(.045,.065,.086,.985),True)

    def page(self, name, heading, subheading=""):
        go = self.node(self.gallery,name,enabled=False)
        self.pages.append(go)
        self.shade(go)
        self.label(go,"Heading",heading,(0,430,1220,94),58)
        if subheading:
            self.label(go,"Subheading",subheading,(0,344,1280,62),28)
        return go

    def toggle(self, origin, target):
        return [active(target,True),active(origin,False)]

    def art(self, opacity):
        return [event(c,"UnityEngine.CanvasGroup, UnityEngine.UIModule","set_alpha",4,opacity) for c in self.art_groups]

    def prepare(self):
        # Reuse the shipped, dormant title-menu slot and its native interaction styling.
        go = self.edit(self.ids.entry)
        go["m_IsActive"]=True
        go["m_Component"]=[c for c in go["m_Component"] if c["component"]["m_PathID"]!=self.ids.entry_driver]
        label = self.edit(self.ids.entry_label)
        label["m_Component"]=[c for c in label["m_Component"] if c["component"]["m_PathID"]!=self.ids.label_driver]
        self.edit(self.ids.entry_text)["m_text"]="CG 鉴赏"
        self.attach(self.ids.entry_label,self.ids.font_localizer,enableDebugLog=False)
        for art in self.ids.title_art:
            self.art_groups.append(self.attach(art,self.ids.canvas_group,m_BlocksRaycasts=False,m_Interactable=False))
        self.gallery=self.node(self.ids.root,"MemoryGallery",enabled=False)
        self.home=self.page("GalleryIndex","CG 鉴赏","选择同伴与场景。可在这里开启剧透预览。")
        self.edits[self.home]["m_IsActive"]=True
        self.wire(self.ids.entry_button,active(self.gallery,True),active(self.ids.buttons,False),*self.art(0.0))
        leave=self.button(self.home,"ReturnToTitle","返回标题",(0,-365,340,70))
        self.wire(leave,active(self.ids.buttons,True),*self.art(1.0),active(self.gallery,False))

    def finish(self,dest):
        # New objects must be included in this prefab's preload range, without shifting other prefab ranges.
        bundle=next(k for k,o in self.af.objects.items() if o.type.name=="AssetBundle")
        index=self.edit(bundle)
        preload=index["m_PreloadTable"]
        spec=next(spec for name,spec in index["m_Container"] if name==self.ids.title_path)
        start,size=spec["preloadIndex"],spec["preloadSize"]
        combined=preload[start:start+size]+[ptr(k) for k in self.added]
        refs={(p["m_FileID"],p["m_PathID"]) for p in combined}
        for d in self.edits.values():
            p=d.get("m_Script")
            if p and (p["m_FileID"],p["m_PathID"]) not in refs:
                refs.add((p["m_FileID"],p["m_PathID"]))
                combined.append(p)
        spec["preloadIndex"]=len(preload)
        spec["preloadSize"]=len(combined)
        preload.extend(combined)
        for oid,tree in self.edits.items():
            self.af.objects[oid].save_typetree(tree)
        # The serialized objects now own their bytes, including the texture payload.
        # Release the temporary hierarchies before UnityPy builds the large I/O buffer.
        self.edits.clear()
        gc.collect()
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(self.env.file.save(packer="lz4"))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--game",type=Path,required=True)
    p.add_argument("--unitypy",type=Path)
    args=p.parse_args()
    if args.source.resolve()==args.output.resolve():
        p.error("Use a separate output file")
    if args.unitypy:
        sys.path.insert(0,str(args.unitypy.resolve()))
    import UnityPy
    gallery=Gallery(UnityPy.load(args.source.read_bytes()),game=args.game)
    gallery.prepare()
    from catalog_ui import build
    build(gallery,json.loads(args.catalog.read_text(encoding="utf-8-sig")),args.game)
    gallery.finish(args.output)
    rects=gallery.rects
    binding=gallery.ids
    added,pages=len(gallery.added),len(gallery.pages)
    gallery.source.cache_clear()
    del gallery
    gc.collect()
    check=UnityPy.load(args.output.read_bytes())
    validate_modified(check,binding)
    file=check.container[binding.title_path].deref().assets_file
    for go,rect in rects.items():
        assert file.objects[rect].read_typetree()["m_GameObject"]==ptr(go)
    print(f"{added} native objects, {pages} index/reading panels, {args.output.stat().st_size} bytes")


if __name__=="__main__":
    main()
