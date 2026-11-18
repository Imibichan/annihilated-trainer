"""Resolve the original scenery registers using only Naninovel's visual data."""
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import re

SCENERY = {
    'FrameBackground', 'FarBackground', 'SceneBackground', 'RoadBackground', 'ObjectBackground',
    'OptionalBackground', 'MainBackground', 'ColorFlashBackground', 'ColorFlashBackground2'
}
BG_PREFIXES = tuple('Naninovel/Backgrounds/' + actor + '/' for actor in sorted(SCENERY))
KNOBS = ('backgroundName', 'backgroundSetOption', 'farBackgroundName', 'frameBackgroundName',
         'roadBackgroundName', 'sceneBackgroundName', 'objectBackgroundName')
FLOORS = {1: 'dungeon_blue', 2: 'heights', 3: 'sea', 4: 'dungeon_red'}
NAMES = ('dungeon_blue', 'heights', 'sea', 'dungeon_red', 'stairs', 'last', 'maou_naka', 'sky', 'sky_night',
         'maou_gyokuza', 'first', 'door', 'doorClosed', 'cave_moss', 'town_fire')
COMMAND = re.compile(r'^\s*@(\w+)\b\s*(.*)$')
PARAM = re.compile(r'(?:^|\s)(\w+):(?:"([^"]*)"|(\S+))')
EXPR = re.compile(r'^(\w+)(==|!=|=)"([^"]*)"$')


def params(body):
    return {m[1].lower(): m[2] if m[2] is not None else m[3] for m in PARAM.finditer(body)}


def first(body):
    m = re.match(r'^"([^"]*)"|^(\S+)', body)
    return (m[1] if m[1] is not None else m[2]) if m else ''


def number(value):
    value = value.strip().strip('{}')
    m = re.fullmatch(r'vcamDefaultZ(?:([+-])([\d.]+))?', value, re.I)
    if m: return -100.0 + (float(m[2]) * (1 if m[1] == '+' else -1) if m[2] else 0)
    try:
        return float(value)
    except ValueError:
        return None


def components(value, prior, uniform=False):
    items = value.split(',')
    if uniform and len(items) == 1: items *= 3
    result = list(prior)
    for i, p in enumerate(items[:3]):
        v = number(p)
        if v is not None: result[i] = v
    return result


def empty(mode='unresolved'):
    return {'mode': mode, 'name': '', 'layers': {}, 'prefab': '', 'prefabOffset': [0, 0, 0]}


def layer(actor, appearance, attr, before=None):
    out = dict(
        before or {
            'actor': actor,
            'x': 50.,
            'y': 50.,
            'z': 0.,
            'scaleX': 1.,
            'scaleY': 1.,
            'scaleZ': 1.,
            'rotX': 0.,
            'rotY': 0.,
            'rotZ': 0.,
            'tint': '#FFFFFFFF',
            'visible': True
        })
    if appearance:
        out['appearance'] = appearance
        out['visible'] = True
    for key, fields, uniform in [('pos', ('x', 'y', 'z'), False),
                                 ('scale', ('scaleX', 'scaleY', 'scaleZ'), True),
                                 ('rotation', ('rotX', 'rotY', 'rotZ'), False)]:
        if key in attr:
            vs = components(attr[key], [out[f] for f in fields], uniform)
            for f, v in zip(fields, vs):
                out[f] = v
    if 'tint' in attr: out['tint'] = attr['tint'].upper()
    if 'visible' in attr: out['visible'] = attr['visible'].lower() == 'true'
    return out


def assign(body):
    m = re.match(r'(\w+)=("[^"]*"|\S+)', body)
    return (m[1], m[2].strip('"')) if m else ('', '')


def expand(text, knobs):
    return re.sub(r'\{(\w+)\}', lambda m: knobs.get(m[1], m[0]), text)


def matches(expression, knobs):
    for alternative in expression.split('||'):
        ok = True
        for term in alternative.split('&&'):
            m = EXPR.fullmatch(term)
            if not m: raise ValueError(f'Unrecognized Func.ShowBackground predicate {term}')
            v = knobs.get(m[1], '')
            ok = ok and ((v != m[3]) if m[2] == '!=' else (v == m[3]))
        if ok: return True
    return False


