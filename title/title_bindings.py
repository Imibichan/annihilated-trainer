"""Identify the game's native title controls and trusted UGUI donors by their actual structure."""
from dataclasses import dataclass
from pathlib import Path


TITLE_PATH = "Assets/NaninovelCustom/UI/CustomTitleUI.prefab"
UI = "UnityEngine.UI"
NANI = "Elringus.Naninovel.Runtime"
# For tools working on a detached copy of the original bundle. Installed games resolve
# scripts from their actual localized CAB names and MonoScript metadata.
STOCK_SCRIPT_CAB = "cab-b904b7e2798c20f35188704be3f11845"
SCRIPTS = {
    (UI,"UnityEngine.UI.Image"):350208831926335389,
    (UI,"UnityEngine.UI.RawImage"):8211606541286769707,
    (UI,"UnityEngine.UI.Button"):-4448497653027179337,
    (UI,"UnityEngine.UI.Mask"):-3041394055549590798,
    (UI,"UnityEngine.UI.ScrollRect"):6814249547350465190,
    (UI,"UnityEngine.UI.ContentSizeFitter"):93356951997354507,
    ("Unity.TextMeshPro","TMPro.TextMeshProUGUI"):7477354737935883349,
    ("Assembly-CSharp","LocalizeFontOnTMP"):8560103588736675248,
    (NANI,"Naninovel.LabeledButton"):6658091400824965451,
    (NANI,"Naninovel.ManagedTextProvider"):594341380326793506,
    (NANI,"Naninovel.UI.TitleCGGalleryButton"):-4107588534935290337,
}
STOCK_SCRIPTS={n:key for key,n in SCRIPTS.items()}


@dataclass(frozen=True)
class TitleBinding:
    title_path: str
    root: int
    root_rect: int
    buttons: int
    entry: int
    entry_button: int
    entry_label: int
    entry_text: int
    entry_driver: int
    label_driver: int
    standard_button: int
    graphic: int
    renderer: int
    rect: int
    font_localizer: int
    canvas_group: int
    title_art: tuple
    raw_image: int
    scroll: int
    mask: int
    fitter: int


def unique(items, description):
    if len(items)!=1:
        raise ValueError(f"Expected one {description}, found {len(items)}")
    return items[0]


def asset_root(env, name):
    return unique([(path,ref) for path,ref in env.container.items()
                   if path.rsplit("/",1)[-1].lower()==name.lower()+".prefab"],name+" prefab")


def script_definitions(game, needed):
    if game is None:return {}
    import UnityPy
    folder=Path(game)/"Annihilated_Data"/"StreamingAssets"/"aa"/"StandaloneWindows64"
    result={}
    for path in sorted(folder.glob("*.bundle")):
        if "monoscript" not in path.name.lower():continue
        candidate=UnityPy.load(path.read_bytes())
        for key,file in candidate.file.files.items():
            cab=key.lower()
            if cab not in needed:continue
            rows={}
            for obj in file.objects.values():
                if obj.type.name=="MonoScript":
                    value=obj.read()
                    rows[obj.path_id]=(value.m_AssemblyName.removesuffix(".dll"),
                                      ".".join(filter(None,(value.m_Namespace,value.m_ClassName))))
            if rows:
                if cab in result and result[cab]!=rows:
                    raise ValueError("Ambiguous MonoScript dependency "+cab)
                result[cab]=rows
    return result


