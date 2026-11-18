"""Locate gallery scenes in the original scenario. All inputs are read as data."""
import heapq
import re
from collections import Counter, defaultdict


ROLES = ('Hero', 'Mage', 'Warrior', 'Priest', 'Shared')
ROUTE = re.compile(r'Scenario_(Hero|Mage|Warrior|Priest)([1-5])$')
CALL = re.compile(r'^@(gosub|goto)\s+"?([.\w{}]+)')
CHOICE = re.compile(r'\bgoto:"?\.([\w]+)')
ENDING = re.compile(r'endingType=="([^"]+)"')


class Source:
    def __init__(self, rows):
        self.text = [r[3].strip() for r in rows]
        self.labels = {r[3].strip().lstrip('#').strip(): r[0] for r in rows if r[1] == 'Label'}
        self.commands = {r[0]: self.text[r[0]] for r in rows if r[1] == 'Command'}
        self.calls = defaultdict(list)
        self.guards = {}
        self.either = {}
        self.skip = {}
        stack = []
        for i,t in self.commands.items():
            head = t.split(' ', 1)[0].lower()
            if head == '@if':
                stack.append([i])
            elif head in ('@elseif','@else') and stack:
                stack[-1].append(i)
            elif head == '@endif' and stack:
                ends = stack.pop()
                for previous, following in zip(ends, ends[1:] + [i]):
                    self.either[previous] = following
                    if following != i:
                        self.skip[following] = i+1
            m = CALL.match(t)
            if m:
                self.calls[m[2]].append(i)
            if t.startswith('@back ') or t.startswith('@set endingImageSetKey=') or t.startswith('@set titleEndingBackground='):
                self.guards[i] = [self.text[block[-1]] for block in stack]

    def find(self, pattern):
        rx = re.compile(pattern)
        for i,t in self.commands.items():
            if rx.search(t): return i
        raise MissingTrigger(pattern)

    def local_order(self, points, menus):
        """Topologically order displayed points along literal jumps, calls, choices and joins.

        Cycles represent revisitable scenes. Independent points, including branches entered
        by the dungeon dispatcher, use their script order as a deterministic tie-break.
        """
        points = set(points)
        if not points: return {}
        # Compress visual/text commands before tracing. A return resumes only the call
        # actually traversed on this path; dynamic external subroutines are opaque.
        important = set(points)
        important.update(self.labels.values())
        for i,t in self.commands.items():
            if t.split(' ',1)[0].lower() in ('@goto','@gosub','@choice','@choicer','@stop','@return','@if','@elseif','@else','@endif'):
                important.add(i)
        end = len(self.text)
        next_ = [end]*(end+1)
        for i in range(end-1,-1,-1):
            next_[i] = i if i in important else next_[i+1]

        def trace(start):
            found = set()
            work = [(start, (), True)]
            seen = set()
            while work:
                i, stack, entering = work.pop()
                if i >= end or (i,stack,entering) in seen: continue
                seen.add((i,stack,entering))
                if i in points and not entering:
                    found.add(i)
                    continue
                t = self.commands.get(i,'')
                head = t.split(' ',1)[0].lower()
                following = next_[i+1]
                # Natural entry into elseif/else means the preceding arm was taken.
                if following in self.skip:
                    following = next_[self.skip[following]]
                def push(pos, callstack=stack):
                    work.append((pos,callstack,False))
                if i in self.either and head != '@else':
                    push(next_[self.either[i]])
                if (m := CALL.match(t)):
                    local = self.labels.get(m[2][1:]) if m[2].startswith('.') else None
                    if local is not None:
                        if head == '@gosub':
                            if following not in stack and len(stack)<10:
                                push(local,stack+(following,))
                        else:
                            push(local)
                    if (head == '@gosub' and local is None) or ' if:' in t: push(following)
                elif head == '@return':
                    if stack: push(stack[-1],stack[:-1])
                    if ' if:' in t: push(following)
                elif head == '@stop':
                    continue
                else:
                    if head in ('@choice','@choicer') and (m := CHOICE.search(t)) and m[1] in self.labels:
                        push(self.labels[m[1]])
                    push(following)
            return found - {start}

        graph = {p:trace(p) for p in points}
        # Parallel illustrated answers should be adjacent before their descendants.
        # The menu order is the original choice order, independent of label placement.
        tie = {p:(p,0) for p in points}
        menu_ties = {}
        for menu in menus:
            if len(menu)>1:
                targets = [p for label,_ in menu if label in self.labels
                           for p in sorted(trace(self.labels[label])) if p in points]
                for n,p in enumerate(dict.fromkeys(targets)):
                    priority = (min(targets),n)
                    menu_ties[p] = min(menu_ties.get(p,priority),priority)
        tie.update(menu_ties)
        return component_order(graph,tie)