def export(bg):
    result = {k: v for k, v in bg.items() if k != 'layers'}
    result['layers'] = [{
        k: v
        for k, v in item.items() if k != 'visible'
    } for item in sorted(bg['layers'].values(), key=lambda v: -v['z'])
                        if item.get('visible') and item.get('appearance') and not item['tint'].endswith('00')]
    return result


class Recipes:

    def __init__(self, rows, addresses):
        self.ad = {k.lower() for k in addresses}
        self.unregistered = set()
        self.cache = {}
        labels = {r[3].strip().lstrip('#').strip(): r[0] for r in rows if r[1] == 'Label'}
        # ShowBackground falls through to ShowObjectBackground, which calls the object preparation
        # block and jumps to the final visibility block. This is their original order.
        self.blocks = {
            k: rows[labels[k] + 1:labels[next_label]]
            for k, next_label in [(
                'ShowBackground',
                'ShowObjectBackground'), (
                    'PrepareObjectBackground',
                    'ShowPreparedObjectBackground'), ('ShowPreparedObjectBackground', 'HideBackground')]
        }

    def known(self, actor, look):
        return ('Naninovel/Backgrounds/' + actor + '/' + look).lower() in self.ad

    def apply(self, bg, actor, look, attrs):
        if actor not in SCENERY: return
        if look and not self.known(actor, look):
            self.unregistered.add((actor, look))
            bg['layers'].pop(actor, None)
            return
        if not look and actor not in bg['layers']: return
        bg['layers'][actor] = layer(actor, look, attrs, bg['layers'].get(actor))

    def get(self, name, knobs=None, objects_only=False):
        init = {k: '' for k in KNOBS}
        init.update(knobs or {})
        init['backgroundName'] = name
        key = (tuple(sorted(init.items())), objects_only)
        if key in self.cache: return deepcopy(self.cache[key])
        bg = empty('script')
        bg['name'] = name
        order = ['PrepareObjectBackground', 'ShowPreparedObjectBackground']
        if not objects_only: order.insert(0, 'ShowBackground')
        for part in order:
            stack = []
            active = True
            for _, kind, _, line, _ in self.blocks[part]:
                if kind != 'Command': continue
                m = COMMAND.match(line)
                if not m: continue
                cmd, body = m.groups()
                cmd = cmd.lower()
                if cmd == 'if':
                    test = active and matches(body.strip(), init)
                    stack.append([active, test])
                    active = test
                    continue
                if cmd in ('elseif', 'else'):
                    parent, accepted = stack[-1]
                    test = parent and not accepted and (cmd == 'else' or matches(body.strip(), init))
                    active = test
                    stack[-1][1] |= test
                    continue
                if cmd == 'endif':
                    active = stack.pop()[0]
                    continue
                if not active: continue
                at = params(body)
                if 'if' in at and not matches(at['if'], init): continue
                at = {k: expand(v, init) for k, v in at.items()}
                if cmd == 'set':
                    k, v = assign(body)
                    init[k] = expand(v, init)
                elif cmd == 'backgroundprefab':
                    bg['prefab'] = '' if at.get('isremove') == 'true' else expand(first(body), init)
                    bg['prefabOffset'] = components(at.get('offset', ''), (0, 0, 0))
                elif cmd == 'back':
                    self.apply(bg, at.get('id', 'MainBackground'), expand(first(body), init), at)
                elif cmd in ('hide', 'show'):
                    actor = first(body)
                    if actor in bg['layers']: bg['layers'][actor]['visible'] = cmd == 'show'
        self.cache[key] = bg
        return deepcopy(bg)


def camera_default():
    return {'positionMode': 'offset', 'offset': [0., 0., -100.], 'rotation': [0., 0., 0.]}


def update_camera(camera, attr):
    for field in ('offset', 'pos', 'rotation'):
        for suffix in ('', 'add'):
            key = field + suffix
            if key not in attr: continue
            token = attr[key]
            if not suffix and field in ('offset', 'pos'):
                # The two native commands position the same camera using different coordinate spaces.
                # A full assignment in one space supersedes any historical value in the other.
                if all(number(v) is not None for v in token.split(',')[:3]) and token.count(',') == 2:
                    camera.pop('dynamic', None)
            base = camera.get(field, (0, 0, 0) if field == 'rotation' else (0, 0, -100))
            for part in token.split(','):
                if part and number(part) is None: camera['dynamic'] = True
            if suffix:
                delta = components(token, (0, 0, 0))
                camera[field] = [a + b for a, b in zip(base, delta)]
            else:
                camera[field] = components(token, base)
            if field in ('offset', 'pos'): camera['positionMode'] = field