class Prefab:
    def __init__(self,env,game=None):
        self.env=env
        self.title_path,ref=asset_root(env,"CustomTitleUI")
        self.root=ref.path_id
        self.file=ref.deref().assets_file
        self.rows={}
        self.cabs=[x.path.replace(chr(92),"/").rsplit("/",1)[-1].lower() for x in self.file.externals]
        self.scripts=script_definitions(game,set(self.cabs))

    def row(self,oid):
        if oid not in self.rows:
            if oid not in self.file.objects:raise ValueError(f"Missing prefab object {oid}")
            self.rows[oid]=self.file.objects[oid].read_typetree()
        return self.rows[oid]

    def kind(self,oid):
        native=self.file.objects[oid].type.name
        if native!="MonoBehaviour":return native
        p=self.row(oid)["m_Script"]
        index=p["m_FileID"]-1
        if not 0<=index<len(self.cabs):return None
        cab=self.cabs[index]
        if cab in self.scripts:return self.scripts[cab].get(p["m_PathID"])
        if cab==STOCK_SCRIPT_CAB:return STOCK_SCRIPTS.get(p["m_PathID"])
        return None

    def components(self,go):
        return [r["component"]["m_PathID"] for r in self.row(go)["m_Component"] if not r["component"]["m_FileID"]]

    def component(self,go,kind,fields=()):
        oid=unique([i for i in self.components(go) if self.kind(i)==kind],f"{kind} on {self.row(go)['m_Name']}")
        data=self.row(oid)
        if data["m_GameObject"]!={"m_FileID":0,"m_PathID":go} or not set(fields)<=data.keys():
            raise ValueError("Incompatible component fields or owner for "+str(kind))
        return oid

    def rect(self,go):
        return self.component(go,"RectTransform",("m_Children","m_Father","m_AnchorMin","m_AnchorMax",
                                                  "m_AnchoredPosition","m_SizeDelta","m_Pivot","m_LocalRotation"))

    def children(self,go):
        rect=self.rect(go)
        result=[]
        for child in self.row(rect)["m_Children"]:
            if child["m_FileID"]:raise ValueError("External child in prefab hierarchy")
            row=self.row(child["m_PathID"])
            if row["m_Father"]!={"m_FileID":0,"m_PathID":rect}:raise ValueError("Broken prefab parent")
            result.append(row["m_GameObject"]["m_PathID"])
        return result

    def descend(self,go,path):
        for name in path.split("/"):
            go=unique([c for c in self.children(go) if self.row(c)["m_Name"]==name],name+" child")
        return go

    def donor_owner(self,root,relative,kind):
        names=relative.split("/")
        ancestors=[root]
        for name in names:
            found=[c for c in self.children(ancestors[-1]) if self.row(c)["m_Name"]==name]
            if not found:break
            ancestors.append(unique(found,name+" template child"))
        else:
            return ancestors[-1]
        # Search the nearest remaining container first. A renamed visual donor is
        # interchangeable only if its original native component is unambiguous.
        for parent in reversed(ancestors):
            pending=[parent]
            visited=set()
            matches=[]
            while pending:
                go=pending.pop()
                if go in visited:raise ValueError("Cycle in template hierarchy")
                visited.add(go)
                comps=self.components(go)
                if any(self.kind(i)==kind for i in comps):matches.append(go)
                tr=self.row(comps[0])
                for ref in tr.get("m_Children",()):
                    pending.append(self.row(ref["m_PathID"])["m_GameObject"]["m_PathID"])
            if matches:
                named=[go for go in matches if self.row(go)["m_Name"]==names[-1]]
                return unique(named or matches,str(kind)+" template in "+self.row(parent)["m_Name"])
        raise ValueError("Missing native gallery template "+relative)

    def donor(self,path,kind,fields):
        first,*relative=path.split("/",1)
        _,ref=asset_root(self.env,first)
        if ref.deref().assets_file is not self.file:raise ValueError("Template belongs to another asset file")
        go=self.donor_owner(ref.path_id,relative[0],kind) if relative else ref.path_id
        result=self.component(go,kind,fields)
        row=self.row(result)
        # The builder will clone this component, including any pre-existing events.
        for field,value in row.items():
            if isinstance(value,dict) and "m_PersistentCalls" in value and value["m_PersistentCalls"]["m_Calls"]:
                raise ValueError(f"Unexpected {field} events on gallery template {path}")
        return result


def validate_stock(env, game=None):
    """Resolve every required template and confirm the vanilla title slot can be repurposed."""
    try:return _validate_stock(env,game)
    except (KeyError,IndexError,TypeError,AttributeError) as error:
        raise ValueError("Incompatible native title prefab structure") from error


