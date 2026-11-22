"""Build the native replay menu from the original script rows and the v1.4 art catalogue.

Each public menu entry is a real scenario callback. A replay host calls First.InitialSettings,
applies one preset's setupCommands, then gosubs to source.label. Intercept that preset's exits
before their first executable instruction and return to the menu on a natural top-level return.
Never expose a candidate as playable. script-reviewed describes static evidence only.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager
import re


ROLES = ('Hero', 'Mage', 'Warrior', 'Priest')
BOSSES = ('', 'Outcast', 'Villainess', 'Dropout', 'Slime')
EXPLORE = {'Dungeon.ExploreStart', 'Dungeon.MapMove', 'Dungeon.ExploreDungeon'}
PART = re.compile(r'^@(goto|gosub|choice|choicer|return|if|elseif|else|endif|stop|title)\b', re.I)
CHOICE_GOTO = re.compile(r'\bgoto:\s*"?([.\w{}]+)')
MANUAL = re.compile(r'\bhandler:(?:BattleCommand|ItemCardSelection|Roulette)\b', re.I)
ROUTE = re.compile(r'Scenario_(Hero|Mage|Warrior|Priest)([1-5])$')
PLAIN = re.compile(r'(\w+)\s*(==|!=|=)\s*("[\w]*"|\w+)')
SAFE_DUNGEON = {
    'BeforeSpecialChoice', 'AfterSpecialChoice', 'BeforeNovelHideUI', 'AfterNovelShowUI',
    'BeforeNovelHideUIWithoutMenu', 'BeforeSpecialBattleAfterChoice', 'AfterSpecialBattleAfterChoice',
    'GetBossIdByDungeonId', 'ResetAfterEvent', 'SetScenario5MaxSection', 'SetScenario5DungeonId',
    'GetEventItem',
}


def story_reset_commands(scripts):
    """Reset cross-playthrough progress inside the private replay environment before each entry."""
    progress = {
        'G_gameClearHeroCount', 'G_gameClearMageCount', 'G_gameClearWarriorCount',
        'G_gameKilledByPriestCount', 'G_gameLoopCount', 'G_gameOverCount', 'G_gameOverPriestPartnerCount',
        'G_latestDungeonId', 'G_latestSectionId', 'G_titleEndingGlitch', 'G_xSwitchDropoutEnd',
        'G_xSwitchFirstDeadOnPriestEventEnd', 'G_xSwitchFirstDeadOnPriestRefused',
        'G_xSwitchFirstDeadOnPriestWelcomeBackSeen',
    }
    for row in scripts.get('Ending', ()):
        match = re.match(r'@set (G_xSwitchEndingSeen_\w+)=1\b', row[3].strip())
        if match:
            progress.add(match[1])
    return ['@set G_titleEndingBackground=""', *(f'@set {name}=0' for name in sorted(progress))]


def _truth(expression, known):
    """Evaluate only simple comparisons with immutable preset values. Unknown arms stay open."""
    expr = expression.strip()
    if '||' in expr:
        values = [_truth(v, known) for v in expr.split('||')]
        return True if True in values else (None if None in values else False)
    if '&&' in expr:
        values = [_truth(v, known) for v in expr.split('&&')]
        return False if False in values else (None if None in values else True)
    if expr.lower() in ('false', 'true'):
        return expr.lower() == 'true'
    if re.fullmatch(r'\w+', expr) and expr in known:
        return bool(known[expr])
    match = PLAIN.fullmatch(expr)
    if not match or match[1] not in known:
        return None
    value = str(known[match[1]]).lower() == match[3].strip('"').lower()
    return not value if match[2] == '!=' else value


class _Source:
    def __init__(self, rows):
        self.text = [row[3].strip() for row in rows]
        self.kinds = [row[1] for row in rows]
        self.labels = {}
        self.ambiguous_labels = set()
        self.false = {}
        self.join = {}
        self.menu_wait = set()
        conditional = []
        menu_pending = False
        for i, (kind, line) in enumerate(zip(self.kinds, self.text)):
            if kind == 'Label':
                label = line.lstrip('#').strip()
                if label in self.labels:
                    self.ambiguous_labels.add(label)
                self.labels.setdefault(label, i)
                menu_pending = False
            if kind != 'Command':
                continue
            command = line.partition(' ')[0].lower()
            if command == '@if':
                conditional.append([i])
            elif command in ('@elseif', '@else') and conditional:
                conditional[-1].append(i)
            elif command == '@endif' and conditional:
                arms = conditional.pop()
                for arm, next_arm in zip(arms, arms[1:] + [i]):
                    self.false[arm] = next_arm
                for arm in arms[1:]:
                    self.join[arm] = i + 1
            if command in ('@choice', '@choicer'):
                menu_pending = True
            elif command == '@stop':
                if menu_pending:
                    self.menu_wait.add(i)
                menu_pending = False
            elif command in ('@goto', '@return', '@clearchoice'):
                menu_pending = False


class ScriptMap:
    def __init__(self, scripts):
        self.sources = {name: _Source(rows) for name, rows in scripts.items()}
        self.excluded = {}

    @contextmanager
    def review(self, scene_id):
        """A failed native proof invalidates this menu entry alone."""
        try:
            yield
        except (ValueError, LookupError, StopIteration) as error:
            self.excluded[scene_id] = str(error) or '缺少原作指令或入口'

    def trace(self, source, label, flags=None, boundaries=(), battle_exit=None):
        known = {'isTrial': False, 'isEditor': False, 'isDebugMode': False}
        known.update(flags or {})
        exits, issues, choices, visited = set(), set(), set(), defaultdict(set)
        returns = battle = False
        if label in self.sources[source].ambiguous_labels:
            return dict(visited={}, exits=[], returns=False, battle=False, choices=0,
                        issues=['原作入口重名 ' + source + '.' + label])
        start = self.sources[source].labels[label] if label else 0
        work = [(source, start, ())]
        seen = set()
        boundaries = set(boundaries) | EXPLORE
        while work:
            name, i, stack = work.pop()
            state = (name, i, stack)
            if state in seen:
                continue
            seen.add(state)
            if len(seen) > 150000:
                issues.add('控制流过大，未核完整')
                break
            src = self.sources[name]
            if i >= len(src.text):
                issues.add(f'{name} 脚本末端缺少显式返回')
                continue
            t = src.text[i]
            point = f'{name}.@{i}'
            if point in boundaries:
                exits.add(point)
                continue
            if src.kinds[i] == 'Label' and name + '.' + t[1:].strip() in boundaries:
                exits.add(name + '.' + t[1:].strip())
                continue
            visited[name].add(i)
            following = src.join.get(i + 1, i + 1)
            next_step = (name, following, stack)
            match = PART.match(t) if src.kinds[i] == 'Command' else None
            head = match[1].lower() if match else ''
            if head in ('if', 'elseif'):
                mode = _truth(t.partition(' ')[2], known)
                if mode is not True and i in src.false:
                    work.append((name, src.false[i], stack))
                if mode is not False:
                    work.append(next_step)
                continue
            if head in ('choice', 'choicer'):
                choices.add((name, i))
                if MANUAL.search(t):
                    issues.add(f'{name}:{i} 专用操作界面')
                work.append(next_step)
                target = CHOICE_GOTO.search(t)
                if not target:
                    if ' do:' not in t:
                        issues.add(f'{name}:{i} 选项去向未定位')
                    continue
                dest = target[1]
            elif head in ('goto', 'gosub', 'return', 'title', 'stop'):
                suffix = re.search(r'\sif:(.+)$', t)
                if suffix:
                    mode = _truth(suffix[1], known)
                    if mode is not True:
                        work.append(next_step)
                    if mode is False:
                        continue
                if head == 'stop':
                    if i not in src.menu_wait:
                        issues.add(f'{name}:{i} 无可追踪出口的暂停')
                    continue
                if head == 'title':
                    exits.add('@title')
                    continue
                if head == 'return':
                    if stack:
                        work.append((*stack[-1], stack[:-1]))
                    else:
                        returns = True
                    continue
                dest = t.split()[1].strip('"')
            else:
                work.append(next_step)
                continue
            if dest.startswith('.'):
                dest = name + dest
            target_name, _, target_label = dest.partition('.')
            if target_name in self.sources and target_label in self.sources[target_name].ambiguous_labels:
                issues.add(f'{name}:{i} 原作跳转目标重名 {dest}')
                continue
            if dest in boundaries:
                exits.add(dest)
                continue
            if target_name == 'Battle':
                battle = True
                if battle_exit and head == 'gosub' and not target_label:
                    exits.add(battle_exit)
                else:
                    issues.add('需要战斗状态和下一次手动指令边界')
                continue
            if head == 'gosub' and (target_name in ('Func', 'StatusFunc', 'First')
                                    or target_name == 'Dungeon' and target_label in SAFE_DUNGEON):
                # Ordinary native presentation and stat helpers return synchronously. Never
                # traverse the entire combat/item/UI engine as if it were a single novel.
                if target_name not in self.sources or target_label not in self.sources[target_name].labels:
                    issues.add(f'缺少辅助脚本 {dest}')
                work.append(next_step)
                continue
            next_src = self.sources.get(target_name)
            if (next_src is None or '{' in dest or target_label and target_label not in next_src.labels):
                issues.add(f'{name}:{i} 跳转目标 {dest} 未定位')
                continue
            if target_name in ('GameOver', 'Title', 'Reinforce', 'GetItem', 'SortWeapon',
                               'Action', 'Tutorial', 'TrialHikitsugi'):
                issues.add(f'需要独立运行条件 {dest}')
                continue
            # Trace the original roulette reset through its return. This helper
            # clears transient variables before an authored wheel sequence.
            if target_name == 'Dungeon' and target_label not in SAFE_DUNGEON and target_label != 'ResetRouletteState':
                issues.add(f'需要迷宫控制器 {dest}')
                continue
            target_i = next_src.labels[target_label] if target_label else 0
            target_stack = stack
            if head == 'gosub':
                ret = (name, following)
                if ret in stack or len(stack) >= 16:
                    issues.add(f'{name}:{i} 循环子调用未核实')
                    continue
                target_stack = stack + (ret,)
            work.append((target_name, target_i, target_stack))
        if not returns and not exits and not issues:
            issues.add('未定位可达的结束点')
        return dict(visited=dict(visited), exits=sorted(exits), returns=returns, battle=battle,
                    choices=len(choices), issues=sorted(issues))


def independent_artworks(gallery):
    artwork = [s for s in gallery['scenes'] if s['source'] == 'Extras']
    return artwork


def _presets(group, chapter, label):
    if group == 'Mage' and label == 'NotMaryokuEpilogue':
        route = {'xSwitchMageChoiceGetMaryoku': 0, 'xSwitchMageChoiceNotMaryoku': 1}
        return [('表明心意', dict(route, xSwitchMageChoiceKokuhakuSuki=1, xSwitchMageChoiceKokuhakuFlat=0)),
                ('继续同行', dict(route, xSwitchMageChoiceKokuhakuSuki=0, xSwitchMageChoiceKokuhakuFlat=1))]
    if group == 'Priest' and label == 'ToDungeon5':
        return [('尚可回头', {'xSwitchPriestLowSanEnded': 0}),
                ('经历过第四层的结局', {'xSwitchPriestLowSanEnded': 1})]
    if label == 'SlimeBattleAfterNotBelieve':
        return [('未能相信勇者', {'xSwitchHeroDropoutChoiceNotBelieve': 1})]
    if group == 'Warrior' and label == 'WarriorLv1DuelAfter':
        return [('放下武器', {'xSwitchChoiceOutcastFinalB': 0, 'xSwitchWarriorGlitchEnd': 0}),
                ('动手之后', {'xSwitchChoiceOutcastFinalB': 1, 'xSwitchWarriorGlitchEnd': 0}),
                ('经历异变', {'xSwitchChoiceOutcastFinalB': 0, 'xSwitchWarriorGlitchEnd': 1})]
    if group == 'Hero' and label == 'PriestBattleAfter':
        return [('夺取成功', {'tempHeroRoute5StealHit': 1})]
    if group == 'Mage' and label == 'PriestBattleAfter':
        return [('履行约定', {'xSwitchMageChoiceGetMaryoku': 1, 'xSwitchMageChoiceNotMaryoku': 0,
                            'xSwitchMageYakusokuSita': 1, 'xSwitchMageYakusokuSinai': 0})]
    if group == 'Mage' and label == 'PriestBattleBefore':
        return [('许下约定' if promised else '未许下约定',
                 {'xSwitchMageChoiceGetMaryoku': 1, 'xSwitchMageChoiceNotMaryoku': 0,
                  'xSwitchMageYakusokuSita': promised, 'xSwitchMageYakusokuSinai': 1-promised})
                for promised in (1, 0)]
    if group == 'Mage' and label == 'NotWakimitiRoute':
        return [('意志坚定' if sanity >= 40 else '心生动摇',
                 {'xSwitchMageChoiceGetMaryoku': 0, 'xSwitchMageChoiceNotMaryoku': 1, 'playerSanity': sanity})
                for sanity in (50, 25)]
    if group == 'Mage' and label == 'NotMaryokuSpecialWin':
        return [('放弃魔力', {'xSwitchMageChoiceNotMaryoku': 1, 'xSwitchMageChoiceGetMaryoku': 0})]
    if group == 'Mage' and chapter >= 4:
        routes = [('取回魔力', {'xSwitchMageChoiceGetMaryoku': 1, 'xSwitchMageChoiceNotMaryoku': 0}),
                  ('放弃魔力', {'xSwitchMageChoiceGetMaryoku': 0, 'xSwitchMageChoiceNotMaryoku': 1})]
        if chapter == 5 and label != 'ToDungeon5':
            return routes[1:] if 'WakimitiRoute' in label else routes[:1]
        return routes
    if group == 'Priest' and (chapter == 4 or label == 'DropoutBattleAfter'):
        return [('拒绝伸出的手', {'xSwitchChoicePriestRefuseHand': 1, 'xSwitchChoicePriestLook': 0}),
                ('看向僧侣', {'xSwitchChoicePriestRefuseHand': 0, 'xSwitchChoicePriestLook': 1})]
    if group == 'Hero' and chapter == 4 and label in ('ToDungeon4', 'SlimeBattleBefore'):
        return [('相信勇者', {'xSwitchHeroDropoutChoiceNotBelieve': 0}),
                ('未能相信勇者', {'xSwitchHeroDropoutChoiceNotBelieve': 1})]
    return [('原作入口', {})]


def _setup(group, dungeon, section, flags, label, conversation=False):
    # First.InitialSettings is the host precondition. Opening3.PartnerChoiceEnd calls
    # these native helpers in this order, including recomputing HP after the new class.
    if conversation:
        commands = ['@gosub First.BeforeGoNovel', '@set backgroundName="first"',
                '@set frameBackgroundName="None"', '@set sceneBackgroundName="cave_moss"',
                '@gosub Func.HideBackground', '@gosub Func.ShowBackground',
                '@sfx a7_waterDrip loop:true volume:0.3', '@bgm m2_loop intro:m2_intro',
                '@vcam pos:0,0,-90 time:0 wait:false']
        if label.startswith('PartnerChoiceEnd'):
            # Reuse the original confirmed-partner subroutine, which returns with the
            # right starting skills and stats. The outer selector would solicit the role.
            commands += [f'@set temp="{group}"', '@gosub Opening3.PartnerChoiceEnd']
        return commands
    partner = 'hero' if group == 'Shared' else group.lower()
    commands = [f'@set partnerCharacter="{partner}"', '@set tempCharacter="partner"',
                '@gosub Func.InitializePartnerCharacterState', '@gosub StatusFunc.StatusSetting',
                '@set partnerHealth=partnerMaxHealth',
                '@set showPlayerStatus=true', '@set showPartnerStatus=true', '@set showCurse=true',
                '@set switchShowItem=1',
                '@set xSwitchShowAttackModeChangeChoiceSelected=1',
                f'@set dungeonId={dungeon}', f'@set sectionId={section}']
    commands.extend(f'@set {key}={value}' for key, value in flags.items())
    if group == 'Mage' and flags.get('xSwitchMageChoiceNotMaryoku') and dungeon == 8:
        dungeon = 9
        commands.append('@set dungeonId=9')
    # Dungeon.ExploreStart lines 152–164 (zero based). Route transitions normally
    # begin on the previous floor. A callback may then set its own new backdrop.
    background = {2: 'heights', 3: 'sea', 4: 'dungeon_red', 10: 'maou_naka'}.get(dungeon, 'dungeon_blue')
    if dungeon in (8, 9) and section == 1:
        background = 'stairs'
    if dungeon == 7 and section > 1:
        background = 'last'
    if dungeon == 6 and section > 1:
        background = 'maou_naka'
    # The post-battle callbacks below have just left these authored battle backgrounds.
    if dungeon == 5 and label == 'VillainnessBattleAfter':
        background = 'heights'
    if dungeon == 5 and label == 'DropoutBattleAfter':
        background = 'sea'
    if label in ('PriestBattleAfter', 'PriestBattleAfterLowLoop') and group in ('Hero', 'Priest'):
        background = 'last'
    if label == 'WarriorLv1DuelAfter':
        background = 'dungeon_blue'
    if label == 'Epilogue' and group == 'Priest':
        background = 'maou_gyokuza'
    bgm_index = {1: 2, 2: 3, 3: 4, 4: 5}.get(dungeon, 17)
    condition = f'dungeonId={dungeon}' if dungeon < 5 else 'dungeonId>=5&&dungeonId<=10'
    commands.extend(['@gosub Dungeon.BeforeNovelHideUI', f'@set backgroundName="{background}"',
                     '@gosub Func.ShowBackground',
                     '@vcam offset:0,0,{vcamDefaultZ} rotation:0,0,0 time:0 wait:false',
                     f'@bgm m{bgm_index}_loop intro:m{bgm_index}_intro if:{condition}'])
    if label == 'WarriorLv1DuelAfter':
        commands.extend(['@gosub Func.ClearPartnerCharacter', '@set showPartnerStatus=false',
                         '@gosub Dungeon.BeforeNovelHideUIWithoutMenu'])
    return commands


def _entries(flow):
    # Only actual external entry points are listed. Internal choices, local test labels
    # and individual @back calls never become directory entries.
    yield 'Opening2', '', 'Shared', 0, '洞窟里的牌局', 1, 1, ''
    for role, title in zip(ROLES, ('勇者', '魔法师', '战士', '僧侣')):
        yield 'Opening3', role.lower() + 'Scene', role, 0, f'洞窟交谈 · {title}', 1, 1, ''
        yield 'Opening3', 'PartnerChoiceEnd' + role, role, 0, '结伴出发', 1, 1, ''
    yield 'Scenario', 'FirstDeadOnPriest', 'Shared', 7, '倒下后的邀请', 1, 1, ''
    for role in ROLES:
        for floor in range(1, 5):
            name = f'Scenario_{role}{floor}'
            if name not in flow.sources:
                continue
            boss = BOSSES[floor]
            if floor > 1:
                yield name, f'ToDungeon{floor}', role, floor, '前往下一层', floor - 1, 5, ''
            for segment in (1, 2, 3):
                # For Warrior at the end of a special random-event tile Dungeon dispatches
                # before incrementing sectionId; the third elite encounter also runs early.
                early = (floor >= 2 and segment == 3 or
                         role == 'Warrior' and (floor, segment) in ((2, 1), (4, 1), (4, 2)))
                section = segment if early else segment + 1
                yield name, f'{boss}{segment}', role, floor, f'途中事件 · {segment}', floor, section, ''
            yield name, boss + 'BattleBefore', role, floor, '首领战前', floor, 4, ''
            # Starting after an actual battle can depend on its state, enemy actors and
            # earlier route choices. Keep unaudited post-battle starts out of the menu.
            reviewed_post = floor == 1 or (role, floor) in {
                ('Hero', 2), ('Hero', 3), ('Hero', 4), ('Mage', 2), ('Mage', 3), ('Mage', 4),
                ('Priest', 3), ('Warrior', 3)}
            post_issue = '' if reviewed_post else '战后初始状态尚待确认'
            yield name, boss + 'BattleAfter', role, floor, '首领战后', floor, 4, post_issue
            for post in {
                ('Hero', 2): ['VillainessAfterDealer'], ('Priest', 2): ['EliteBattleAfter'],
                ('Mage', 3): ['Elite3BattleAfter'],
            }.get((role, floor), ()):
                yield name, post, role, floor, '精英战后', floor, 3, ''
            if role == 'Hero' and floor == 4:
                yield name, 'SlimeBattleAfterNotBelieve', role, 6, '另一条路的终点', 4, 4, ''
        name = f'Scenario_{role}5'
        event_floor = {'Hero': 5, 'Warrior': 6, 'Priest': 7, 'Mage': 8}[role]
        yield name, 'ToDungeon5', role, 5, '进入第五层', event_floor, 1, ''
        upper = {
            'Hero': [('Floor5', 1), ('OutcastEvent', 2), ('VillainessMemory', 3),
                     ('DropoutMemory', 4), ('PriestBattleBefore', 5)],
            'Warrior': [('Floor5', 1), ('Last1', 2), ('Last2', 3), ('Last3', 4), ('WarriorBattleBefore', 5)],
            'Mage': [('PriestBattleBefore', 2), ('NotWakimitiRoute', 2), ('WakimitiRoute', 2),
                     ('WakimitiRoute_AfterBattle1', 3), ('WakimitiRoute_AfterBattle2', 4)],
            # Dungeon.event701 calls ToDungeon5 AND PriestBattleBefore. ToDungeon5 itself
            # falls into that battle on ordinary routes; no second directory item is made.
            'Priest': [('DemonLordBattleBefore', 1)],
        }
        for label, section in upper[role]:
            event_dungeon = 10 if label == 'DemonLordBattleBefore' else event_floor
            title = f'途中事件 · {section}' if 'BattleBefore' not in label else '决战之前'
            if role == 'Mage':
                title = {'WakimitiRoute_AfterBattle2':'昔日对手的合流',
                         'WakimitiRoute_AfterBattle1':'跌倒之后的追逐',
                         'WakimitiRoute':'握住她的手，奔向岔路',
                         'NotWakimitiRoute':'正面迎向僧侣'}.get(label, title)
            yield name, label, role, 5, title, event_dungeon, section, ''
        after = {
            'Hero': [('OutcastBattleAfter', 2, '放逐者的回忆'), ('VillainnessBattleAfter', 3, '反派千金的回忆'),
                     ('DropoutBattleAfter', 4, '落选者的回忆'), ('PriestBattleAfter', 5, '最后的一击')],
            'Mage': [('PriestBattleAfter', 2, '共同的约定'), ('NotMaryokuSpecialWin', 2, '逆转命运'),
                     ('NotMaryokuEpilogue', 4, '迷宫之外')],
            'Warrior': [('Last3BattleAfter', 4, '幻影消失之后'), ('WarriorLv1DuelAfter', 5, '决斗之后')],
            'Priest': [('PriestBattleAfterLowLoop', 1, '再次伸手'), ('Epilogue', 1, '凯旋')],
        }
        for label, section, title in after[role]:
            is_ending = label in ('PriestBattleAfter', 'Epilogue', 'NotMaryokuSpecialWin',
                                  'NotMaryokuEpilogue', 'WarriorLv1DuelAfter')
            dungeon = 10 if label == 'Epilogue' else event_floor
            yield name, label, role, 6 if is_ending else 5, title, dungeon, section, ''


def _select_art(visited, gallery_rows):
    return [s['id'] for s in gallery_rows if s['source'] in visited and
            s['source'] not in ('Ending', 'Title') and
            any(line in visited[s['source']] for line in s.get('nativeLines', (s['line'],)))]


def _battle_bridge(source, label):
    """Only fights with a normal opening-turn command boundary. Scripted inputs (late
    final battles, orders, roulette, timed hits) need an actual combat checkpoint."""
    route = ROUTE.fullmatch(source)
    if not route:
        return False
    role, chapter = route[1], int(route[2])
    if chapter in (1, 2, 3):
        return True
    if chapter == 4:
        return role in ('Hero', 'Mage') or label in ('Slime3', 'SlimeBattleBefore') or (
            role == 'Warrior' and label == 'Slime1')
    # These are early rematches and the illusion battle intros. Each callback sets
    # battleTarget and addEnemyResourceNames before calling Battle.
    return (
        role == 'Hero' and label in ('OutcastEvent', 'VillainessMemory', 'DropoutMemory') or
        role == 'Mage' and label in ('PriestBattleBefore', 'NotWakimitiRoute', 'WakimitiRoute',
                                     'WakimitiRoute_AfterBattle1', 'WakimitiRoute_AfterBattle2') or
        role == 'Warrior' and label in ('Last1', 'Last2', 'Last3') or
        role == 'Priest' and label == 'ToDungeon5'
    )


def _boundaries(source, label, flow):
    if source == 'Opening3':
        if label.startswith('PartnerChoiceEnd'):
            return ('Opening3.PartnerChoice',)
        if label == 'priestScene':
            src = flow.sources[source]
            start = src.labels['priestChoiceGisikiYes']
            end = min((i for i in src.labels.values() if i > start), default=len(src.text))
            matches = [i for i in range(start, end) if src.text[i].lower() == '@quickload']
            if len(matches) != 1:
                raise ValueError('序章祭祀的原作快速读取位置已变化')
            return ('Opening3.hanasiChoice', f'Opening3.@{matches[0]}')
        return ('Opening3.hanasiChoice',)
    if source == 'Opening2':
        return ('Opening3.hanasiChoice',)
    if (source, label) == ('Scenario', 'FirstDeadOnPriest'):
        return ('GameOver.GameOverBeforeCore', 'GameOver.FirstDeadOnPriestEnd')
    return ()


def _ending_art(source, label, flags, route, gallery_rows):
    if 'Ending' not in route['visited']:
        return []
    # v1.4 records the ACTUAL set-endingType line or final jump for each ending,
    # including the cross-script DropoutBadEnd. The Ending controller contains all
    # slideshow definitions in one script, so its line numbers alone are ambiguous.
    ignore = set()
    if (source, label) == ('Scenario_Warrior5', 'WarriorLv1DuelAfter'):
        expected = ('warriorKill' if flags['xSwitchChoiceOutcastFinalB'] else
                    'warriorAfterGlitch' if flags['xSwitchWarriorGlitchEnd'] else 'warrior')
        ignore = {'warrior', 'warriorKill', 'warriorAfterGlitch'} - {expected}
    result = []
    for row in gallery_rows:
        if row['source'] != 'Ending' or row['label'] in ignore:
            continue
        origins = row.get('storyOrigins', ())
        if any(x['line'] in route['visited'].get(x['source'], ()) for x in origins):
            result.append(row['id'])
    return result


def _battle_action(flow, gallery_rows, uid, group, chapter, title, setup, commands, cut_labels, proof, note):
    rows = []
    for script, exact_text in proof:
        text = flow.sources[script].text
        try:
            line = text.index(exact_text)
        except ValueError as exc:
            raise ValueError(f'战斗回放条件发生变化 {script} {exact_text}') from exc
        rows.append({'source': script, 'line': line, 'text': exact_text})
    ids = []
    for label in cut_labels:
        hits = [row for row in gallery_rows if row['source'] == 'Battle' and (row['label'] == label or
                label.startswith('CG/') and f'"{label}"' in flow.sources['Battle'].text[row['line']])]
        if not hits:
            raise ValueError(f'未找到原作战斗插画 {label}')
        ids.extend(s['id'] for s in hits)
    action = dict(commands=commands, target='Battle.PlayerAttack', skipTiming=True)
    preset = dict(title='原作触发动作', setupCommands=setup, exits=['Battle.InitializeCommand'],
                  naturalReturn=False, naturalTitle=False, choices=0, galleryIds=ids,
                  actionAtFirstCommand=action, issues=[], status='script-reviewed')
    return dict(id=uid, group=group, chapter=chapter, title=title, source='Battle', label='Start',
                line=flow.sources['Battle'].labels['Start'], setupCommands=setup, exits=preset['exits'],
                naturalReturn=False, naturalTitle=False, boundary='label', galleryIds=ids, presets=[preset],
                actionAtFirstCommand=action, status='script-reviewed', evidence=note, evidenceRows=rows)


def _villainess_regeneration(flow, gallery_rows):
    proof = [('Battle', '@gosub .TurnEndEffectsLoop'),
             ('Battle', '@if battleTarget=="villainess"&&IsEnemyStr(tempTarget)&&{tempTarget}ResourceName=="villainess"'),
             ('Battle', '@if xSwitchVillainessBossRegeneEvent!=1&&tempDamagedHealth>0'),
             ('Battle', '@if xSwitchVillainessBossRegeneCount!=1')]
    commands = ['@set tempTarget="enemy1";enemy1Health=enemy1MaxHealth-10;enemy1StateRegeneration=10',
                '@set xSwitchVillainessBossRegeneCount=1;xSwitchVillainessBossRegeneEvent=0',
                '@gosub Battle.TurnEndEffectsLoop']
    def setup(role):
        return _setup(role, 2, 4, {}, '') + ['@gosub Func.ShowSettings', '@set battleTarget="villainess"',
            '@set addEnemyResourceNames="villainess"', '@set xSwitchBoss2BattleEvent=0', '@set showEnemyUI=false']
    scene = _battle_action(flow, gallery_rows, 'Battle.Action.VillainessRegeneration', 'Shared', 2,
                           '反派千金 · 以爱愈合的伤口', setup('Hero'), commands, ('TurnEndEffectsLoop',),
                           proof, '千金受伤后再次再生，吻的特写和同行者的反应由原作回合结算播放。')
    scene['actionAtFirstCommand'].update(target='Test2.Finish', skipTiming=False)
    # The first art record is common. The gallery also indexes the lines spoken
    # over the same shot for the hero, priest and warrior.
    lines = flow.sources['Battle'].text
    rows = sorted((r for r in gallery_rows if r['id'] in scene['galleryIds']), key=lambda r:r['line'])
    first = rows[0]
    role_starts = {role: lines.index(('@if ' if role=='Mage' else '@elseif ')+f'partnerCharacter=="{role.lower()}"',
                                     first['line']) for role in ROLES}
    assigned = {role: [first['id']] for role in ROLES}
    for row in rows[1:]:
        role = max((r for r in ROLES if role_starts[r] < row['line']), key=role_starts.get)
        assigned[role].append(row['id'])
    scene['presets'] = [dict(scene['presets'][0], title=title+'同行', setupCommands=setup(role),
                             galleryIds=assigned[role]) for role, title in zip(ROLES, ('勇者','魔法师','战士','僧侣'))]
    return scene


def _battle_actions(flow, gallery_rows):
    with flow.review('Battle.Action.VillainessRegeneration'):
        yield _villainess_regeneration(flow, gallery_rows)
    # One remaining target represents the turn after the servants have disappeared.
    # Stock AddEnemies assigns slot 1. The normal damaging command is submitted to
    # PlayerAttack; EnemyDeathCheck owns the actual CG, dialogue and phase restart.
    setup = _setup('Hero', 2, 4, {}, '') + [
        '@gosub Func.ShowSettings', '@set battleTarget="villainess"',
        '@set addEnemyResourceNames="villainessWithDoll"', '@set xSwitchBoss2BattleEvent=0',
        '@set xSwitchVillainessBattleRe=1', '@set xSwitchVillainessWithDollDamageFirstEvent=1',
        '@set xSwitchVillainessHeroFrontEvent=1', '@set xSwitchSkipEnemyAppearMessage=1',
    ]
    commands = ['@set bgmName="m13"', '@bgm "{bgmName}_loop" intro:"{bgmName}_intro"',
                '@set enemy1Health=1', '@set enemy1StateBlock=0', '@set enemy1StateEvading=0',
                '@set selectCommand=-1', '@set selectionEnemyTargetId="enemy1"']
    proof = [
        ('Scenario', '@set addEnemyResourceNames="villainessWithDoll"'),
        ('Battle', '@if enemy{tempBattleStartEnemyCount}ResourceName=="villainessWithDoll"'),
        ('Battle', '@set xVillainessWithDollSlot=tempBattleStartEnemyCount'),
        ('Battle', '@set defaultActionNumber="-1"'), ('Battle', '# PlayerAttack'),
        ('Battle', '@set livingEnemyCount=CountTargetableEnemies(enemyMaxCount)'),
        ('Battle', '@set z=PrepareSelectedTargetHits(selectCommand,selectionEnemyTargetId)'),
        ('Battle', '@if tempEnemyResourceName=="villainessWithDoll"&&xSwitchVillainessSpiderForm!=1'),
        ('Battle', '@gosub .VillainessSecondFormTransitionCore'),
        ('Battle', '@set xSwitchVillainessSpiderForm=1'),
        ('Battle', '@gosub .RequestBattlePhaseRestart if:xSwitchVillainessSpiderForm==1&&xVillainessSlot>0&&enemy{xVillainessSlot}Death!=1'),
    ]
    with flow.review('Battle.Action.VillainessSecondForm'):
        yield _battle_action(flow, gallery_rows, 'Battle.Action.VillainessSecondForm', 'Hero', 2,
                             '反派千金 · 第二形态', setup, commands,
                             ('VillainessSecondFormTransitionCore', 'VillainessReSkipSecondFormText'),
                             proof, '勇者同行，人偶退场；普通攻击击倒第一形态，原作死亡检查触发变身。')

    # The first phase summons eight separate targetable limbs. The second and third
    # start with the priest alone. The original pre-command support scene is normally
    # run below InitializeCommand and before its first choice, so call it first here.
    for phase, ally, title, cut, marker in (
        (2, 'outcast', '放逐者的救援', 'PriestFinalMageNotMaryokuForm2CounterText',
         '@gosub .PriestFinalMageNotMaryokuForm2CounterText if:xPriestFinalPhase==2'),
        (3, 'dropout', '落选者的支援与红色身影', 'HatsugenTest22',
         '@gosub .PriestFinalMageNotMaryokuForm3CounterText'),
    ):
        setup = _setup('Mage', 9, 4, {'xSwitchMageChoiceGetMaryoku': 0, 'xSwitchMageChoiceNotMaryoku': 1}, '') + [
            '@set backgroundName="last"', '@gosub Func.ShowBackground', '@gosub Func.ShowSettings',
            '@set xSwitchBoss5BattleEvent=1', '@set battleTarget="priest"', '@set xSwitchRunAllowed=0',
            '@set xSwitchPriestFinalMageNotMaryokuEventAllowed=1', '@set xSwitchPriestFinalMageNotMaryokuSpecialWinGoto=0',
            f'@set xSwitchSystemDebugPriestPhase={phase}', '@set addEnemyResourceNames="priest"',
            '@set showEnemyUI=false',
        ]
        commands = ['@gosub Battle.PriestFinalAfterFormStartSetupText', '@set enemy1Health=1',
                    '@set enemy1StateBlock=0', '@set enemy1StateBarrier=0', '@set enemy1StateEvading=0',
                    '@set selectCommand=-1', '@set selectionEnemyTargetId="enemy1"']
        proof = [
            ('Scenario_Mage5', '@set xSwitchPriestFinalMageNotMaryokuEventAllowed=1'),
            ('Battle', '@set xPriestFinalPhase=xSwitchSystemDebugPriestPhase'),
            ('Battle', '@set xPriestFinalRoute="mageNotMaryoku" if:xSwitchMageChoiceNotMaryoku==1'),
            ('Battle', f'@set priestFinalCurrentResourceName="priestForm{phase}" if:xPriestFinalPhase=={phase}'),
            ('Battle', '@set xPriestFinalSlot=tempBattleStartEnemyCount'),
            ('Battle', '@gosub .PriestFinalAfterFormStartSetupText if:battleTarget=="priest"'),
            ('Battle', f'@gosub .PriestFinalMageNotMaryokuForm{phase}AfterSetupText'),
            ('Battle', f'@set tempSupportPresentationCharacter="{ally}"'),
            ('Battle', '@gosub .PriestFinalPhaseTransitionCheck if:battleTarget=="priest"'),
            ('Battle', '@return if:enemy{xPriestFinalSlot}Health>0&&enemy{xPriestFinalSlot}Death!=1'),
            ('Battle', '@gosub .PriestFinalPhaseClearText'), ('Battle', marker),
        ]
        with flow.review(f'Battle.Action.MagePriestPhase{phase}'):
            yield _battle_action(flow, gallery_rows, f'Battle.Action.MagePriestPhase{phase}', 'Mage', 5,
                                 title, setup, commands, (f'CG/{ally}AllyCut', cut), proof,
                                 '以原作形态选择值初始化；保留同伴支援，自动提交普通攻击，顺接原作反击演出。')


def build_catalog(scripts, gallery):
    """Return serializable scene records, original independent artwork, and an ID coverage audit."""
    flow = ScriptMap(scripts)
    artwork = independent_artworks(gallery)
    if __package__:
        from .source_anchors import resolve_gallery
    else:
        from source_anchors import resolve_gallery
    gallery_rows, missing_art = resolve_gallery(scripts, gallery)
    scenes = []
    for source, label, group, chapter, title, dungeon, section, issue in _entries(flow):
        if source not in flow.sources or label and label not in flow.sources[source].labels:
            continue
        uid = f'{source}.{label}' if label else source
        with flow.review(uid):
            conversation = source == 'Opening3'
            presets = []
            for preset_title, flags in _presets(group, chapter, label):
                boundaries = _boundaries(source, label, flow)
                battle_exit = 'Battle.InitializeCommand' if _battle_bridge(source, label) else None
                route = flow.trace(source, label, dict(flags, partnerCharacter=group.lower()), boundaries,
                                   battle_exit=battle_exit)
                if (source, label) == ('Scenario_Priest5', 'ToDungeon5') and route['battle']:
                    route['exits'].append('Battle.SelectAnyItemByTurn')
                natural_title = '@title' in route['exits']
                if natural_title:
                    route['exits'].remove('@title')
                issues = list(route['issues'])
                if issue:
                    issues.append(issue)
                ids = _select_art(route['visited'], gallery_rows)
                ids.extend(_ending_art(source, label, flags, route, gallery_rows))
                if route['battle'] and 'Battle.InitializeCommand' in route['exits']:
                    # Demonstrated stock control flow before that very first manual input.
                    labels = ()
                    if chapter == 1 and label == 'OutcastBattleBefore':
                        labels = {'Hero': ('SkipBgm', 'OutcastHeroCutCore'), 'Priest': ('OutcastHeroCutCore',)}.get(group, ())
                    if source == 'Scenario_Warrior5' and label == 'Last2':
                        labels = ('WarriorIllusionBStartText',)
                    ids.extend(s['id'] for s in gallery_rows if s['source'] == 'Battle' and s['label'] in labels)
                setup = _setup(group, dungeon, section, flags, label, conversation)
                if source == 'Opening2':
                    setup = []
                if (source, label) == ('Scenario', 'FirstDeadOnPriest'):
                    setup.extend(['@set G_xSwitchFirstDeadOnPriestEventEnd=0',
                                  '@set G_xSwitchFirstDeadOnPriestWelcomeBackSeen=0',
                                  '@set G_xSwitchFirstDeadOnPriestRefused=0', '@gosub Func.HideBackground'])
                presets.append(dict(title=preset_title, setupCommands=setup,
                                    exits=route['exits'], naturalReturn=route['returns'], naturalTitle=natural_title,
                                    choices=route['choices'],
                                    galleryIds=ids, issues=issues, status='candidate' if issues else 'script-reviewed'))
            checked = [p for p in presets if p['status'] == 'script-reviewed']
            first = next(iter(checked), presets[0])
            scenes.append(dict(id=uid, group=group, chapter=chapter, title=title, source=source, label=label,
                               line=flow.sources[source].labels[label] if label else 0, setupCommands=first['setupCommands'],
                               exits=sorted({x for p in checked or presets for x in p['exits']}),
                               naturalReturn=any(p['naturalReturn'] for p in checked or presets),
                               naturalTitle=any(p['naturalTitle'] for p in checked or presets),
                               boundary='return' if first['naturalReturn'] and not first['exits'] else 'label',
                               galleryIds=list(dict.fromkeys(x for p in checked or presets for x in p['galleryIds'])),
                               presets=presets, status=first['status'], evidence='原作剧情入口及静态控制流'))
    scenes.extend(_battle_actions(flow, gallery_rows))
    import hero_replay, mage_replay, warrior_replay, priest_replay
    hero_replay.integrate(scenes, flow, gallery_rows)
    mage_replay.integrate(scenes, flow, gallery_rows)
    warrior_replay.integrate(scenes, flow, gallery_rows)
    priest_replay.integrate(scenes, flow, gallery_rows)
    # Post-battle callbacks are recovered separately from their map event.
    # Place them between that encounter and the next story beat in the directory.
    scenes = [s for s in scenes if s['id'] not in flow.excluded]
    by_scene = {s['id']: s for s in scenes}
    earlier = {
        'Scenario_Hero2.VillainessBattleBefore': ['Scenario_Hero2.VillainessAfterDealer'],
        'Scenario_Hero5.VillainessMemory': ['Scenario_Hero5.OutcastBattleAfter'],
        'Scenario_Hero5.DropoutMemory': ['Scenario_Hero5.VillainnessBattleAfter'],
        'Scenario_Hero5.PriestBattleBefore': ['Scenario_Hero5.DropoutBattleAfter'],
        'Scenario_Mage3.DropoutBattleBefore': ['Scenario_Mage3.Elite3BattleAfter'],
        'Scenario_Warrior5.WarriorBattleBefore': ['Scenario_Warrior5.Last3BattleAfter'],
        'Scenario_Priest2.VillainessBattleBefore': ['Scenario_Priest2.EliteBattleAfter'],
        'Scenario_Priest2.VillainessBattleAfter': ['Scenario_Priest2.MageHeroBattleAfter'],
        'Scenario_Priest3.DropoutBattleBefore': ['Scenario_Priest3.EliteBattle3After'],
        'Scenario_Priest3.DropoutBattleAfter': ['Battle.Action.PriestDropout'],
        'Scenario_Priest4.SlimeBattleBefore': ['Scenario_Priest4.Slime3BattleAfter'],
        'Scenario_Priest5.DemonLordBattleBefore': ['Battle.Action.PriestCounter', 'Battle.Action.PriestCurseShortage',
                                                   'Battle.Action.PriestFourthForm', 'Scenario_Priest5.PriestBattleAfterLowLoop'],
    }
    for next_id, preceding in earlier.items():
        for scene_id in preceding:
            if scene_id not in by_scene or next_id not in by_scene:
                continue
            scene = by_scene[scene_id]
            scenes.remove(scene)
            scenes.insert(scenes.index(by_scene[next_id]), scene)
    by_id = {s['id']: 'pending' for s in gallery['scenes']}
    by_id.update({s['id']: 'pending' for s in gallery_rows})
    for s in scenes:
        for p in s['presets']:
            for old_id in p['galleryIds']:
                if by_id[old_id] == 'pending' or p['status'] == 'script-reviewed':
                    by_id[old_id] = p['status']
    for s in artwork:
        by_id[s['id']] = 'artwork'
    candidate_issues = {scene['id']: sorted({reason for p in scene['presets'] for reason in p['issues']})
                        for scene in scenes if any(p['issues'] for p in scene['presets'])}
    pending_sources = Counter(row['source'] for row in gallery['scenes'] if by_id[row['id']] == 'pending')
    legacy_ids = {s['id'] for s in gallery['scenes']}
    added_cues = {key: by_id.pop(key) for key in list(by_id) if key not in legacy_ids}
    return dict(scenes=scenes, artworks=artwork,
                coverage=dict(byGalleryId=by_id, counts=dict(Counter(by_id.values())),
                              pendingBySource=dict(pending_sources), candidateIssues=candidate_issues,
                              unresolvedArtwork=missing_art, nativeIllustrations=added_cues, excluded=flow.excluded,
                              sceneCounts=dict(Counter(s['status'] for s in scenes))))