def component_order(graph, tie):
    # Tarjan contraction keeps an actual cycle together without dropping any other edges.
    stack, active, ids, low, components = [], set(), {}, {}, []
    def visit(v):
        ids[v] = low[v] = len(ids)
        stack.append(v)
        active.add(v)
        for w in sorted(graph[v]):
            if w not in ids:
                visit(w)
                low[v] = min(low[v],low[w])
            elif w in active:
                low[v] = min(low[v],ids[w])
        if ids[v] == low[v]:
            c = []
            while True:
                w = stack.pop()
                active.remove(w)
                c.append(w)
                if w == v: break
            components.append(sorted(c,key=lambda p:(tie[p],p)))
    for p in sorted(graph):
        if p not in ids: visit(p)
    owner = {p:i for i,c in enumerate(components) for p in c}
    edges = {i:{owner[w] for p in c for w in graph[p] if owner[w]!=i}
             for i,c in enumerate(components)}
    incoming = Counter(w for ws in edges.values() for w in ws)
    def item(i):
        return tie[components[i][0]], components[i][0], i
    queue = [item(i) for i in edges if not incoming[i]]
    heapq.heapify(queue)
    result = {}
    while queue:
        _,_,i = heapq.heappop(queue)
        for p in components[i]: result[p]=len(result)
        for w in edges[i]:
            incoming[w]-=1
            if not incoming[w]: heapq.heappush(queue,item(w))
    return result


def route(source):
    match = ROUTE.fullmatch(source)
    return (match[1],int(match[2])) if match else ('Shared',0)


class MissingTrigger(ValueError):
    """A known optional event no longer has its original route guard or caller."""


def arc_position(name,src,i):
    """Separate mutually exclusive late-game paths which the battle engine re-enters.

    Local script jumps alone cannot order callbacks from Battle or the dungeon map.
    The section labels here are the callbacks and branch joins used by those dispatchers.
    """
    if name=='Scenario_Priest5':
        phases = [
            ('PriestBattleAfterLowLoop',1,0),('DemonLordBattleBefore',1,1),('Epilogue',1,2),
            ('PriestBattleHighLoopBeforeForm4',2,0),('PriestBattleHighLoopBeforeFinisher',2,1),
            ('PriestBattleHighLoopFinisherCutIns',2,2),('PriestBattleHighLoopFinisher',2,3),
            ('PriestBattleAfterHighLoop',2,4),('ChoicePriestNod',3,0),
        ]
        latest = max(((src.labels[l],a,b) for l,a,b in phases if l in src.labels and src.labels[l]<=i),default=None)
        if latest: return latest[1:]
    return 0,0


