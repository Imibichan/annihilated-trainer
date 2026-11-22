"""Complete ordinary dungeon encounters, including the original choice and roulette handlers."""
import re


TITLES = {
    1: "坍塌的天花板", 2: "黑暗中的轰鸣", 3: "荆棘悬崖", 4: "石像通道",
    5: "遗落的箱子", 6: "游动的微光", 7: "黑暗的深坑", 8: "迷宫陷阱", 9: "水面倒影",
    10: "牢房中的人影", 11: "铁门后的烈焰", 12: "迷雾之室", 13: "持镰的身影",
    14: "飞来的箭矢", 15: "柱后的魔物", 16: "邪神像", 17: "高处的黑暗",
    18: "幸福之室", 19: "落下的铁柱", 20: "书房里的药瓶", 21: "镜中的人影",
    22: "台座上的石板", 23: "发光的蘑菇", 24: "飞奔的金枪鱼", 25: "金币之路",
    27: "倒下的尸体", 28: "披袍的祈祷者", 29: "闪光的泉水", 30: "绞肉机",
}
TARGET = re.compile(r'(?:^@(?:goto|gosub)\s+|\s+goto:)\s*"?([.\w{}]+)', re.I)
TAG = re.compile(r"\[([a-zA-Z_][a-zA-Z_0-9]*)\]\[[a-zA-Z_]+:")
EXTERNAL = {
    "Func": set("Damage DamageAll Death Heal SanityDamage SanityDamageAll SanityHeal forwardDamage "
                "RemoveItemOnlyDelete ResetItemChoiceCommand itemCardSelection".split()),
    "StatusFunc": {"GainExp"},
}
HELPERS = set("beforeEventChoice createRouletteGoto GetEventItem RollEventItemDiscovery backEvents eventDeath "
              "EnemyEncounter DungeonBattle Treasure GetTreasure".split())
PREP = "V15PrepareRandomEvent"


def _labels(rows):
    return {r[3].strip().lstrip("#").strip(): idx for idx, r in enumerate(rows) if r[1] == "Label"}


def _require(lines, *commands):
    absent = [cmd for cmd in commands if cmd not in lines]
    if absent:
        raise ValueError(f"迷宫事件的原作调度发生变化：{absent[0]}")


def _wrapper(rows, labels):
    lines = [r[3].strip() for r in rows]
    body = lines[labels["events"]:labels["ShowEventIllustration"]]
    event_call = "@gosub .event{nowEvent}"
    image = "@gosub .ShowEventIllustration if:nowEvent>=1&&nowEvent<=30&&nowEvent!=26"
    _require(body, image, event_call, "@gosub .eventRecord", "@gosub .afterEvent", "@return")
    _require(lines, "@set nowEvent=GetMapSpaceOption({dungeonX},{mapChosenSpaceY})",
             '@set tempTargetName="DungeonEvent/{nowEvent}Me{playerType}"',
             '@goto .event{eventNum}_{eventName}', '@goto ".event{eventNum}_roulette"',
             "@gosub .roulette_{rouletteResult}", "@goto .events")
    i = body.index(event_call)
    before = [cmd for cmd in body[:i] if cmd.startswith("@") and "if:nowEvent>=500" not in cmd]
    after = [cmd for cmd in body[i+1:] if cmd.startswith("@") and "if:nowEvent>=500" not in cmd and cmd != "@return"]
    # Relocated host commands which invoke a subroutine must keep their original script scope.
    before = [cmd.replace("@gosub .", "@gosub Dungeon.") if cmd != image else "@gosub Dungeon.ShowEventIllustration"
              for cmd in before]
    after = [cmd.replace("@gosub .", "@gosub Dungeon.") for cmd in after]
    return before, after


def _check_event(number, body, label_maps):
    label = f"event{number}"
    locals_ = _labels(body)
    commands = [r[3].strip() for r in body if r[1] == "Command"]
    if not any(r[1] == "GenericText" for r in body) or "@return" not in commands:
        return [], 0, ["没有完整叙事或原作返回点"]
    if f"@set eventNum={number}" not in commands or label + "_roulette" not in locals_:
        return [], 0, ["缺少原作事件编号或选项入口"]
    issues, calls = set(), set()
    branches = 0
    dynamic_tag = None
    for line in commands:
        if re.match(r"@set tempEventTag=", line):
            tag = TAG.search(line)
            dynamic_tag = tag[1] if tag else None
        match = TARGET.search(line)
        if not match:
            continue
        target = match[1]
        script, _, name = target.partition(".")
        if script and script != "Dungeon":
            if name not in EXTERNAL.get(script, ()) or name not in label_maps.get(script, {}):
                issues.add("外部调用 " + target)
            continue
        if name not in label_maps["Dungeon"]:
            issues.add("缺少跳转 " + target)
            continue
        if name not in locals_ and name not in HELPERS:
            issues.add("事件外部转移 " + target)
        calls.add(name)
        if line.startswith("@choice "):
            branches += 1
            if name == "createRouletteGoto":
                tag = TAG.search(line)
                action = tag[1] if tag else dynamic_tag if "{tempEventTag}" in line else None
                if not action or f"{label}_{action}" not in locals_:
                    issues.add(f"缺少轮盘结果 {action}")
    if not branches:
        issues.add("缺少玩家的原作选择")
    # Backtracking presents its original effects, then yields before dispatching a different event.
    exits = set()
    if "backEvents" in calls:
        exits.add("Dungeon.events")
    if "eventDeath" in calls:
        exits.add("GameOver.gameover")
    if calls & {"EnemyEncounter", "DungeonBattle"}:
        exits.add("Battle.InitializeCommand")
    if "Treasure" in calls:
        exits.add("Dungeon.Treasure")
    return sorted(exits), branches, sorted(issues)


