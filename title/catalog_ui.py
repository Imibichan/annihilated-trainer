"""Bind the versioned scene catalog to native Unity UI on the title prefab."""
import re
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

from ui_art import Paint, paint_events

from build_title import active, event, ptr, rgba, text_change, xy


GROUPS = {"Hero":"勇者", "Mage":"魔法师", "Warrior":"战士", "Priest":"僧侣", "Shared":"共通与其他 CG"}
MARGINS = {"x":18,"y":8,"z":18,"w":8}
MARKUP = re.compile(r"\[(?:wait(?:\s+[^\]]*)?|/?[ib]|br|stop)\]|</?(?:color|size|[biu]|alpha|voffset|cspace|shake|bounce|wave|ruby)(?=[\s=>])[^<>]*>",re.I)
SYMBOLS = {"playername":"主角", 'translatecharactername("player")':"主角", "partnername":"同伴",
           'translatename("partner")':"同伴", "tempeventtag":"〔事件标记〕", "event29thrownitemname":"〔投掷的道具〕",
           "event30meatitemname":"〔食物名称〕", "zyouken1":"〔条件一〕", "zyouken2":"〔条件二〕",
           "ciftext":"〔分支文字〕", "ciftext2":"〔分支文字〕", "playertype":"〔主角形象〕"}


def clean_line(s):
    s=re.sub(r"<br\s*/?>|\[br\]", "\n", s, flags=re.I)
    return re.sub(r"\{([^{}]+)\}",lambda m:SYMBOLS.get(m[1].lower(),m[0]),MARKUP.sub("",s)).strip()


def read_lines(frame,resources):
    lines=[]
    for row in frame.get("lines",[]):
        if row["offset"]<0 or row["length"]<0:
            raise ValueError("Negative dialogue byte range")
        resources.seek(row["offset"])
        raw=resources.read(row["length"])
        if len(raw)!=row["length"]:
            raise ValueError("Incomplete dialogue resource")
        line=clean_line(raw.decode("utf-8"))
        who=row.get("speaker","")
        if line:
            lines.append(("选项　" if row.get("kind")=="choice" else (who+"　" if who else ""))+line)
    return lines


def read_frame(frame,resources):
    return "\n\n".join(read_lines(frame,resources))


def scroll_text(g, parent, box):
    host=g.node(parent,"ScrollableDialogue",box)
    g.graphic(host,rgba(.04,.065,.085,.96),True)
    viewport=g.node(host,"Viewport")
    g.graphic(viewport,rgba(1,1,1),True)
    g.component(viewport,g.ids.mask,m_ShowMaskGraphic=False)
    label=g.label(viewport,"Transcript","",None,30,left=True)
    content=g.edits[label]["m_GameObject"]["m_PathID"]
    rect=g.rects[content]
    g.edits[rect].update(m_AnchorMin=xy(0,1),m_AnchorMax=xy(1,1),m_Pivot=xy(.5,1))
    g.edits[label].update(m_margin=MARGINS, m_overflowMode=0)
    g.component(content,g.ids.fitter,m_HorizontalFit=0,m_VerticalFit=2)
    scroller=g.component(host,g.ids.scroll,m_Content=ptr(rect),m_Viewport=ptr(g.rects[viewport]),m_Horizontal=False,
                         m_Vertical=True,m_MovementType=2,m_ScrollSensitivity=72,
                         m_VerticalScrollbar=ptr(0),m_HorizontalScrollbar=ptr(0))
    return label,scroller


def selected(g,button):
    return event(button, "UnityEngine.UI.Button, UnityEngine.UI", "Select")


def navigation(g,origin,target,first=None):
    return g.toggle(origin,target)+([selected(g,first)] if first else [])