def _validate_stock(env,game):
    view=Prefab(env,game)
    root=view.root
    row=view.row
    if row(root)["m_Name"]!="CustomTitleUI" or any(row(c)["m_Name"]=="MemoryGallery" for c in view.children(root)):
        raise ValueError("Expected the original CustomTitleUI without an installed gallery")
    buttons=view.descend(root,"ButtonsPanel")
    entry=view.descend(buttons,"CGGalleryButton")
    label=view.descend(entry,"CgGalleryLabel")
    component=view.component
    def ui(name):return (UI,"UnityEngine.UI."+name)
    provider=component(label,(NANI,"Naninovel.ManagedTextProvider"),("category","key","onValueChanged"))
    if row(provider)["key"]!="TitleMenu.CGGallery":raise ValueError("Unexpected native title label provider")
    driver=component(entry,(NANI,"Naninovel.UI.TitleCGGalleryButton"),("onShow","onHide"))
    btn=component(entry,(NANI,"Naninovel.LabeledButton"),("m_OnClick","m_TargetGraphic","m_Interactable"))
    graphic=component(entry,ui("Image"),("m_Sprite","m_Type","m_Color","m_Material","m_RaycastTarget"))
    text=component(label,("Unity.TextMeshPro","TMPro.TextMeshProUGUI"),
                   ("m_text","m_fontSize","m_isRichText","m_enableAutoSizing","m_margin","m_RaycastTarget"))
    events=row(provider)["onValueChanged"]["m_PersistentCalls"]["m_Calls"]
    if (row(btn)["m_OnClick"]["m_PersistentCalls"]["m_Calls"] or
        row(btn)["m_TargetGraphic"]!={"m_FileID":0,"m_PathID":graphic} or
        len(events)!=1 or events[0]["m_MethodName"]!="set_text" or
        events[0]["m_Target"]!={"m_FileID":0,"m_PathID":text}):
        raise ValueError("Unexpected native title control callbacks")
    group=component(root,"CanvasGroup",("m_Alpha","m_Interactable","m_BlocksRaycasts"))
    art=tuple(view.descend(root,name) for name in ("TitleImageRight","TitleImageLeft","Logo"))
    for go in art:
        if any(view.kind(k)=="CanvasGroup" for k in view.components(go)):
            raise ValueError("Title illustration already owns a CanvasGroup")
    donor=view.donor
    standard=donor("CustomSaveLoadUI/Content/LoadPanel/PaginationPanel/NextPageButton",
                   ui("Button"),("m_Navigation","m_Colors","m_TargetGraphic","m_OnClick"))
    raw=donor("CustomSaveLoadUI/Content/SavePanel/PaginationPanel/NextPageButton/Icon",ui("RawImage"),
              ("m_Texture","m_UVRect","m_Material","m_RaycastTarget"))
    scroll=donor("CustomLoadingUI/Content/LoadLoggerScrollRect",ui("ScrollRect"),
                 ("m_Content","m_Viewport","m_ScrollSensitivity","m_Vertical","m_Horizontal","m_OnValueChanged"))
    mask=donor("PlayerStatusUI/VideoRecordingVisibility/StatusVerticalContainer/PartyStatusContainer/"
               "StatusTooltipContainer/PartnerTooltipParent/StatusTooltip (1)/BackImage/StatusFaceMask",
               ui("Mask"),("m_ShowMaskGraphic",))
    fitter=donor("CustomSaveLoadUI/Content",ui("ContentSizeFitter"),("m_HorizontalFit","m_VerticalFit"))
    font=donor("CustomTitleUI/ButtonsPanel/NewGameButton/NewGameLabel",("Assembly-CSharp","LocalizeFontOnTMP"),
               ("fontSettings","enableDebugLog"))
    bundle=unique([i for i,v in view.file.objects.items() if v.type.name=="AssetBundle"],"asset index")
    table=row(bundle)
    record=unique([v for k,v in table["m_Container"] if k==view.title_path],"title preload record")
    start,size=record["preloadIndex"],record["preloadSize"]
    if start<0 or size<=0 or start+size>len(table["m_PreloadTable"]) or record["asset"]!={"m_FileID":0,"m_PathID":root}:
        raise ValueError("Invalid title preload range")
    return TitleBinding(view.title_path,root,view.rect(root),buttons,entry,btn,label,text,driver,provider,standard,
                        graphic,component(entry,"CanvasRenderer"),view.rect(label),font,group,art,raw,scroll,mask,fitter)


def validate_modified(env,binding):
    """Check the saved result against the roots resolved from this particular vanilla build."""
    view=Prefab(env)
    if (view.title_path,view.root)!=(binding.title_path,binding.root):
        raise ValueError("Generated bundle no longer contains the original title prefab")
    gallery=view.descend(view.root,"MemoryGallery")
    home=view.descend(gallery,"GalleryIndex")
    if (view.row(gallery)["m_IsActive"] or not view.row(home)["m_IsActive"]
            or not view.row(binding.entry)["m_IsActive"] or view.row(binding.entry_text)["m_text"]!="CG 鉴赏"
            or binding.entry_driver in view.components(binding.entry)
            or binding.label_driver in view.components(binding.entry_label)):
        raise ValueError("Invalid initial gallery state")
    calls=view.row(binding.entry_button)["m_OnClick"]["m_PersistentCalls"]["m_Calls"]
    if (len(calls)<2 or calls[0]["m_MethodName"]!="SetActive"
            or calls[0]["m_Target"]!={"m_FileID":0,"m_PathID":gallery}
            or not calls[0]["m_Arguments"]["m_BoolArgument"]):
        raise ValueError("Native title button has no gallery action")
    return gallery
