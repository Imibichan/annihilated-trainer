"""Compose the replay directory and guards, preserving the game's own story lines."""
from collections import defaultdict
import hashlib
import re


ROLES = {"Shared":"共通", "Hero":"勇者", "Mage":"魔法师", "Warrior":"战士", "Priest":"僧侣"}
PAGE_SIZE = 4
MENU = "Test2"


def unique(rows, predicate, description):
    hits = [r[0] for r in rows if predicate(r)]
    if len(hits) != 1:
        raise ValueError(f"无法唯一定位 {description}（{len(hits)} 处）")
    return hits[0]


def label_at(rows, name):
    return unique(rows, lambda r: r[1] == "Label" and r[3].strip().lstrip("#").strip() == name, name)


def choices(text, target, condition=None):
    if any(c in text for c in '"\r\n'):
        raise ValueError("目录标题有不支持的字符")
    return f'@choice "{text}" goto:.{target}' + (f" if:{condition}" if condition else "")


def builtins():
    return [
        {"id":"opening", "group":"Shared", "chapter":0, "title":"序章开场",
         "source":"Opening", "label":"Start", "setupCommands":[],
         "exits":["Battle.InitializeCommand"], "status":"script-reviewed"},
        {"id":"tutorial-break", "group":"Shared", "chapter":0, "title":"教学战 · 第一次破防",
         "source":"Opening", "label":"TutorialSlimeBattleBefore", "status":"script-reviewed",
         "setupCommands":['@set xSwitchOpening1=1;backgroundName="dungeon_blue";backgroundSetOption="dungeon_blue_blood"',
                          "@gosub Func.HideBackground", "@gosub Func.ShowBackground",
                          "@set v15Tutorial=1"], "exits":[]},
    ]