def state_for(recipes, name='', mode='unresolved'):
    bg = recipes.get(name) if name else empty(mode)
    bg['mode'] = mode
    return {'bg': bg, 'vars': {'backgroundName': name}, 'camera': camera_default()}


def restore_scene(state, bg):
    # Func changes only scenery actors; a flash or cut-in continues to exist until explicitly hidden.
    kept = {
        k: v
        for k, v in state['bg']['layers'].items()
        if k in ('MainBackground', 'OptionalBackground', 'ColorFlashBackground', 'ColorFlashBackground2')
    }
    state['bg'] = bg
    state['bg']['layers'].update(kept)


def merged(states):
    # A common visual can survive different conditions even when unrelated variables differ.
    if len(states) == 1: return deepcopy(states[0])
    result = deepcopy(states[0])
    if any(x['bg'] != result['bg'] for x in states[1:]):
        matched = {
            k: v
            for k, v in result['bg']['layers'].items() if all(t['bg']['layers'].get(k) == v for t in states)
        }
        names = {x['bg']['name'] for x in states}
        result['bg']['layers'] = matched
        if len(names) > 1:
            result['bg']['mode'] = 'unresolved'
            result['bg']['name'] = ''
            result['bg']['prefab'] = ''
        elif any(t['bg']['prefab'] != result['bg']['prefab'] for t in states):
            result['bg']['prefab'] = ''
    result['vars'] = {k: v for k, v in result['vars'].items() if all(t['vars'].get(k) == v for t in states)}
    if any(t['camera'] != result['camera'] for t in states): result['camera'] = camera_default()
    return result


def source_context(name, label, scene_chapters, recipes):
    # Explicit area transitions further down the script override the exploring-room default.
    route = re.fullmatch(r'Scenario_(?:Hero|Mage|Warrior|Priest)([1-4])', name)
    floor = int(route[1]) if route else 0
    if floor: return state_for(recipes, FLOORS[floor], 'inherited')
    if name == 'Battle':
        chapters = scene_chapters.get(label, set())
        if len(chapters) == 1 and next(iter(chapters)) in FLOORS:
            return state_for(recipes, FLOORS[next(iter(chapters))], 'inherited')
    return state_for(recipes)