def route_note(name,src,line):
    """Read branch selectors from their owning label intervals, without revealing the choice."""
    if name=='Scenario_Mage4':
        for base in ('Slime1','Slime2','SlimeBattleBefore','SlimeBattleAfter'):
            start,end = src.labels.get(base),src.labels.get(base+'BunkiEnd')
            if start is None or end is None or not start<=line<end: continue
            for flag,letter in (('Maryoku','A'),('NotMaryoku','B')):
                dest = base+flag+'Route'
                if dest not in src.labels or not src.calls.get('.'+dest): continue
                other = base+('Maryoku' if flag=='NotMaryoku' else 'NotMaryoku')+'Route'
                lo,hi = src.labels[dest],src.labels.get(other,end)
                if lo<=line<(hi if hi>lo else end): return '路线分支 '+letter
    if name=='Scenario_Priest5':
        arc,_ = arc_position(name,src,line)
        if arc: return '路线分支 '+'ABC'[arc-1]
    if name=='Scenario_Mage5':
        split = src.labels.get('ToDungeon5NotMaryokuRoute')
        if split is not None and src.calls.get('.ToDungeon5NotMaryokuRoute'):
            return '路线分支 '+('B' if line>=split else 'A')
    return ''


class Story:
    def __init__(self, scripts):
        self.src = {k:Source(v) for k,v in scripts.items() if k.startswith(('Opening','Scenario')) or
                    k in ('GameOver','Battle','Ending','Dungeon','TrialEnd')}
        self.ending_origins = defaultdict(list)
        for name,src in self.src.items():
            if not ROUTE.fullmatch(name) and name != 'Scenario': continue
            for line,text in src.commands.items():
                m = re.match(r'@set endingType="([^"]+)"',text)
                if m: self.ending_origins[m[1]].append((name,line))
        # Dungeon's floor / section selectors select actual route scripts at runtime.
        dungeon = self.src['Dungeon']
        if not dungeon.calls['Scenario_{tempPartnerName}{tempScenarioDungeonId}.ToDungeon{tempScenarioDungeonId}'] or not dungeon.calls['Scenario_{tempPartnerName}{dungeonId}.{bossId}{temp}']:
            raise ValueError('Unrecognized dungeon route/section dispatch')

    def callers(self, target):
        return [(name,i) for name,src in self.src.items() if ROUTE.fullmatch(name)
                for i in src.calls.get(target,[])]

    def placement(self,s):
        source, label, line = s['source'],s['label'],s['line']
        src = self.src.get(source)
        def put(role,ch,kind,note='',anchors=()):
            return role,ch,kind,note,list(anchors)
        def at(anchors,kind='battle',note='战斗中触发'):
            anchors = list(anchors)
            origins = {route(n) for n,i in anchors}
            if not origins: raise MissingTrigger(s['id'])
            roles = {r for r,c in origins}
            floors = {c for r,c in origins}
            return put(next(iter(roles)) if len(roles)==1 else 'Shared',
                       next(iter(floors)) if len(floors)==1 else 7,
                       kind,note,anchors)
        def trigger(name,pattern):
            return at([(name,self.src[name].find(pattern))])
        if source=='Extras': return put('Shared',7,'unplaced','未定位画稿')
        if source=='Dungeon': return put('Shared',7,'random','随机触发')
        if source=='GameOver': return put('Shared',7,'conditional','冒险结束时随机出现')
        if source=='TrialEnd':
            if label=='TrialEndCore':
                role = s['id'].rsplit('-',1)[-1]
                return put(role,7,'trial','第1层试玩结尾',
                           [(n,i) for n,i in self.callers('TrialEnd.TrialEndCore') if route(n)[0]==role])
            guards = src.guards.get(line,[])
            role = next((m[1].title() for t in reversed(guards)
                         if (m:=re.search(r'partnerCharacter=="(hero|mage|warrior|priest)"',t))),None)
            if not role: raise MissingTrigger(s['id'])
            calls = self.callers('TrialEnd')+self.callers('TrialEnd.'+label)
            return at([(n,i) for n,i in calls if route(n)[0]==role],'story','')
        if source in ('Ending','Title'):
            guards = self.src['Ending'].guards[line]
            endings = [e for g in guards for e in ENDING.findall(g)]
            if not endings: raise MissingTrigger(s['id'])
            origins = [o for e in endings for o in self.ending_origins[e]]
            if 'dropout' in endings:
                role = next(m[1].title() for g in guards if (m:=re.search(r'partnerCharacter=="(\w+)"',g)))
                origins = [(n,i) for n,i in self.callers('Scenario.DropoutBadEnd') if route(n)[0]==role]
            groups = {route(n)[0] for n,i in origins}
            ch = {route(n)[1] for n,i in origins}
            if len(ch)!=1 or len(groups)!=1: raise MissingTrigger(s['id'])
            floor = ch.pop()
            return put(groups.pop(),6,'ending' if source=='Ending' else 'title',
                       f'第{floor}层结局分支',origins)
        if source.startswith('Opening'):
            if label=='TrialEndSpeedyYes': return put('Shared',7,'trial','序章试玩结尾')
            if source=='Opening3':
                for role in ROLES[:-1]:
                    if label==f'ToDungeon1{role}':
                        start = src.labels['PartnerChoiceEnd'+role]
                        if any(i>start for i in src.calls['.'+label]):
                            return put(role,0,'story','',[(source,line)])
                    if label.lower().startswith(role.lower()) and f'{role.lower()}Scene' in src.labels:
                        return put(role,0,'branch','选择同行者前的可选交谈',[(source,line)])
            return put('Shared',0,'story','',[(source,line)])
        if source=='Scenario':
            if label in ('Conference1','DropoutBadEnd'):
                return at(self.callers('Scenario.'+label),'branch','多条路线共用')
            return put('Shared',7,'conditional','第1至2层条件事件')
        if ROUTE.fullmatch(source):
            ext = self.callers(source+'.'+label)
            external = [(n,i) for n,i in ext if route(n)[0]!=route(source)[0]]
            if external:
                return at(external+[(source,i) for i in src.calls.get('.'+label,[])],
                          'branch','多条路线共用')
            kind = 'branch' if s.get('choice') else 'story'
            return put(*route(source),kind,'并列选项' if kind=='branch' else '',[(source,line)])
        if source!='Battle': raise ValueError(f'Unrecognized story source {source}')
        if label=='EndActionEffectSet' and any('xSwitchTutorialSlimeBattle==1' in g for g in src.guards.get(line,[])):
            return put('Shared',0,'battle','序章教学战斗',[('Opening',self.src['Opening'].find(r'^@set xSwitchTutorialSlimeBattle=1$'))])
        if label=='SkipBgm' and any('partnerCharacter=="hero"' in g for g in src.guards.get(line,[])):
            return trigger('Scenario_Hero1',r'^@set xSwitchBoss1BattleEvent=1$')
        if label=='OutcastHeroCutCore':
            # Hero enters directly. Priest enters the same shots via a literal local jump.
            # The fifth-floor rematch explicitly skips this label.
            names = ['Scenario_Hero1','Scenario_Priest1']
            if not src.calls['.OutcastHeroCutCore']: raise MissingTrigger('first boss cutscene dispatch')
            return at([(n,self.src[n].find(r'^@set xSwitchBoss1BattleEvent=1$')) for n in names])
        if label=='DropoutMageChargeModeBranch':
            return trigger('Scenario_Mage3',r'^@gosub Scenario\.DropoutBattleCore')
        form3 = src.labels.get('PriestFinalMageNotMaryokuForm3CounterText',-1)
        # The third phase contains an internal debug bookmark, reached by natural fallthrough.
        phase3 = form3 >= 0 and form3 < line and all(t!='@return' for t in src.text[form3:line])
        if label.startswith('PriestFinalMageNotMaryokuForm') or phase3:
            return trigger('Scenario_Mage5',r'^@set xSwitchPriestFinalMageNotMaryokuEventAllowed=1$')
        if label.startswith('WarriorIllusion'):
            return trigger('Scenario_Warrior5',r'^@set battleTarget="warriorIllusionB"')
        if label.startswith('WarriorFinalStopBattleText'):
            return trigger('Scenario_Warrior5',r'^@set battleTarget="warriorFinalDuel"')
        if label.startswith('GlausFinalForm'):
            return trigger('Scenario_Priest5',r'^@set battleTarget="demonLord"')
        if label=='SlimeWarriorRightHandSelected':
            return trigger('Scenario_Warrior4',r'^@gosub Scenario\.SlimeBattleCore')
        if label=='WarriorHeadThrowPresentation': return put('Warrior',7,'conditional','战斗技能条件触发')
        if label in ('WarriorHeadVillainessHitPresentation','TurnEndEffectsLoop','VillainessSecondFormTransitionCore'):
            return put('Shared',2,'battle','战斗中条件触发')
        if label=='VillainessReSkipSecondFormText':
            return put('Shared',2,'battle','第2层战斗，第5层可再次出现')
        if label=='PlaySupportAttackPresentation': return put('Shared',5,'battle','战斗中条件触发')
        return put('Shared',7,'conditional','战斗中条件触发')