def reader(g):
    shared=g.node(g.gallery,"SharedSceneReader",enabled=False)
    scene_host=g.node(g.gallery,"ActiveSceneControls")
    titlebar=g.node(shared,"SceneToolbar",(0,477,1420,70))
    g.graphic(titlebar,rgba(.04,.065,.085,.95),True)
    stat=g.label(titlebar,"FrameNumber","",(595,0,162,64),26)
    dialogue=g.node(shared,"DialogueBox")
    full=g.node(dialogue,"FullTranscript",enabled=False)
    text,scroll=scroll_text(g,full,(0,-315,1420,276))
    line=g.node(dialogue,"LineReader",(0,-350,1420,187))
    g.graphic(line,rgba(.04,.065,.085,.94),True)
    single=g.label(line,"LineContent","",(0,15,1362,132),32,left=True)
    g.edits[single].update(m_enableAutoSizing=True,m_fontSizeMin=24,m_fontSizeMax=32)
    progress=g.label(line,"LineNumber","",(400,-68,528,48),23)
    footer=g.node(shared,"FrameToolbar",(0,-485,1420,62))
    g.graphic(footer,rgba(.04,.065,.085,.92),False)
    show=g.button(titlebar,"ExpandDialogue","显示对话",(160,0,146,59),22)
    hide=g.button(titlebar,"CollapseDialogue","收起对话",(160,0,146,59),22)
    as_full=g.button(titlebar,"ReadTranscript","全文",(291,0,100,59),23)
    as_line=g.button(titlebar,"ReadLine","逐句",(291,0,100,59),23)
    art=g.button(titlebar,"ArtOnly","纯看图",(416,0,131,59),23)
    blank=g.node(g.gallery,"FullArtReturn",enabled=False)
    _,hotspot=g.hit_button(blank,"ClickArtToRestore")
    def go_of(comp):
        return g.edits[comp]["m_GameObject"]["m_PathID"]
    defaults=[active(line,True),active(full,False),active(go_of(as_full),True),active(go_of(as_line),False)]
    g.wire(as_line,*defaults,active(dialogue,True),active(go_of(hide),True),active(go_of(show),False))
    g.wire(as_full,active(line,False),active(full,True),active(go_of(as_full),False),active(go_of(as_line),True),
           active(dialogue,True),active(go_of(hide),True),active(go_of(show),False))
    g.edits[go_of(show)]["m_IsActive"]=False
    g.edits[go_of(as_line)]["m_IsActive"]=False
    g.wire(show,active(dialogue,True),active(go_of(hide),True),active(go_of(show),False))
    g.wire(hide,active(dialogue,False),active(go_of(show),True),active(go_of(hide),False))
    return SimpleNamespace(shared=shared,host=scene_host,dialogue=dialogue,hide=go_of(hide),show=go_of(show),
                           stat=stat,text=text,scroll=scroll,line=line,single=single,progress=progress,defaults=defaults,
                           art_button=art,art_return=hotspot,blank=blank)