def scan(name, rows, points, recipes, chapter_labels, known_calls, collect_calls):
    snapshots = {}
    context = source_context(name, '', chapter_labels, recipes)
    terminated = False
    carry = defaultdict(list)
    branches = []
    label = ''
    external = known_calls.get(name, {})
    for idx, kind, _, raw, _ in rows:
        if kind == 'Label':
            label = raw.strip().lstrip('#').strip()
            inputs = list(carry.get(label, []))
            inputs.extend(external.get(label, []))
            if not terminated: inputs.append(context)
            context = merged(inputs) if inputs else source_context(name, label, chapter_labels, recipes)
            terminated = False
        elif kind == 'Command':
            m = COMMAND.match(raw)
            if not m: continue
            cmd, body = m.groups()
            cmd = cmd.lower()
            at = params(body)
            token = first(body)
            if cmd == 'if':
                branches.append([deepcopy(context), [], False])
            elif cmd in ('else', 'elseif') and branches:
                base, ends, _ = branches[-1]
                if not terminated: ends.append(deepcopy(context))
                context = deepcopy(base)
                branches[-1][2] = cmd == 'else'
                terminated = False
            elif cmd == 'endif' and branches:
                base, ends, has_else = branches.pop()
                if not terminated: ends.append(context)
                if not has_else: ends.append(base)
                if ends:
                    context = merged(ends)
                    terminated = False
            elif cmd == 'set':
                k, v = assign(body)
                k = next((key for key in KNOBS if key.lower() == k.lower()), k)
                if k in KNOBS and 'if' not in at:
                    context['vars'][k] = expand(v, context['vars'])
            elif cmd == 'gosub' and token.lower() in ('func.showbackground', 'func.showobjectbackground'):
                knobs = context['vars']
                setting = knobs.get('backgroundName') or context['bg']['name']
                if setting in NAMES:
                    if token.lower() == 'func.showbackground':
                        restore_scene(context, recipes.get(setting, knobs))
                    else:
                        add = recipes.get(setting, knobs, objects_only=True)['layers']
                        context['bg']['layers'].pop('ObjectBackground', None)
                        context['bg']['layers'].update(add)
                else:
                    restore_scene(context, empty())
                context['vars'] = {'backgroundName': setting}
            elif cmd == 'gosub' and token.lower() == 'func.hidebackground':
                old = context['bg']
                old['prefab'] = ''
                old['mode'] = 'plain'
                old['name'] = ''
                for actor in ('FrameBackground', 'FarBackground', 'RoadBackground', 'SceneBackground'):
                    old['layers'].pop(actor, None)
            elif cmd == 'gosub' and token.lower() == 'first.beforegonovel':
                context['bg']['layers'].pop('FrameBackground', None)
            elif cmd == 'backgroundprefab':
                context['bg']['prefab'] = '' if at.get('isremove') == 'true' else expand(
                    token, context['vars'])
                context['bg']['prefabOffset'] = components(at.get('offset', ''), (0, 0, 0))
            elif cmd == 'back':
                actor = at.get('id', 'MainBackground')
                look = '' if ':' in token else expand(token, context['vars'])
                if actor == 'MainBackground' and look.lower().startswith('cg/'):
                    context['bg']['layers'].pop(actor, None)
                elif actor in SCENERY:
                    recipes.apply(context['bg'], actor, look, at)
            elif cmd in ('hide', 'show'):
                for actor in token.split(','):
                    if actor in context['bg']['layers']:
                        context['bg']['layers'][actor]['visible'] = cmd == 'show'
            elif cmd == 'vcam':
                update_camera(context['camera'], at)
            if cmd in ('choice', 'choicer', 'goto', 'gosub'):
                dest = at.get('goto', '') if 'choice' in cmd else token
                if dest.startswith('.') and '{' not in dest:
                    if context['bg']['mode'] != 'unresolved' and cmd != 'gosub':
                        carry[dest[1:]].append(deepcopy(context))
                elif '.' in dest and '{' not in dest and collect_calls is not None:
                    other, dest_label = dest.split('.', 1)
                    if other.startswith('Scenario') or other in ('Battle', 'GameOver', 'Opening', 'Opening2',
                                                                 'Opening3', 'TrialEnd'):
                        if context['bg']['mode'] != 'unresolved':
                            collect_calls[other][dest_label].append(deepcopy(context))
            if cmd in ('goto', 'stop', 'return', 'title') and 'if' not in at:
                terminated = True
        if idx in points: snapshots[idx] = deepcopy(context)
    return snapshots


def normalized(bg, frame):
    bg = export(bg)
    layers = bg['layers']
    occupied = {b['actor'] for b in frame['bindings']}
    depth = max(l['z'] for l in frame['layout'])
    # Apply only backings behind the illustration. Front flashes intentionally cover the
    # screen mid-transition, not the still being browsed.
    layers = [l for l in layers if l['actor'] not in occupied and l['z'] >= depth]
    # The gallery keeps the documented room visible behind the illustration even during
    # a story blackout. Preserve source overlay evidence independently of the rendering list.
    scenic = bool(bg['prefab']
                  or any(l['actor'] in ('RoadBackground', 'FrameBackground', 'SceneBackground',
                                        'FarBackground', 'ObjectBackground', 'OptionalBackground')
                         for l in layers))
    if scenic:
        screens = [
            l for l in layers if l['actor'].startswith('ColorFlash') and l['appearance'] in (
                'white', 'black') and abs(l['scaleX']) >= 100
        ]
        if screens:
            bg['sourceScreens'] = screens
            layers = [l for l in layers if l not in screens]
    else:
        solid = [
            l for l in layers if l['actor'].startswith('ColorFlash') and l['appearance'] in (
                'black', 'white') and l['tint'][-2:] == 'FF' and abs(l['scaleX']) >= 100
        ]
        if solid:
            closest = min(l['z'] for l in solid)
            layers = [l for l in layers if l['z'] <= closest]
            bg['mode'] = 'plain'
    bg['layers'] = layers
    return bg