def make_program(scripts, scenes, artworks, assets=()):
    from scenes import story_reset_commands
    edits = defaultdict(dict)
    tape = []
    exit_rules = defaultdict(list)
    automatic_actions = {}
    stock = {}
    for name, rows in scripts.items():
        for idx, kind, _, raw, *_ in rows:
            line = raw.strip()
            if kind == "Command":
                stock.setdefault(line, (name, idx))
                if line.lower().startswith("@steamachievement "):
                    edits[name][idx] = ";"

    def donor(line):
        if isinstance(line, (list,tuple)):
            return tuple(line)
        # Relative jumps must resolve within the script where they were authored.
        if line in stock and not re.search(r"@(?:goto|gosub)\s+\.", line, re.I):
            return stock[line]
        return line

    def emit(*rows):
        tape.extend(rows)

    def switch_lead_choice(page):
        emit(choices("切换主角（当前为女主角）", "Change"+page, "G_v15Lead==1"),
             choices("切换主角（当前为男主角）", "Change"+page, "G_v15Lead==2"))

    def page(name, items, parent=None):
        emit("# " + name, "@clearChoice *", "@hidePrinter")
        for title, target in items:
            emit(choices(title, target))
        if parent:
            emit(choices("返回上一级", parent))
        else:
            switch_lead_choice(name)
        emit("@stop")

    def chapter_name(n):
        return {0:"序章", 6:"终章", 7:"其他回忆", 8:"迷宫偶遇"}.get(n, f"第 {n} 层")

    all_scenes = builtins() + [s for s in scenes if s["status"] in {"script-reviewed","live-verified"}]
    active = []
    sections = defaultdict(list)
    for scene in all_scenes:
        if any(x["id"] == scene["id"] for x in active):
            continue
        active.append(scene)
        sections[(scene["group"], scene["chapter"])].append((len(active),scene))
    art_rows = [(len(active) + i, a) for i,a in enumerate(artworks,1)]
    # Keep the last item stable when a game update adds other scenes earlier in its route.
    objects = active + list(artworks)
    keys = {i:int.from_bytes(hashlib.sha256(obj["id"].encode()).digest()[:3],"big")
            for i,obj in enumerate(objects,1)}
    if len(set(keys.values())) != len(keys) or 0 in keys.values():
        raise ValueError("场景标记重复，无法可靠保存目录位置")
    if art_rows:
        sections[("Art",0)] = art_rows
    groups = [g for g in ROLES if any(k[0] == g for k in sections)]
    top = [(ROLES[g], "G"+g) for g in groups]
    if art_rows:
        top.append(("独立画稿","PArt0x0"))
    emit("# Resume", "@hideUI TitleUI", "@clearChoice *", "@hidePrinter",
         "@gosub .ChooseLead if:G_v15Lead!=1&&G_v15Lead!=2")
    pages = []
    for (group,chapter), items in sections.items():
        parts = [items[i:i+PAGE_SIZE] for i in range(0,len(items),PAGE_SIZE)]
        for j, part in enumerate(parts):
            key = f"P{group}{chapter}x{j}"
            pages.append((group, chapter, j, key, part, len(parts)))
            for idx, _ in part:
                emit(f"@goto .{key} if:G_v15Last=={keys[idx]}")
    emit("@goto .Home")
    page("Home", top)
    for group in groups:
        chapters = sorted(ch for g,ch in sections if g == group)
        page("G"+group, [(chapter_name(ch),f"P{group}{ch}x0") for ch in chapters], "Home")
    for group,chapter,j,key,part,count in pages:
        emit("# "+key, "@clearChoice *", "@hidePrinter")
        for idx, obj in part:
            caption = obj["title"]
            emit(choices("◆ "+caption,f"S{idx}",f"G_v15Last=={keys[idx]}"),
                 choices(caption,f"S{idx}",f"G_v15Last!={keys[idx]}"))
        if j:
            emit(choices("上一页",f"P{group}{chapter}x{j-1}"))
        if j+1 < count:
            emit(choices("下一页",f"P{group}{chapter}x{j+1}"))
        switch_lead_choice(key)
        emit(choices("返回上一级","Home" if group == "Art" else "G"+group), "@stop")
    for origin in ["Home"] + [p[3] for p in pages]:
        emit("# Change"+origin, "@gosub .ChooseLead", "@goto ."+origin)
    emit("# ChooseLead", "@clearChoice *", "@hidePrinter",
         choices("使用女主角", "ChooseFemale"), choices("使用男主角", "ChooseMale"), "@stop",
         "# ChooseFemale", "@set G_v15Lead=1", donor("@return"),
         "# ChooseMale", "@set G_v15Lead=2", donor("@return"))
    for idx, scene in enumerate(active,1):
        emit(f"# S{idx}", f"@set G_v15Last={keys[idx]}", "@clearChoice *")
        presets = [r for r in scene.get("presets",[]) if r.get("status","script-reviewed") in {"script-reviewed","live-verified"}]
        if len(presets)>1:
            for n,preset in enumerate(presets):
                emit(choices(preset["title"],f"S{idx}v{n}"))
            emit("@stop")
        for n,preset in enumerate(presets or [scene]):
            flag = idx*100+n+1
            emit(f"# S{idx}v{n}", "@gosub First.InitialSettings", "@gosub .ResetProgress", "@gosub .ApplyLead",
                 f"@set v15Scene={flag};v15Tutorial=0;v15ActionIssued=0;v15AutoTiming=0")
            action = preset.get("actionAtFirstCommand",scene.get("actionAtFirstCommand"))
            if action:
                automatic_actions[flag] = action
                if action.get("skipTiming"):
                    emit("@set v15AutoTiming=1")
            for cmd in preset.get("setupCommands", scene["setupCommands"]):
                emit(donor(cmd))
            destination = scene["source"] + ("."+scene["label"] if scene["label"] else "")
            emit("@gosub "+destination)
            for cmd in preset.get("finishCommands", scene.get("finishCommands", [])):
                emit(donor(cmd))
            emit("@goto .Finish")
            for target in preset.get("exits",scene["exits"]):
                if target != "@title":
                    exit_rules[target].append(flag)
    measurements = {a["id"]:a for a in assets}
    for idx, art in art_rows:
        frame = art["frames"][0]
        emit(f"# S{idx}",f"@set G_v15Last={keys[idx]}","@clearChoice *","@hidePrinter")
        variants = ("", "2") if frame.get("bindings2") else ("",)
        if len(variants) == 2:
            emit(f"@goto .A{idx}v1 if:G_v15Lead==2")
        from artwork_scale import contain_scale
        for n, suffix in enumerate(variants):
            bind = frame["bindings"+suffix][0]
            scale = contain_scale(measurements[frame["layers"+suffix][0]])
            emit(f"# A{idx}v{n}", "@gosub Func.HideBackground",
                 donor("@vcam offset:0,0,-100 rotation:0,0,0 time:0 wait:false"),
                 f'@back "{bind["appearance"]}" id:{bind["actor"]} scale:{scale:.6f} pos:50,50,-16 time:0',
                 donor("@wait i"), "@goto .Finish")
    emit("# ResetProgress", *story_reset_commands(scripts), donor("@return"))
    # Direct scene entries skip Opening.MeChoiceAfter, which normally establishes
    # these pronouns and the opposite companion form after the protagonist is chosen.
    emit("# ApplyLead", "@set playerType=G_v15Lead;playerLooksType=G_v15Lead")
    for lead, first_person, subject, obj, slime_jp, slime_en in (
            (1, "私", "She", "Her", "彼", "him"), (2, "僕", "He", "Him", "彼女", "her")):
        condition = f"if:G_v15Lead=={lead}"
        emit(f'@set itininsyouJp="{first_person}" {condition}&&xSwitchItininsyouJpInputted!=1',
             f'@set SoldierEnHe="{subject}" {condition}&&xSwitchSoldierEnHeInputted!=1',
             f'@set SoldierEnHim="{obj}" {condition}&&xSwitchSoldierEnHimInputted!=1',
             f'@set slimeSanninsyouJp="{slime_jp}";slimeSanninsyou="{slime_en}" {condition}')
    emit(donor("@return"))
    emit("# Finish","@clearChoice *","@title")
    emit("# BreakInput", "@goto .Finish if:v15ActionIssued==1",
         '@set v15ActionIssued=1;enemy1Break=1;selectCommand=-1;selectionEnemyTargetId="enemy1"',
         "@goto Battle.PlayerAttack")
    for flag, action in automatic_actions.items():
        emit(f"# Trigger{flag}", "@goto .Finish if:v15ActionIssued==1", "@set v15ActionIssued=1")
        for cmd in action["commands"]:
            emit(donor(cmd))
        emit("@goto "+action["target"])
    # Use the engine's normal animation and action effect. The only part simulated here
    # is the player's timing-bar input; its deterministic target is the tutorial slime.
    battle = scripts["Battle"]
    boss_targets = [flag for flag, action in automatic_actions.items() if action.get('selectBoss')]
    if boss_targets:
        # The phase-one priest summons eight targetable limbs. Keep the living
        # enemies and the original attack; only answer its target-selection prompt.
        target_row = unique(battle, lambda r: r[3].strip() ==
                            '@set tempActionTargetArr=GetActionTargetArrayStrBySlotNumber(selectCommand)',
                            '多目标普通攻击')
        if battle[target_row-1][1] not in ('Empty','Comment') or target_row in edits['Battle']:
            raise ValueError('原作攻击目标选择位置已变化')
        edits['Battle'][target_row-1] = ('Battle',target_row)
        target_scenes = '||'.join(f'v15Scene=={flag}' for flag in boss_targets)
        edits['Battle'][target_row] = (f'@set tempActionTargetArr="" if:({target_scenes})'
                                       '&&v15ActionIssued==1&&selectCommand==-1')
    before = unique(battle,lambda r:r[3].strip()=="@if tempClicks>0","timing input")
    if battle[before-1][1] not in ("Empty","Comment"):
        raise ValueError("攻击输入边界已改变")
    edits["Battle"][before-1] = "@set tempClicks=0 if:v15Tutorial==1||v15AutoTiming==1"
    # Insert at a non-executable line to catch both named jumps and natural fallthrough.
    # Mark the beginning of control, never the intermediate showUI in a cutscene.
    def guard(target, flags):
        name, label = target.split(".",1)
        rows = scripts[name]
        pos = len(rows)
        while pos in edits[name]:
            pos += 1
        if label.startswith("@"):
            original = int(label[1:])
            if rows[original][3].strip().lower() != "@quickload":
                raise ValueError("回放预期的原作读档位置已改变："+target)
            entry = "V15BeforeLoad"+str(original)
            edits[name][original] = "@goto ."+entry
            block = ["# "+entry] + [f"@goto Test2.Finish if:v15Scene=={flag}" for flag in sorted(set(flags))]
            block.append((name,original))
            edits[name].update({pos+i:v for i,v in enumerate(block)})
            return
        original = label_at(rows,label)
        alias = "V15Stock"+str(original)
        extra = ["# "+label]
        if target == "Battle.InitializeCommand":
            extra.append("@goto Test2.BreakInput if:v15Tutorial==1")
            extra.extend(f"@goto Test2.Trigger{flag} if:v15Scene=={flag}" for flag in automatic_actions)
        for flag in sorted(set(flags)):
            extra.append(f"@goto Test2.Finish if:v15Scene=={flag}")
        extra.append("@goto ."+alias)
        edits[name].update({pos+i:v for i,v in enumerate(extra)})
        # Named calls and natural fallthrough both pass the guard. Only move the
        # old label into a spare source row; all original commands retain their indices.
        if original+1 < len(rows) and rows[original+1][1] in ("Empty","Comment"):
            edits[name][original] = "@goto ."+label
            edits[name][original+1] = "# "+alias
        elif original and rows[original-1][1] in ("Empty","Comment"):
            edits[name][original-1] = "@goto ."+label
            edits[name][original] = "# "+alias
        else:
            raise ValueError("无法定位回放终点 "+target)
    for target, flags in exit_rules.items():
        guard(target,flags)
    currency = unique(scripts["First"], lambda r: r[3].strip() == "@set curse=0", "回放初始货币")
    edits["First"][currency] = "@set curse=999"
    # Stock immediately accepts success. Offer the original paid controls for either
    # result, keeping native costs, refunds, fixed outcomes and story callbacks.
    dungeon = scripts["Dungeon"]
    settle = unique(dungeon, lambda r: r[3].strip() == '@if curse<rotateNeedCurse||rouletteResult=="success"',
                    "轮盘结算")
    if dungeon[settle-1][1] not in ("Empty", "Comment") or settle-1 in edits["Dungeon"]:
        raise ValueError("无法定位回放轮盘的调整入口")
    label_at(dungeon, "RouletteEnd")
    edits["Dungeon"][settle-1] = "@goto .RouletteEnd if:curse>=rotateNeedCurse"
    # Keep the wheel, sound, random result and subsequent story choices in the original game.
    # Only the two mechanical button presses are automatic in the private player.
    for name in ("Dungeon", "Scenario_Warrior4"):
        rows = scripts[name]
        patch = edits[name]
        cursor = max([len(rows)] + [i + 1 for i in patch])
        phases = (("START!", "RouletteStartGoto", "V15StartWheel", "@wait 0.5"),
                  ("STOP!", "RouletteStop", "V15StopWheel", "@wait 1"))
        for caption, destination, entry, delay in phases:
            original = unique(rows, lambda r: r[3].strip().startswith(f'@choice " {caption}"')
                              and "goto:." + destination + " " in r[3], name + " " + caption)
            label_at(rows, destination)
            patch[original] = "@goto ." + entry
            for cmd in ("# " + entry, "@clearChoice *", donor(delay), "@goto ." + destination):
                patch[cursor] = cmd
                cursor += 1
    # The dedicated copy opens directly into the directory on boot and after @title.
    title_stop = unique(scripts["Title"],lambda r:r[3].strip()=="@stop","标题目录")
    edits["Title"][title_stop] = "@goto Test2.Resume"
    # A native New Game button may still be exposed during asynchronous title startup.
    for idx,_,_,line,*_ in scripts["First"]:
        if line.strip()=="@goto Opening":
            edits["First"][idx] = "@goto Test2.Resume"
    edits[MENU].update(enumerate(tape))
    import hero_replay, priest_replay, warrior_replay
    priest_replay.patch_program(edits, scripts)
    warrior_replay.patch_program(edits, scripts)
    hero_replay.patch_program(edits, scripts)
    return dict(edits)