def apply_story_order(scenes,scripts,menus):
    story = Story(scripts)
    by_source = defaultdict(set)
    places = {}
    for s in scenes:
        try:
            group,ch,kind,note,origins = story.placement(s)
        except (MissingTrigger,KeyError,StopIteration):
            group,ch,kind,note,origins = 'Shared',7,'conditional','触发位置未定位',[]
        if origins and 0<ch<6:
            branches = {route_note(n,story.src[n],i) for n,i in origins}
            if len(branches)==1 and '' not in branches:
                arc = branches.pop()
                note = arc + (' · '+note if note else '')
                if kind=='story': kind='branch'
        s.update(group=group,chapter=ch,sequenceKind=kind)
        if note: s['sequenceNote']=note
        places[s['id']] = origins
        for name,i in origins: by_source[name].add(i)
        if origins and (len(origins)>1 or origins[0]!=(s['source'],s['line'])):
            s['storyOrigins']=[{'source':n,'line':i} for n,i in origins]
    order = {n:story.src[n].local_order(points,menus.get(n,[])) for n,points in by_source.items()}
    section = {'conditional':0,'random':1,'trial':2,'unplaced':3}
    def sortkey(s):
        ch,kind = s['chapter'],s['sequenceKind']
        anchor = places[s['id']]
        if ch==7:
            rank = (section.get(kind,4),s['source'],s['line'])
        elif anchor:
            def source_rank(n):
                if n.startswith('Opening'): return {'Opening':0,'Opening2':1,'Opening3':2}.get(n,3)
                return route(n)[1]
            choose = max if kind=='title' else min
            rank = choose((source_rank(n),*arc_position(n,story.src[n],i),order[n][i]) for n,i in anchor)
        else:
            rank = (ch,0,0)
        # Dynamic variants can share even the same @back command. Its order comes from
        # the original translated menu, not alphabetization of the branch label.
        choice_order = s.get('choice',{}).get('offset',0)
        return ROLES.index(s['group']),ch,rank,kind=='title',s['line'],choice_order,s['id']
    scenes.sort(key=sortkey)
    nums = Counter()
    for s in scenes:
        ch = s['chapter']
        section_kind = s['sequenceKind'] if ch==7 else ''
        key = s['group'],ch,section_kind
        nums[key]+=1
        section_name = {0:'序章',6:'终章',7:{'conditional':'条件事件','random':'迷宫事件',
                         'trial':'试玩篇','unplaced':'独立画稿'}.get(section_kind,'附录')}.get(ch,f'第{ch}层')
        s['title'] = f'{section_name} · {nums[key]:02d}'
        if not s.get('reveal'): s['reveal'] = s['title']