def ending_settings(scene, rows):
    start = scene['line']
    finish = next((r[0] for r in rows[start + 1:] if '@set endingImageSetKey=' in r[3]), len(rows))
    settings = {}
    for _, kind, _, t, _ in rows[start:finish]:
        if kind != 'Command': continue
        m = re.match(r'^\s*@set (endingImageScale[1-5]|yValEndingImageOffset[XY][1-5])="?(-?[\d.]+)"?', t)
        if m: settings[m[1]] = float(m[2])
    return settings


def recover_callback(source, scene, frame, state, recipes):
    """Battle/Naninovel callbacks are sometimes entered by the engine rather than by a goto.
    Anchor those settings at the actual caller or the source's floor/section transition.
    Unrecognized callbacks keep their unknown state rather than guessing by the picture name.
    """
    b = state['bg']
    label = scene['label']
    appearance = frame['bindings'][-1]['appearance'].lower()
    named = ''
    provenance = ''
    alternatives = []
    # Count these as physical rooms even where the filmmaker temporarily removes the entire
    # room rig to light an insert. The story immediately before/after the insert establishes
    # where it occurs. Epilogues, visions, prologue resurrection and full-screen cuts retain
    # their own color fields unless the source specifies a room.
    if source == 'Scenario_Mage1' and label == 'MergeSearch' and b['mode'] == 'plain':
        named, provenance = 'dungeon_blue', 'Scenario_Mage1.MergeSearch -> Func.ShowBackground(dungeon_blue)'
    elif source == 'Scenario_Mage5' and label == 'WakimitiRoute' and not b['name']:
        named, provenance = 'dungeon_blue', 'Dungeon.event903 / Dungeon.ExploreStart(dungeonId=9,sectionId>1)'
    elif b['mode'] != 'unresolved':
        return state
    elif source == 'Battle':
        if label == 'OutcastHeroCutCore' or (label == 'SkipBgm' and appearance == 'cg/outcaststart'):
            named, provenance = 'dungeon_blue', 'Scenario_Hero1.OutcastBattleBefore'
        elif label.startswith('WarriorIllusion'):
            named, provenance = 'maou_naka', 'Scenario_Warrior5.Last2 / Dungeon.ExploreStart(dungeonId=6,sectionId>1)'
        elif label.startswith('GlausFinal'):
            named, provenance = 'maou_gyokuza', 'Scenario_Priest5.DemonLordBattleBefore'
        elif label.startswith('WarriorFinalStop'):
            named, provenance = 'maou_gyokuza', 'Scenario_Warrior5.WarriorBattleBeforePoint'
        elif label.startswith('PriestFinalMageNotMaryoku') or label == 'HatsugenTest22':
            named, provenance = 'last', 'Scenario_Mage5.Test7 / Battle.PriestFinalFormChangeEffect'
        elif label == 'TurnEndEffectsLoop' and 'villainesskisscut' in appearance:
            named, provenance = 'heights', 'Battle.End / Battle.VillainessSecondFormTransitionCore'
            alternatives = ['heights', 'town_fire']
        elif label == 'PlaySupportAttackPresentation':
            named, provenance = 'last', 'Battle.PriestFinalMageNotMaryoku / Battle.GlausFinal'
            alternatives = ['last', 'maou_gyokuza']
        elif label in ('EnemiesActionLoop', 'EndActionEffectSet', 'WarriorHeadThrowPresentation'):
            # Reusable enemy/weapon action: the original current battle room is a runtime input.
            named, provenance = 'dungeon_blue', 'Battle / Dungeon.ExploreStart'
            alternatives = [
                'dungeon_blue', 'heights', 'sea', 'dungeon_red', 'last', 'maou_naka', 'maou_gyokuza'
            ]
    elif source == 'Scenario_Mage5' and label == 'PriestBattleBadRouteBattleFinale':
        named, provenance = 'last', 'Scenario_Mage5.PriestBattleBeforeBadRouteBunki -> Battle'
    elif source == 'Scenario_Mage5' and label == 'PriestBattleAfterNige':
        # The run command restores priestFinalEscapeBackgroundName to the room the fight started in;
        # Wakimiti is floor 9 in exploration (blue outside the first stair section).
        named, provenance = 'dungeon_blue', 'Scenario_Mage5.WakimitiRoute / Battle.Run / Dungeon.ExploreStart'
        alternatives = ['dungeon_blue', 'stairs']
    elif source == 'Scenario_Priest5' and label.startswith('PriestBattleHighLoop'):
        named, provenance = 'last', 'Scenario_Priest5.PriestBattleBefore / Dungeon.ExploreStart(dungeonId=7,sectionId>1)'
    elif source == 'TrialEnd' and label != 'TrialEndCore':
        named, provenance = 'dungeon_blue', 'Scenario_Hero1/Scenario_Mage1/Scenario_Priest1/Scenario_Warrior1 -> TrialEnd'
        alternatives = ['dungeon_blue', 'stairs']
    if not named: return state
    state = deepcopy(state)
    bg = recipes.get(named)
    bg['mode'] = 'variable' if alternatives else 'inherited'
    bg['origin'] = provenance
    if alternatives: bg['alternateNames'] = alternatives
    bg['layers'].update(b['layers'])
    state['bg'] = bg
    return state