def build_dungeon_scenes(scripts, gallery):
    rows = scripts["Dungeon"]
    maps = {name: _labels(scripts.get(name, ())) for name in ("Dungeon", "Func", "StatusFunc", "Battle", "GameOver")}
    labels = maps["Dungeon"]
    before, after = _wrapper(rows, labels)
    if __package__:
        from .source_anchors import resolve_gallery
    else:
        from source_anchors import resolve_gallery
    mapped, _ = resolve_gallery(scripts, {"scenes": [s for s in gallery["scenes"] if s.get("source") == "Dungeon"]})
    original_art = [s for s in mapped if s['source'] == 'Dungeon']
    records = []
    for n, title in TITLES.items():
        label = f"event{n}"
        if label not in labels:
            continue
        start = labels[label]
        end = min([labels[f"event{k}"] for k in TITLES if f"event{k}" in labels and labels[f"event{k}"] > start]
                  + [labels["SpecialEvent"]])
        exits, choices, issues = _check_event(n, rows[start:end], maps)
        linked = [r["id"] for r in original_art if start <= r["line"] < end]
        if not linked:
            issues.append("原作画稿映射缺失")
        for target in exits:
            source, stop = target.split(".", 1)
            if stop not in maps[source]:
                issues.append("缺少原作结束点 " + target)
        setup = [f"@gosub Dungeon.{PREP}", f"@set nowEvent={n}"]
        # These decisions explicitly depend on a real inventory slot and the soldier's sanity.
        # Configure a valid inventory before presenting the game's own choices.
        if n in (29, 30):
            setup.extend(['@set addItem="powerSeed"', "@gosub Func.AddItem"])
        if n == 30:
            setup.extend(["@set playerSanity=50", "@gosub Func.UpdateSanityEffect"])
        records.append(dict(id="Dungeon." + label, group="Shared", chapter=8, title=title,
                            source="Dungeon", label=label, line=start, setupCommands=setup + before,
                            finishCommands=list(after), exits=exits, naturalReturn=True, naturalTitle=False,
                            boundary="return", choices=choices, galleryIds=linked, issues=issues,
                            status="candidate" if issues else "script-reviewed",
                            evidence="原作事件编号、轮盘与选项回调、探索或战斗指令边界"))
    return records


def add_dungeon_helpers(edits, scripts):
    """Append the common ordinary-tile context once. No story choices are made here."""
    if PREP in _labels(scripts["Dungeon"]):
        raise ValueError("迷宫事件准备标签已被占用。")
    extra = edits.setdefault("Dungeon", {})
    start = max([len(scripts["Dungeon"])] + [i+1 for i in extra])
    lines = [
        "# " + PREP, '@set partnerCharacter="hero"', '@set tempCharacter="partner"',
        "@gosub Func.InitializePartnerCharacterState", "@gosub StatusFunc.StatusSetting",
        "@set partnerHealth=partnerMaxHealth", "@set xSwitchShowAttackModeChangeChoiceSelected=1",
        "@set dungeonId=1", "@set sectionId=1", "@gosub Dungeon.MapReset",
        '@set backgroundName="dungeon_blue"', "@gosub Func.ShowBackground", "@bgm m2_loop intro:m2_intro",
        "@set showPlayerStatus=true", "@set showPartnerStatus=true", "@set showCurse=true",
        "@set switchShowItem=1", "@showUI PlayerStatusUI", "@set showMap=false",
        '@set dungeonSpaceType="random"',
        "@vcam offset:0,0,{vcamDefaultZ} rotation:0,0,0 time:0 wait:false", "@return",
    ]
    # Animation, UI, music and @return carry engine-specific serialized fields.
    # Relocate the native compiled command by its source identity.
    native = {r[3].strip(): (name, r[0]) for name, rows in scripts.items() for r in rows if r[1] == "Command"}
    for idx, line in enumerate(lines, start):
        if line.startswith(("#", "@set ", "@gosub ")):
            extra[idx] = line
        elif line in native:
            extra[idx] = native[line]
        else:
            raise ValueError(f"缺少迷宫演出原生指令：{line}")
