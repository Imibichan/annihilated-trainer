"""Independently inspect the saved title prefab and simulate its native UI navigation."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

from build_title import validate_modified, validate_stock
from catalog_ui import GROUPS, category_sections, read_lines

UI_METHODS = {
    "SetActive":("UnityEngine.GameObject, UnityEngine.CoreModule",6),
    "set_text":("TMPro.TextMeshProUGUI, Unity.TextMeshPro",5),
    "set_alpha":("UnityEngine.CanvasGroup, UnityEngine.UIModule",4),
    "Select":("UnityEngine.UI.Button, UnityEngine.UI",1),
    "StopMovement":("UnityEngine.UI.ScrollRect, UnityEngine.UI",1),
    "set_verticalNormalizedPosition":("UnityEngine.UI.ScrollRect, UnityEngine.UI",4),
    "set_horizontalNormalizedPosition":("UnityEngine.UI.ScrollRect, UnityEngine.UI",4),
}


def verify(bundle,catalog,game,vanilla_bundle=None):
    import UnityPy
    env=UnityPy.load(bundle.read_bytes())
    startup_dir=game/"Annihilated_Data"/"StreamingAssets"/"aa"/"StandaloneWindows64"
    startup=vanilla_bundle or next(startup_dir.glob("naninovelstartupui_assets_all_*.bundle"))
    stock=UnityPy.load(startup.read_bytes())
    ids=validate_stock(stock,game)
    validate_modified(env,ids)
    vanilla=stock.container[ids.title_path].deref().assets_file
    af=env.container[ids.title_path].deref().assets_file
    new_ids=af.objects.keys()-vanilla.objects.keys()
    bundle_info=next(i for i,o in vanilla.objects.items() if o.type.name=="AssetBundle")
    expected_changes={ids.entry,ids.entry_label,ids.entry_button,ids.entry_text,ids.root_rect,bundle_info,*ids.title_art}
    assert {i for i,o in vanilla.objects.items() if o.get_raw_data()!=af.objects[i].get_raw_data()}==expected_changes
    nodes={o.path_id:o.read_typetree() for o in af.objects.values()
           if (o.path_id in new_ids and o.type.name!="Texture2D")
           or o.path_id in (ids.entry_button,ids.entry,ids.entry_text,ids.root,ids.buttons)}
    def node(i):
        if i not in nodes:
            nodes[i]=af.objects[i].read_typetree()
        return nodes[i]
    def rect(go):
        return node(go)["m_Component"][0]["component"]["m_PathID"]
    def go(component):
        return node(component)["m_GameObject"]["m_PathID"]
    def children(parent):
        return [go(n["m_PathID"]) for n in node(rect(parent))["m_Children"]]
    def child(parent,name):
        matches=[i for i in children(parent) if node(i)["m_Name"]==name]
        assert len(matches)==1,(node(parent)["m_Name"],name,len(matches))
        return matches[0]
    def script(i):
        pointer=node(i).get("m_Script")
        return (pointer["m_FileID"],pointer["m_PathID"]) if pointer else None
    button_script=script(ids.standard_button)
    text_script=script(ids.entry_text)
    def button(i):
        if "m_Component" not in node(i):
            return i
        return next(c["component"]["m_PathID"] for c in node(i)["m_Component"] if script(c["component"]["m_PathID"])==button_script)
    objects=[i for i in nodes if i in new_ids]
    # All new behaviours are shipped UI components. Any scenario/effect controller is a failure.
    allowed_components={script(template) for template in (
        ids.standard_button,ids.graphic,ids.font_localizer,ids.canvas_group,ids.entry_text,ids.raw_image,ids.mask,ids.fitter,ids.scroll)}
    textures={i for i,o in af.objects.items() if i in new_ids and o.type.name=="Texture2D"}
    assigned=set()
    for i in objects:
        if af.objects[i].type.name=="MonoBehaviour":
            assert script(i) in allowed_components and script(i) is not None, ("non-UI behaviour",i,script(i))
        if script(i)==script(ids.raw_image):
            tex=node(i)["m_Texture"]
            assert tex["m_FileID"]==0 and tex["m_PathID"] in textures
            assigned.add(tex["m_PathID"])
    assert assigned==textures and textures
    texture_names={}
    for i in textures:
        value=af.objects[i].read_typetree()
        assert value["m_TextureFormat"] in (10,12) and not value["m_IsReadable"]
        assert value["m_StreamData"]["size"]==0 and len(value["image data"])==value["m_CompleteImageSize"]
        texture_names[i]=value["m_Name"]
    del value
    for i in objects:
        t=node(i)
        if "m_Component" in t:
            assert t["m_Layer"]==node(ids.entry)["m_Layer"]
            assert len(t["m_Component"])==len({c["component"]["m_PathID"] for c in t["m_Component"]})
            for ref in t["m_Component"]:
                assert go(ref["component"]["m_PathID"])==i
            ident=rect(i)
            parent=node(ident)["m_Father"]["m_PathID"]
            if parent:
                assert ident in [c["m_PathID"] for c in node(parent)["m_Children"]]
    methods=Counter()
    objects_set=set(objects)
    for i in objects+[ids.entry_button]:
        for call in node(i).get("m_OnClick",{}).get("m_PersistentCalls",{}).get("m_Calls",[]):
            target=call["m_Target"]["m_PathID"]
            method=call["m_MethodName"]
            assert target in af.objects and method in UI_METHODS and call["m_CallState"]==2
            assert (call["m_TargetAssemblyTypeName"],call["m_Mode"])==UI_METHODS[method]
            assert target in objects_set or target==ids.buttons
            if method=="Select":assert script(target)==button_script
            if method=="set_alpha":assert af.objects[target].type.name=="CanvasGroup"
            if method in ("StopMovement","set_verticalNormalizedPosition","set_horizontalNormalizedPosition"):assert script(target)==script(ids.scroll)
            if method=="set_text":
                assert script(target)==text_script
            if method=="SetActive":
                assert af.objects[target].type.name=="GameObject"
            methods[method]+=1
    ui=child(ids.root,"MemoryGallery")
    surface=child(ui,"IllustrationSurface")
    assert children(ui)[0]==surface
    origin=child(child(surface,"Panels"),"FrameOrigin")
    paintings={s["id"]:child(origin,"Painting_"+s["id"]) for s in catalog["scenes"]}
    fitted_layers=0
    for s in catalog["scenes"]:
        for idx,frame in enumerate(s["frames"]):
            shot=child(paintings[s["id"]],"Shot"+str(idx+1))
            for form,layer_ids in enumerate([frame["layers"]]+([frame["layers2"]] if frame.get("layers2") else [])):
                drawer=child(shot,"Art"+str(form+1))
                complete=child(drawer,"CompleteLayers")
                for layers in (child(drawer,"StoryLayers"),complete):
                    for layer,asset in enumerate(layer_ids):
                        obj=child(layers,"Layer"+str(layer+1))
                        raw=next(k["component"]["m_PathID"] for k in node(obj)["m_Component"]
                                 if script(k["component"]["m_PathID"])==script(ids.raw_image))
                        assert texture_names[node(raw)["m_Texture"]["m_PathID"]]=="CG_"+str(asset)
                        expected_opacity=frame["layout"][layer].get("opacity",255)/255
                        assert abs(node(raw)["m_Color"]["a"]-expected_opacity)<1e-5,(s["id"],idx,layer,"opacity")
                        if layers==complete and node(obj)["m_IsActive"]:
                            t=node(rect(obj))
                            a,b=t["m_AnchorMin"],t["m_AnchorMax"]
                            cx,cy=(a["x"]+b["x"])/2,(a["y"]+b["y"])/2
                            w,h=(b["x"]-a["x"])/2,(b["y"]-a["y"])/2
                            rot=t["m_LocalRotation"]
                            angle=2*math.atan2(rot["z"],rot["w"])
                            dx=abs(w*math.cos(angle))+abs(h*math.sin(angle))*9/16
                            dy=abs(h*math.cos(angle))+abs(w*math.sin(angle))*16/9
                            assert min(cx-dx,cy-dy,1-cx-dx,1-cy-dy)>=-1e-5,(s["id"],idx,layer)
                            fitted_layers+=1
    home=child(ui,"GalleryIndex")
    shared=child(ui,"SharedSceneReader")
    holder=child(ui,"ActiveSceneControls")
    art=child(ui,"FullArtReturn")
    assert node(ids.entry)["m_IsActive"] and node(ids.entry_text)["m_text"]=="CG 鉴赏" and not node(ui)["m_IsActive"]
    seen=set()
    def walk(p):
        assert p not in seen
        seen.add(p)
        for c in children(p): walk(c)
    walk(ui)
    assert set(i for i in objects if "m_Component" in node(i))==seen
    active={i:bool(t["m_IsActive"]) for i,t in nodes.items() if "m_IsActive" in t}
    labels={}
    def effective(i):
        while i and i!=ids.root:
            if not active.get(i,node(i)["m_IsActive"]):
                return False
            father=node(rect(i))["m_Father"]["m_PathID"]
            i=go(father) if father else 0
        return True
    def click(i):
        comp=button(i)
        assert effective(go(comp)),("click on hidden object",node(go(comp))["m_Name"])
        for c in node(comp)["m_OnClick"]["m_PersistentCalls"]["m_Calls"]:
            target=c["m_Target"]["m_PathID"]
            method=c["m_MethodName"]
            if method=="SetActive":active[target]=bool(c["m_Arguments"]["m_BoolArgument"])
            if method=="set_text":labels[target]=c["m_Arguments"]["m_StringArgument"]
            if method=="set_horizontalNormalizedPosition":labels["framing"]=c["m_Arguments"]["m_FloatArgument"]

    def test_choice(code,option,view,prompt,index):
        saved=active.copy(),labels.copy()
        click(child(prompt,"Choose"+str(index)))
        target=option["sceneId"]
        dest_code=code if (code,target) in locations else main_groups[target]
        page2,slot2=locations[(dest_code,target)]
        dest=child(holder,f"Scene_{dest_code}_{page2}_{slot2}")
        assert effective(dest) and effective(shared) and not effective(prompt)
        assert effective(child(dest,"Frame1")) and effective(child(paintings[target],"Shot1"))
        assert [name for name,art in paintings.items() if active[art]]==[target]
        assert not effective(view) or view==dest
        click(child(dest,"CloseScene"))
        assert effective(child(ui,dest_code+str(page2)))
        active.clear();active.update(saved[0])
        labels.clear();labels.update(saved[1])
    click(ids.entry_button)
    assert effective(home) and not effective(ids.buttons)
    enable=child(home,"EnableSpoilers")
    disable=child(home,"DisableSpoilers")
    assert effective(enable) and not effective(disable)
    eyes=[i for i in objects if node(i).get("m_Name","").startswith("Preview") and
          node(i).get("m_Name","")[7:].isdigit()]
    assert eyes and all(not active[i] for i in eyes)
    click(enable)
    assert effective(disable) and all(active[i] for i in eyes)
    albums={group:category_sections(catalog["scenes"],group) for group in GROUPS}
    locations={}
    for code,sections in albums.items():
        pages=[rows for section in sections for rows in section.pages]
        for page_no,rows in enumerate(pages):
            for slot,scene in enumerate(rows):
                assert (code,scene["id"]) not in locations
                locations[code,scene["id"]]=page_no,slot
    main_groups={s["id"]:s["group"] for s in catalog["scenes"]}
    box=child(shared,"DialogueBox")
    top=child(shared,"SceneToolbar")
    line=child(box,"LineReader")
    full=child(box,"FullTranscript")
    def text_comp(p,n):
        return next(c["component"]["m_PathID"] for c in node(child(p,n))["m_Component"]
                    if script(c["component"]["m_PathID"])==text_script)
    single=text_comp(line,"LineContent")
    with (game/"Annihilated_Data"/"resources.assets").open("rb") as source:
        dialogue={s["id"]:[read_lines(f,source) for f in s["frames"]] for s in catalog["scenes"]}
    frame_total=0
    line_total=0
    branch_total=0
    for code,sections in albums.items():
        if not sections:continue
        click(child(home,"Group"+code))
        chooser=child(ui,code+"Chapters")
        pages=[(i,p,len(section.pages),rows) for i,section in enumerate(sections)
               for p,rows in enumerate(section.pages)]
        for page_no,(section_no,within,total,rows) in enumerate(pages):
            if within==0:
                assert effective(chooser)
                click(child(chooser,"Section"+str(section_no)))
            page=child(ui,code+str(page_no))
            assert effective(page) and not effective(chooser)
            assert node(text_comp(page,"Heading"))["m_text"]==sections[section_no].caption
            section_ends={node(o)["m_Name"] for o in children(page) if node(o)["m_Name"].startswith("Step")}
            assert ("Step-1" in section_ends)==(within>0)
            assert ("Step1" in section_ends)==(within+1<total)
            for slot,scene in enumerate(rows):
                eye=child(page,"Preview"+str(slot))
                assert effective(eye)
                click(eye)
                preview=child(ui,f"Preview_{code}_{page_no}")
                paint=paintings[scene["id"]]
                start=scene.get("alsoFrames",{}).get(code,0)
                assert effective(child(paint,"Shot"+str(start+1)))
                assert effective(preview) and not effective(shared)
                click(child(preview,"BackToIndexPage"))
                assert not any(active[art] for art in paintings.values()) and effective(page)
                click(child(page,"SceneButton"+str(slot)))
                view=child(holder,f"Scene_{code}_{page_no}_{slot}")
                assert effective(view) and effective(shared)
                start=scene.get("alsoFrames",{}).get(code,0)
                assert effective(child(view,"Frame"+str(start+1)))
                all_lines=dialogue[scene["id"]]
                if scene.get("branches"):
                    picker=child(view,"BranchPicker")
                    prompt=child(ui,f"Branches_{code}_{page_no}_{slot}")
                    click(picker)
                    assert effective(prompt) and not effective(view)
                    click(child(prompt,"BackToScene"))
                    assert effective(view)
                    click(picker)
                    for j,option in enumerate(scene["branches"]):
                        test_choice(code,option,view,prompt,j)
                        branch_total+=1
                    click(child(prompt,"BackToScene"))
                if not effective(box):click(child(top,"ExpandDialogue"))
                click(child(top,"ReadTranscript"))
                assert effective(full) and not effective(line)
                click(child(top,"ReadLine"))
                assert effective(line) and not effective(full)
                click(child(top,"CollapseDialogue"))
                assert not effective(box)
                click(child(top,"ExpandDialogue"))
                click(child(top,"ArtOnly"))
                assert effective(art) and not effective(view) and not effective(shared) and labels["framing"]==1
                click(child(art,"ClickArtToRestore"))
                assert effective(view) and effective(shared) and labels["framing"]==0
                for fi in range(start,0,-1):
                    click(child(child(view,"Frame"+str(fi+1)),"Step-1"))
                for fi,rows in enumerate(all_lines):
                    rack=child(view,"Frame"+str(fi+1))
                    group=child(line,f"Lines_{code}_{page_no}_{slot}_{fi}")
                    assert effective(rack) and effective(group)
                    f=scene["frames"][fi]
                    if f.get("layers2"):
                        for form in (1,0):
                            ch="2" if form else ""
                            click(child(rack,"Form"+str(form)))
                            picture=child(paint,"Shot"+str(fi+1))
                            assert effective(child(picture,"Art"+str(form+1))) and not effective(child(picture,"Art"+str(2-form)))
                    for li,original in enumerate(rows or ["此画面没有对白。"]):
                        assert labels[single]==original
                        click(child(group,"Advance"+str(li)))
                        if rows:line_total+=1
                    if f.get("branches"):
                        prompt=child(ui,f"Branches_{code}_{page_no}_{slot}_Frame{fi}")
                        assert effective(prompt)
                        for j,option in enumerate(f["branches"]):
                            test_choice(code,option,view,prompt,j)
                            branch_total+=1
                        click(child(prompt,"BackToScene"))
                        if fi+1<len(all_lines):click(child(rack,"Step1"))
                    frame_total+=1
                click(child(view,"CloseScene"))
                assert not any(active[art] for art in paintings.values()) and effective(page) and not effective(view)
            if within+1<total:
                click(child(page,"Step1"))
                following=child(ui,code+str(page_no+1))
                click(child(following,"Step-1"))
                assert effective(page)
                click(child(page,"Step1"))
            else:
                click(child(page,"Back"))
                assert effective(chooser)
        click(child(chooser,"Back"))
        assert effective(home)
    click(disable)
    assert effective(enable) and not any(active[i] for i in eyes)
    click(child(home,"ReturnToTitle"))
    assert not effective(ui) and effective(ids.buttons)
    print(f"{len(catalog['scenes'])} unique scenes, {len(locations)} preview/open/return paths, {branch_total} branch jumps; "
          f"{frame_total} frame visits; {line_total} dialogue clicks; "
          f"{fitted_layers} full-view layer bounds; {len(textures)} independent native UI textures, zero gallery scripts; "
          f"{len(seen)} gallery GameObjects; {sum(methods.values())} validated native calls. All passed.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("bundle","catalog","game"):
        p.add_argument(name,type=Path)
    p.add_argument("--unitypy",type=Path)
    p.add_argument("--vanilla-bundle",type=Path)
    a=p.parse_args()
    if a.unitypy:sys.path.insert(0,str(a.unitypy.resolve()))
    verify(a.bundle,json.loads(a.catalog.read_text(encoding="utf-8")),a.game,a.vanilla_bundle)