def room_signature(background):
    scenery = tuple((l['actor'], l['appearance']) for l in background['layers']
                    if not l['actor'].startswith('ColorFlash'))
    return background['name'], background['prefab'], scenery


def split_at_room_changes(scene, frame, samples, lookup, rows, snapshots, recipes):
    """Keep a fresh still when the same picture is re-used in a visibly different room."""
    if len(samples) < 2: return [frame]
    result = [frame]
    previous = room_signature(frame['background'])
    boundaries = []
    for earlier, point in zip(samples, samples[1:]):
        state = recover_callback(scene['source'], scene, frame, snapshots[point], recipes)
        background = normalized(state['bg'], frame)
        signature = room_signature(background)
        if signature == previous: continue
        item = deepcopy(result[-1])
        original_pose = {b['actor']: (b, pos) for b, pos in zip(item['bindings'], item['layout'])}
        start = point
        for idx, kind, _, line, _ in rows[earlier + 1:point + 1]:
            command = COMMAND.match(line) if kind == 'Command' else None
            if not command: continue
            cmd, body = command.groups()
            if cmd.lower() == 'gosub' and first(body).lower() == 'func.showbackground': start = idx
            if cmd.lower() != 'back': continue
            attr = params(body)
            actor = attr.get('id', 'MainBackground')
            if actor not in original_pose: continue
            binding, pose = original_pose[actor]
            look = first(body)
            if look and ':' not in look and binding['appearance'].lower() != look.lower(): continue
            start = idx
            xyz = components(attr.get('pos', ''), [pose[k] for k in ('x', 'y', 'z')])
            pose.update(zip(('x', 'y', 'z'), xyz))
            if 'scale' in attr: pose['scale'] = components(attr['scale'], [pose['scale']] * 3)[0]
            if 'rotation' in attr:
                pose['rotation'] = components(attr['rotation'], [0, 0, pose['rotation']])[2]
        item.update(line=start, background=background, camera=state['camera'])
        boundaries.append(point)
        previous = signature
        result.append(item)
    if boundaries:
        from bisect import bisect_right
        lines = frame['lines']
        for item in result:
            item['lines'] = []
        slot = 0
        for line in lines:
            target = lookup.get(line['offset'])
            if target is not None: slot = bisect_right(boundaries, target)
            result[slot]['lines'].append(line)
    return result