def scene_view(g,scene,caption,index_page,index_button,resources,number,r,first_frame):
    viewer=g.node(r.host,"Scene_"+str(number),enabled=False)
    title=g.label(viewer,"SceneTitle",caption,(-214,477,535,62),27)
    g.edits[title].update(m_enableAutoSizing=True,m_fontSizeMin=17,m_fontSizeMax=27)
    close=g.button(viewer,"CloseScene","返回目录",(-590,477,178,62),26)
    frames=scene.get("frames",[])
    if not frames:
        raise ValueError("Empty gallery scene "+scene["id"])
    art_host,art_frames,art_forms=r.paint.scene(scene)
    def draw(i,variant=1):
        return paint_events(art_host,art_frames,i,art_forms,variant)
    racks=[g.node(viewer,"Frame"+str(i+1),enabled=False) for i in range(len(frames))]
    line_groups=[g.node(r.line,f"Lines_{number}_{i}",enabled=False) for i in range(len(frames))]
    contents=[read_lines(f,resources) or ["此画面没有对白。"] for f in frames]
    hits=[[g.hit_button(line_groups[i],"Advance"+str(n)) for n in range(len(lines))] for i,lines in enumerate(contents)]
    def show_line(i,n):
        count=len(contents[i])
        if n+1<count:
            help_text="点按对话继续"
        elif frames[i].get("branches"):
            help_text="点按选择分支"
        elif i+1<len(frames):
            help_text="点按进入下一幅"
        else:
            help_text="点按重读本幅"
        return [text_change(r.single,contents[i][n]),text_change(r.progress,f"{n+1} / {count}　{help_text}"),
                active(hits[i][n][0],True)]

    def enter(i):
        f=frames[i]
        return [active(racks[i],True),active(line_groups[i],True),text_change(r.stat,f"{i+1} / {len(frames)}"),
                text_change(r.text,"\n\n".join(contents[i])),*show_line(i,0),*[active(go,False) for go,_ in hits[i][1:]],
                event(r.scroll,"UnityEngine.UI.ScrollRect, UnityEngine.UI","StopMovement"),
                event(r.scroll,"UnityEngine.UI.ScrollRect, UnityEngine.UI","set_verticalNormalizedPosition",4,1.0),
                *draw(i)]
    def transition(i,j):
        return [active(line_groups[i],False),active(racks[i],False),*enter(j)]
    for i,(rack,f) in enumerate(zip(racks,frames)):
        for n,(hit,button) in enumerate(hits[i]):
            if n+1<len(hits[i]):
                g.wire(button,active(hit,False),*show_line(i,n+1),selected(g,hits[i][n+1][1]))
            elif i+1<len(racks):
                g.wire(button,*transition(i,i+1),selected(g,hits[i+1][0][1]))
            else:
                g.wire(button,active(hit,False),*show_line(i,0),selected(g,hits[i][0][1]))
        if len(frames)>1:
            for direction,caption in ((-1,"上一幅"),(1,"下一幅")):
                j=i+direction
                if 0<=j<len(racks):
                    step=g.text_button(rack,"Step"+str(direction),caption,(direction*235,-485,222,58),26)
                    g.wire(step,*transition(i,j))
        if f.get("layers2") is not None and f["layers2"]!=f["layers"]:
            for k,layers in enumerate((f["layers"],f["layers2"])):
                sw=g.text_button(rack,"Form"+str(k),"形象 "+str(k+1),(455+k*137,-485,124,58),24)
                g.wire(sw,*draw(i,k+1))
    spoken=any(f.get("lines") for f in frames)
    def open_at(frame):
        return [active(r.shared,True),*navigation(g,index_page,viewer),active(r.dialogue,spoken),
                active(r.hide,spoken),active(r.show,not spoken),*r.defaults,*enter(frame),
                selected(g,hits[frame][0][1] if spoken else close)]
    g.wire(index_button,*open_at(first_frame))
    # Reset the selected frame for a future visit, including a return from either protagonist variant.
    g.wire(close,active(art_host,False),active(r.shared,False),*navigation(g,viewer,index_page,index_button),
           *[active(o,False) for o in racks+line_groups])
    decisions={i:hits[i][-1][1] for i,f in enumerate(frames) if f.get("branches")}
    return SimpleNamespace(title=title,enter=open_at(0),draw=draw,art_host=art_host,viewer=viewer,states=racks+line_groups,number=number,
                           decisions=decisions,scene=scene)


APPENDICES = {"conditional":"条件事件", "random":"迷宫随机事件", "trial":"试玩结尾", "unplaced":"独立画稿"}


class Section(NamedTuple):
    caption: str
    pages: list


def category_sections(scenes, code):
    chapters = {}
    appendices = {}
    guest = []
    for scene in scenes:
        if scene["group"] == code:
            chapter = scene["chapter"]
            if chapter == 7:
                kind = scene.get("sequenceKind", "unplaced")
                appendices.setdefault(APPENDICES.get(kind, "条件事件"), []).append(scene)
            else:
                chapters.setdefault(chapter, []).append(scene)
        elif code in scene.get("alsoGroups", []):
            guest.append(scene)
    groups = [({0:"序章", 6:"终章"}.get(ch, f"第{ch}层"), chapters[ch]) for ch in sorted(chapters)]
    groups.extend((name, appendices[name]) for name in APPENDICES.values() if name in appendices)
    if guest:
        groups.append(("其他路线登场", guest))
    return [Section(caption, [rows[i:i+10] for i in range(0, len(rows), 10)]) for caption, rows in groups]


def entry_title(scene,code):
    if scene["group"]==code:
        return scene["title"]
    source=GROUPS[scene["group"]] if scene["group"]!="Shared" else "共通"
    return f"{source} · {scene['title']}"