def add_scenery(scenes, assets, raw, local_refs, addresses, metrics):
    recipes = Recipes(raw['Func'], addresses)
    for a in assets:
        a.update(metrics['assets'][a['path']])
        if 'resource' in a: a['localizedGeometry'] = metrics['localized'][a['resource'].lower()]
    by_source = defaultdict(list)
    for s in scenes:
        by_source[s['source']].append(s)
    frames_by_point = defaultdict(lambda: defaultdict(list))
    lookups = {}
    all_points = defaultdict(set)
    chapters = defaultdict(lambda: defaultdict(set))
    for source, items in by_source.items():
        if source not in raw or source in ('Title', 'Ending', 'Dungeon'): continue
        lookup = {ref['offset']: idx for idx, ref in local_refs.get(source, {}).items()}
        lookups[source] = lookup
        for s in items:
            chapters[source][s['label']].add(s['chapter'])
            for i, f in enumerate(s['frames']):
                first = f['line']
                limit = s['frames'][i + 1]['line'] if i + 1 < len(s['frames']) else len(raw[source])
                points = [
                    lookup[l['offset']] for l in f['lines']
                    if l['offset'] in lookup and first <= lookup[l['offset']] < limit
                ]
                point = min(points) if points else first
                samples = sorted(set(points))
                all_points[source].update(samples + [point])
                frames_by_point[source][point].append((s, f, samples))
    calls = defaultdict(lambda: defaultdict(list))
    for n in raw:
        if n.startswith('Scenario') or n in ('Battle', 'Dungeon', 'Opening', 'Opening2', 'Opening3',
                                             'GameOver'):
            scan(n, raw[n], set(), recipes, chapters[n], {}, calls)
    for n, points in frames_by_point.items():
        snaps = scan(n, raw[n], all_points[n], recipes, chapters[n], calls, None)
        splits = {}
        for point, frames in points.items():
            state = snaps[point]
            for scene, frame, samples in frames:
                if n == 'TrialEnd' and scene['label'] == 'TrialEndCore':
                    f_at = params(COMMAND.match(raw[n][frame['line']][3])[2])
                    frame['layout'][0].update(x=50, y=50, z=-6, scale=float(f_at['scale']))
                    # The final trial card itself is a complete localized illustration.
                    matte = empty('plain')
                    recipes.apply(matte, 'ColorFlashBackground', 'black', {
                        'pos': ',,-5.5',
                        'scale': '9999999',
                        'tint': '#000000FF'
                    })
                    frame['background'] = normalized(matte, frame)
                else:
                    recovered = recover_callback(n, scene, frame, state, recipes)
                    frame['background'] = normalized(recovered['bg'], frame)
                frame['camera'] = state['camera']
                splits[id(frame)] = split_at_room_changes(scene, frame, samples, lookups[n], raw[n], snaps,
                                                          recipes)
        for scene in by_source[n]:
            scene['frames'] = [f for original in scene['frames'] for f in splits[id(original)]]
    for s in scenes:
        source = s['source']
        if source not in ('Dungeon', 'Title', 'Ending', 'Extras'): continue
        settings = ending_settings(s, raw['Ending']) if source == 'Ending' else {}
        for f in s['frames']:
            look = f['bindings'][0]['appearance']
            if source == 'Title':
                titled = 'CG/endingTitle' in look
                name = ('sky_night' if 'PriestSlowLife' in look else
                        ('maou_gyokuza' if 'MageSecret' in look else 'sky'))
                bg = recipes.get(name) if titled else empty('plain')
                f['layout'][0].update(x=50, y=50, z=-16, scale=.38734 if titled else .23)
            elif source == 'Ending':
                bg = empty('plain')
                recipes.apply(bg, 'ColorFlashBackground', 'black', {
                    'pos': ',,-15.5',
                    'scale': '9999999',
                    'tint': '#FFFFFFFF'
                })
                slot = re.search(r'endingImage([1-5])=', raw['Ending'][f['line']][3])[1]
                f['layout'][0].update(x=43.75 + settings.get('yValEndingImageOffsetX' + slot, 0),
                                      y=50 + settings.get('yValEndingImageOffsetY' + slot, 0),
                                      z=-16,
                                      scale=settings.get('endingImageScale' + slot, .262))
            elif source == 'Dungeon':
                display = next(r[3] for r in raw['Dungeon']
                               if r[3].strip().startswith('@back {tempTargetName} id:OptionalCGBackground'))
                pose = layer('OptionalCGBackground', '', params(COMMAND.match(display)[2]))
                f['layout'][0].update(x=pose['x'],
                                      y=pose['y'],
                                      z=pose['z'],
                                      scale=pose['scaleX'],
                                      rotation=pose['rotZ'])
                bg = recipes.get('dungeon_blue')
                bg['mode'] = 'variable'
                bg['alternateNames'] = [
                    'dungeon_blue', 'heights', 'sea', 'dungeon_red', 'stairs', 'last', 'maou_naka'
                ]
            else:
                bg = empty('standalone')
            f['background'] = normalized(bg, f)
            f['camera'] = camera_default()
    return {n: export(recipes.get(n)) for n in NAMES}, recipes.unregistered