def build_branches(g,views,shared,resources):
    by_id={view.scene["id"]:view.scene for view in views.values()}
    def menu(code,view,choices,trigger,suffix):
        ids=[item["sceneId"] for item in choices]
        if len(ids)!=len(set(ids)):
            raise ValueError("Expected distinct confirmed choice destinations in "+view.scene["id"])
        prompt=g.page("Branches_"+view.number+suffix,"剧情分支","选择原作选项，查看对应的画面与对白。")
        back=g.button(prompt,"BackToScene","返回当前画面",(0,-405,350,70))
        g.wire(back,active(shared.host,True),active(shared.shared,True),selected(g,trigger),active(prompt,False))
        first=None
        for n,item in enumerate(choices):
            target=by_id[item["sceneId"]]
            dest=views.get((code,target["id"]),views[(target["group"],target["id"])])
            choice={**item["choice"],"speaker":"","kind":"text"}
            name=read_frame({"lines":[choice]},resources)
            if not name:
                raise ValueError("Empty translated choice in "+view.scene["id"])
            if len(choices)<=5:
                box=(0,200-n*100,920,78)
            else:
                box=((n%2-.5)*640,215-(n//2)*97,612,78)
            button=g.button(prompt,"Choose"+str(n),name,box,31)
            g.edits[g.button_labels[button]].update(m_enableAutoSizing=True,m_fontSizeMin=20,m_fontSizeMax=31)
            first=first or button
            g.wire(button,active(prompt,False),active(view.art_host,False),active(view.viewer,False),*[active(o,False) for o in view.states],
                   active(shared.host,True),*dest.enter)
        g.wire(trigger,active(prompt,True),selected(g,first),active(shared.shared,False),active(shared.host,False))
    for (code,_),view in views.items():
        choices=view.scene.get("branches",[])
        if choices:
            picker=g.text_button(view.viewer,"BranchPicker","剧情分支",(-540,-485,220,58),26)
            menu(code,view,choices,picker,"")
        for i,trigger in view.decisions.items():
            menu(code,view,view.scene["frames"][i]["branches"],trigger,"_Frame"+str(i))


def build(g,catalog,game,*,background_index=None):
    resource=Path(game)/"Annihilated_Data"/"resources.assets"
    if resource.stat().st_size!=catalog["resourcesSize"]:
        raise ValueError("Installed dialogue asset size differs from the gallery catalog")
    assets=catalog["assets"]
    if any(a["id"]!=i for i,a in enumerate(assets)):
        raise ValueError("Non-contiguous gallery asset IDs")
    warnings=[]
    previews=[]
    views={}
    shared=reader(g)
    shared.paint=Paint(g,game,catalog,background_index=background_index)
    with resource.open("rb") as resources:
        for k,(code,caption) in enumerate(GROUPS.items()):
            sections=category_sections(catalog["scenes"],code)
            if not sections:
                continue
            group=g.button(g.home,"Group"+code,caption,((k%2-.5)*600,235-(k//2)*130,565,92))
            chooser=g.page(code+"Chapters",caption,"选择章节")
            home=g.button(chooser,"Back","返回画廊",(0,-405,295,70))
            g.wire(home,*navigation(g,chooser,g.home,group))
            page_rows=[]
            spacing=min(118,550/max(1,(len(sections)-1)//2))
            for i,section in enumerate(sections):
                choose=g.button(chooser,"Section"+str(i),section.caption,((i%2-.5)*600,232-(i//2)*spacing,565,min(90,spacing-10)),31)
                if i==0:
                    g.wire(group,*navigation(g,g.home,chooser,choose))
                start=len(page_rows)
                count=len(section.pages)
                pages=[g.page(code+str(start+p),section.caption,f"{caption}　·　第 {p+1} / {count} 页") for p in range(count)]
                g.wire(choose,*navigation(g,chooser,pages[0]))
                for p,page in enumerate(pages):
                    back=g.button(page,"Back","返回章节",(0,-405,295,70))
                    g.wire(back,*navigation(g,page,chooser,choose))
                    for direction,cap in ((1,"下一页"),(-1,"上一页")):
                        if 0<=p+direction<count:
                            step=g.button(page,"Step"+str(direction),cap,(direction*340,-405,290,70))
                            g.wire(step,*navigation(g,page,pages[p+direction]))
                    page_rows.append((page,section.pages[p]))
            for j,(page,rows) in enumerate(page_rows):
                preview=g.node(g.gallery,f"Preview_{code}_{j}",enabled=False)
                band=g.node(preview,"PreviewCaption",(0,470,1380,74))
                g.graphic(band,rgba(.04,.065,.085,.92),False)
                preview_caption=g.label(band,"PreviewName","",None,28)
                g.edits[preview_caption].update(m_enableAutoSizing=True,m_fontSizeMin=18,m_fontSizeMax=28)
                done=g.button(preview,"BackToIndexPage","返回本页",(0,-477,250,62),25)
                preview_hosts=[]
                for n,scene in enumerate(rows):
                    name=entry_title(scene,code)
                    row=g.button(page,"SceneButton"+str(n),name,((n%2-.5)*680,232-(n//2)*118,650,90),28)
                    row_label=g.edits[g.button_labels[row]]
                    row_label.update(m_enableAutoSizing=True,m_fontSizeMin=18,m_fontSizeMax=28,
                                     m_margin={"x":18,"y":2,"z":110,"w":2})
                    first_frame=scene.get("alsoFrames",{}).get(code,0)
                    if not 0<=first_frame<len(scene["frames"]):
                        raise ValueError("Invalid first frame for "+scene["id"]+" in "+code)
                    view=scene_view(g,scene,name,page,row,resources,f"{code}_{j}_{n}",shared,first_frame)
                    views[(code,scene["id"])]=view
                    reveal=scene.get("reveal","")
                    if scene.get("choice"):
                        choice=read_frame({"lines":[scene["choice"]]},resources)
                        if choice:
                            reveal=(reveal+" · " if reveal and reveal!=scene["title"] else "")+choice
                    detail=[s for s in (scene.get("sequenceNote"),reveal) if s and s!=scene["title"]]
                    reveal=" · ".join(dict.fromkeys(detail))
                    if reveal:
                        warnings.append((g.button_labels[row],name,name+"　"+reveal))
                        warnings.append((view.title,name,name+"　"+reveal))
                    eye=g.button(page,"Preview"+str(n),"预览",((n%2-.5)*680+268,232-(n//2)*118,94,66),23)
                    eye_go=g.edits[eye]["m_GameObject"]["m_PathID"]
                    g.edits[eye_go]["m_IsActive"]=False
                    previews.append(eye_go)
                    preview_hosts.append(view.art_host)
                    preview_name="　".join(s for s in (name,reveal) if s)
                    g.wire(eye,*navigation(g,page,preview,done),text_change(preview_caption,"原画预览　"+preview_name),
                           *view.draw(first_frame))
                g.wire(done,*[active(host,False) for host in preview_hosts],*navigation(g,preview,page))
        build_branches(g,views,shared,resources)
    g.wire(shared.art_button,*shared.paint.framing_calls(True),active(shared.blank,True),
           selected(g,shared.art_return),active(shared.shared,False),active(shared.host,False))
    g.wire(shared.art_return,*shared.paint.framing_calls(False),active(shared.host,True),active(shared.shared,True),
           selected(g,shared.art_button),active(shared.blank,False))
    if shared.paint.background_renderer:
        shared.paint.background_renderer.close()
    on=g.button(g.home,"EnableSpoilers","开启剧透预览",(0,-210,380,75),30)
    off=g.button(g.home,"DisableSpoilers","关闭剧透预览",(0,-210,380,75),30)
    on_go=g.edits[on]["m_GameObject"]["m_PathID"]
    off_go=g.edits[off]["m_GameObject"]["m_PathID"]
    g.edits[off_go]["m_IsActive"]=False
    g.wire(on,*[text_change(t,r) for t,s,r in warnings],*[active(o,True) for o in previews],
           active(off_go,True),selected(g,off),active(on_go,False))
    g.wire(off,*[text_change(t,s) for t,s,r in warnings],*[active(o,False) for o in previews],
           active(on_go,True),selected(g,on),active(off_go,False))
