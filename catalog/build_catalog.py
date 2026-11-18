"""Build a spoiler-neutral illustrated scene index from local, read-only game data."""
import argparse
import collections

import hashlib
import json
import re
from pathlib import Path

from addressables import address_paths
from backgrounds import add_scenery, BG_PREFIXES
from links import add_companion_links, add_branch_links, collect_menus
from story_order import apply_story_order

ROOT = 'Naninovel/Backgrounds/'
MAIN = 'MainBackground'
GROUPS = ('Hero', 'Mage', 'Warrior', 'Priest')
SPEAKERS = {
    'Hero': '勇者',
    'HeroTrue': '勇者',
    'MiniHero': '勇者',
    'Mage': '魔法师',
    'Warrior': '战士',
    'Priest': '僧侣',
    'Me{playerType}': '士兵',
    'MiniMe{playerType}': '士兵',
    'Dropout': '落选者',
    'Villainess': '反派千金',
    'Outcast': '放逐者',
    'Dealer': '荷官',
    'Slime': '史莱姆',
    'SlimeBlue': '蓝色史莱姆',
    'BlueSlime': '蓝色史莱姆',
    'Mob': '路人'
}
EFFECT_TYPES = {'glowtex', 'glitchtex', 'effect', 'masktex', 'burntex', 'trashtex'}
REVEAL_WORDS = [('epilogue', '尾声'), ('highloop', '轮回深处'), ('lowsan', '濒临崩溃'),
                ('poker', '牌桌'), ('casino', '赌场'), ('yubikiri', '拉钩'), ('kaigi', '会议'), ('conference', '会议'),
                ('dropout', '落选者'), ('outcast', '放逐者'), ('villainess', '反派千金'), ('dealer', '荷官'),
                ('slime', '史莱姆'), ('camp', '营地'), ('battle', '交锋'), ('trial', '试玩篇'), ('ending', '终幕'),
                ('choice', '抉择'), ('todungeon', '出发'), ('trump', '纸牌'), ('grave', '墓地')]
SOURCE_ORDER = [
    'Opening', 'Opening2', 'Opening3', 'Scenario', 'Battle', 'Dungeon', 'GameOver', 'TrialEnd', 'Ending'
]
CMD = re.compile(r'^\s*@([\w]+)(?:\s+|$)(.*)', re.S)
ARG = re.compile(r'(?:^|\s)([A-Za-z]+):(?:"([^"]*)"|([^\s]+))')
FIRST = re.compile(r'^"((?:\\.|\{[^{}]*\}|[^"\\])*)"|^(\S+)')
SPEAKER = re.compile(r'^\s*([\w{}.&＆]+):\s*')


def json_read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def args_of(body):
    return {m[1].lower(): m[2] if m[2] is not None else m[3] for m in ARG.finditer(body)}


def first_arg(body):
    match = FIRST.match(body)
    if not match: return ''
    return next(v for v in match.groups() if v is not None)


def translations(source, localized):
    """Match original line hashes, preserving repeated occurrences and translated substrings."""
    by_hash = collections.defaultdict(list)
    label = ''
    for _, kind, _, t, offset in localized:
        if kind == 'Label':
            label = t.strip().removeprefix('#').strip()
            continue
        speaker = ''
        line_kind = 'text'
        if kind == 'GenericText':
            name = SPEAKER.match(t)
            if name:
                speaker = '、'.join(SPEAKERS.get(role, role) for role in re.split('[&＆]', name[1]))
                start = name.end()
            else:
                start = len(t) - len(t.lstrip())
            end = len(t.rstrip())
        elif kind == 'Command':
            command = CMD.match(t)
            if not command or command[1].lower() not in ('choice', 'choicer', 'print', 'append'):
                continue
            body = command[2]
            quoted = FIRST.match(body)
            if not quoted: continue
            arg = 1 if quoted[1] is not None else 2
            start = command.start(2) + quoted.start(arg)
            end = command.start(2) + quoted.end(arg)
            attrs = args_of(body)
            actor = attrs.get('author', '')
            speaker = SPEAKERS.get(actor, actor)
            if command[1].lower().startswith('choice'):
                line_kind = 'choice'
                # Roulette choices append machine-only answer tags after their visible caption.
                tags = re.search(r'\[(?:[a-z_]+(?:\]|:)|cif=|tooltip=)', t[start:end], re.I)
                if tags: end = start + tags.start()
        else: continue
        if start >= end: continue
        ref = {
            'speaker': speaker,
            'offset': offset + len(t[:start].encode('utf8')),
            'length': len(t[start:end].encode('utf8')),
            'kind': line_kind
        }
        inline = re.search(r'\[(back [^\]]+)\]', t[start:end], re.I)
        if inline and kind == 'GenericText':
            pre = t[start:start + inline.start()].encode('utf8')
            post = t[start + inline.end():end].encode('utf8')
            ref['inline'] = (dict(ref, length=len(pre)), inline[1],
                             dict(ref, offset=ref['offset'] + ref['length'] - len(post), length=len(post)))
        by_hash[label].append(ref)
    seen = collections.Counter()
    mapped = {}
    for idx, kind, h, t, _ in source:
        if kind not in ('Command', 'GenericText') or h not in by_hash: continue
        refs = by_hash[h]
        i = seen[h]
        mapped[idx] = refs[min(i, len(refs) - 1)]
        seen[h] += 1
    return mapped


class Library:

    def __init__(self, entries, addr, localized_names=()):
        image_files = {row[1]: row for row in entries if row[2] == 'Texture2D'}
        aliases = collections.defaultdict(list)
        for key, path in addr.items():
            aliases[path].append(key)
        self.assets = []
        self.lookup = {}
        self.names = collections.defaultdict(list)
        for path, names in sorted(aliases.items()):
            row = image_files[path]
            names.sort(key=lambda n: (not n.startswith(ROOT + MAIN + '/CG/'), len(n), n))
            primary = names[0]
            aid = len(self.assets)
            info = {'id': aid, 'bundle': row[0], 'path': path, 'address': primary}
            stem = Path(path).stem.lower()
            if stem in ('background_white', 'kariend1', 'kariend2', 'toumei'):
                info['kind'] = 'technical'
            elif stem.endswith('effect') or path.endswith('/blood.png') or '/Enemy/' in path:
                info['kind'] = 'overlay'
            else:
                info['kind'] = 'art'
            for alias in names:
                localized = alias.replace('Naninovel/', 'Naninovel/Localization/zh-CN/', 1)
                if localized.lower() in localized_names:
                    info['resource'] = localized
                    break
            self.assets.append(info)
            for name in names:
                key = name[len(ROOT):]
                self.lookup[key.lower()] = aid
                self.names[aid].append(key.split('/', 1))

    def pair(self, actor, token):
        pair = []
        for i in (1, 2):
            name = token.replace('{playerType}', str(i)).replace('{otherPlayerType}', str(3 - i))
            key = (actor + '/' + name).lower()
            if key not in self.lookup: return None
            pair.append(self.lookup[key])
        return tuple(pair)


def route(name, label=''):
    match = re.fullmatch(r'Scenario_(Hero|Mage|Warrior|Priest)([1-5])', name)
    if match: return match[1], int(match[2])
    if name == 'Opening3':
        for g in GROUPS:
            if label.lower().startswith(g.lower()): return g, 0
    if name == 'TrialEnd':
        for g in GROUPS:
            if g.lower() in label.lower(): return g, 2
    if name in ('GameOver', 'Battle'):
        key = label.lower()
        for g in GROUPS:
            if g.lower() not in key: continue
            chapter = next((ch for term, ch in (('final', 5), ('illusion', 5), ('slime', 4), ('dropout', 3),
                                                ('villainess', 2), ('outcast', 1)) if term in key), None)
            return g, chapter if chapter is not None else 0
    return 'Shared', 0 if name.startswith('Opening') else (1 if name in ('Scenario', 'Battle',
                                                                         'Dungeon') else 6)


def reveal_name(label, stem):
    s = (label + ' ' + stem).lower()
    for key, value in REVEAL_WORDS:
        if key in s: return value
    return ''


def snapshot(layers):
    visible = [(key, layer) for key, layer in layers.items() if layer['visible'] and layer.get('pair')]
    visible.sort(key=lambda item: (-item[1]['z'], item[0]))
    return [(key, layer.copy()) for key, layer in visible]


def clone(state):
    return {key: value.copy() for key, value in state.items()}


def numeric(value, prior):
    try:
        return float(value)
    except (ValueError, TypeError):
        return prior


def apply_pose(layer, attrs):
    for j, value in enumerate(attrs.get('pos', '').split(',')[:3]):
        key = ('x', 'y', 'z')[j]
        layer[key] = numeric(value, layer[key])
    layer['scale'] = numeric(attrs.get('scale'), layer['scale'])
    if 'rotation' in attrs:
        layer['rotation'] = numeric(attrs['rotation'].split(',')[-1], layer['rotation'])
    tint = attrs.get('tint', '')
    if re.fullmatch(r'#[0-9a-fA-F]{8}', tint):
        layer['opacity'] = int(tint[-2:],16)
        layer['visible'] = layer['opacity'] > 0


def forget_appearance(state, actor):
    # A Naninovel @back replaces its texture independently of its transform.
    # Keep the registered actor even if the intervening appearance is outside the CG catalog.
    if actor in state:
        state[actor].update(pair=None, names=None, visible=False)


def common_actors(states):
    shared = {}
    for actor, first in states[0].items():
        rows = [state.get(actor) for state in states]
        if any(row is None for row in rows):
            continue
        if all(row == first for row in rows):
            shared[actor] = first.copy()
        elif all(all(row[k] == first[k] for k in ('x','y','z','scale','rotation')) for row in rows):
            # The actor's expression may differ across choices while its transform is shared.
            # Keep that transform but draw nothing until an appearance is explicitly assigned.
            shared[actor] = {**first, 'pair':None, 'names':None, 'visible':False}
    return shared


def annotated_rows(rows, loc):
    for row in rows:
        idx, kind, h, t, offset = row
        ref = loc.get(idx)
        if ref and 'inline' in ref:
            pre, appearance, post = ref['inline']
            if pre['length']: yield (*row, pre)
            yield (idx, 'Command', h, '@' + appearance, offset, None)
            if post['length']: yield (*row, post)
        else:
            yield (*row, ref)


def merge_target(carry, target, state):
    previous = carry.get(target)
    if previous is None:
        carry[target] = clone(state)
    else:
        carry[target] = common_actors((previous,state))


class Builder:

    def __init__(self, library):
        self.lib = library
        self.scenes = []
        self.missing = set()
        self.effects = set()

    def make_scene(self, source, label, idx, group=None, chapter=None, caption=None):
        g, ch = route(source, label)
        scene = {
            'id': f'{source}-{idx}',
            'group': group or g,
            'chapter': ch if chapter is None else chapter,
            'source': source,
            'label': label,
            'line': idx,
            'reveal': caption or '',
            'frames': []
        }
        self.scenes.append(scene)
        return scene

    def frame(self, scene, state, idx, branch=''):
        snap = snapshot(state)
        if not snap: return None
        layers = [v['pair'][0] for _, v in snap]
        layers2 = [v['pair'][1] for _, v in snap]
        prev = scene['frames'][-1] if scene['frames'] else None
        layout = [{
            'x': v['x'],
            'y': v['y'],
            'scale': v['scale'],
            'rotation': v['rotation'],
            'z': v['z'],
            **({'opacity': v['opacity']} if 0 < v.get('opacity',255) < 255 else {})
        } for _, v in snap]
        if prev and layers == prev['layers'] and layers2 == prev.get(
                'layers2', prev['layers']) and branch == prev.get('branch', ''):
            # Replace a transition's initial pose with its final pose, before dialogue begins.
            if not prev['lines']:
                prev['layout'] = layout
            elif layout != prev['layout'] and layout not in prev.get('poseAlternatives', []):
                # Same illustration can move into frame after several lines of dialogue.
                # Store authored alternatives without inventing a separate story/choice.
                prev.setdefault('poseAlternatives', []).append(layout)
            return prev
        bindings = []
        bindings2 = []
        for key, v in snap:
            for variant, target in enumerate((bindings, bindings2)):
                aid = v['pair'][variant]
                options = self.lib.names[aid]
                actor, appearance = next((binding for binding in options if binding[0] == key), options[0])
                if v.get('names'):
                    actor, appearance = key, v['names'][variant]
                if self.lib.lookup[(actor + '/' + appearance).lower()] != aid:
                    raise ValueError(f'Wrong address binding {actor}/{appearance}')
                target.append({'actor': actor, 'appearance': appearance})
        item = {'layers': layers, 'bindings': bindings, 'layout': layout, 'line': idx, 'lines': []}
        if bindings2 != bindings: item['bindings2'] = bindings2
        if layers2 != layers: item['layers2'] = layers2
        if branch: item['branch'] = branch
        scene['frames'].append(item)
        return item

    @staticmethod
    def layer(pair, depth=0):
        return {'pair': pair, 'x': 50, 'y': 50, 'scale': 1, 'z': depth, 'rotation': 0, 'visible': True}

    def script(self, name, rows, loc):
        state = {}
        scene = None
        label = ''
        condition_stack = []
        carry = {}
        stopped = False
        branch = ''
        choice_labels = {}
        live_choices = []
        live_choice_actor = ''
        dynamic_choices = []
        for idx, kind, _, raw, _, ref in annotated_rows(rows, loc):
            if kind == 'Label':
                label = raw.strip().lstrip('#').strip()
                if label in carry:
                    state = clone(carry[label])
                elif stopped:
                    state = {}
                stopped = False
                scene = None
                branch = ''
                live_choices = []
                continue
            row = CMD.match(raw) if kind == 'Command' else None
            command = row[1].lower() if row else ''
            body = row[2] if row else ''
            attrs = args_of(body) if row else {}
            token = first_arg(body) if row else ''
            if command == 'if':
                condition_stack.append((clone(state), []))
            elif command in ('else', 'elseif') and condition_stack:
                before, ends = condition_stack[-1]
                ends.append(clone(state))
                state = clone(before)
                scene = None
            elif command == 'endif' and condition_stack:
                before, ends = condition_stack.pop()
                # A merge that disagrees on a layer cannot supply a single known later picture.
                if ends:
                    all_states = ends + [state]
                    state = common_actors(all_states)
                elif before != state:
                    state = common_actors((before,state))
            if command in ('choice', 'choicer') and attrs.get('goto', '').startswith('.'):
                dest = attrs['goto'][1:]
                merge_target(carry, dest, state)
                if ref: choice_labels[dest] = ref
            if command == 'goto' and token.startswith('.'):
                merge_target(carry, token[1:], state)
            if command in ('goto', 'return', 'stop', 'title') and 'if' not in attrs:
                stopped = True
                state = {}
                scene = None
                continue
            if command in ('hideall', 'resetstate'):
                state = {}
            if command == 'set' and (m := re.match(r'tempPriestHighLoopChoiceCg="(\w+)"', body)):
                dynamic_choices.append((m[1], label, choice_labels.get(label)))
            if command == 'actorspriteeffect':
                effect = attrs.get('texture', '').removeprefix(ROOT)
                for i in (1, 2):
                    effect_id = self.lib.lookup.get(effect.replace('{playerType}', str(i)).lower())
                    if effect_id is not None: self.effects.add(effect_id)
            if command in ('hide', 'show'):
                for target in token.split(','):
                    if target == live_choice_actor and command == 'hide':
                        live_choices = []
                    if target in state: state[target]['visible'] = command == 'show'
            if command == 'back':
                actor = attrs.get('id', MAIN)
                if actor != MAIN and not actor.startswith('OptionalCGBackground'): continue
                name_token = token if ':' not in token else ''
                if name_token and actor == live_choice_actor:
                    live_choices = []
                pair = self.lib.pair(actor, name_token) if name_token else None
                names = tuple(
                    name_token.replace('{playerType}', str(i)).replace('{otherPlayerType}', str(3 - i))
                    for i in (1, 2))
                if name_token == 'CG/{partnerCharacter}TrialEnd':
                    for g in GROUPS:
                        trial_name = 'CG/' + g.lower() + 'TrialEnd'
                        p = self.lib.pair(MAIN, trial_name)
                        s = self.make_scene(name, label, idx, g, 2, '试玩篇纪念画')
                        s['id'] += '-' + g
                        self.frame(s, {MAIN: self.layer(p)}, idx)
                    continue
                if name_token == '{tempHeroDropoutImage}':
                    names = ('CG/heroDropout04', 'CG/heroDropout03')
                    pairs = [self.lib.pair(MAIN, 'CG/heroDropout' + n) for n in ('04', '03')]
                    pair = (pairs[0][0], pairs[1][0])
                if '{tempPriestHighLoopChoiceCg}' in name_token and dynamic_choices:
                    # Each original choice jumps to a literal-valued assignment, then to this display.
                    for choice, choice_label, choice_ref in dynamic_choices:
                        p = self.lib.pair(actor, name_token.replace('{tempPriestHighLoopChoiceCg}', choice))
                        if p and raw.lower().find('#ffffff00') < 0:
                            s = self.make_scene(name, label, idx, caption='最后的选择')
                            s['id'] += '-' + choice
                            branch_state = clone(state)
                            branch_state[actor] = self.layer(p, -16.4)
                            apply_pose(branch_state[actor], attrs)
                            f = self.frame(s, branch_state, idx, choice)
                            if choice_ref:
                                f['lines'].append(choice_ref)
                                s['choice'] = choice_ref
                                s['choiceLabel'] = choice_label
                            live_choices.append(f)
                            live_choice_actor = actor
                    scene = None
                    state.pop(actor, None)
                    continue
                if name_token and not pair:
                    if name_token.lower().startswith('cg/') or (actor.startswith('OptionalCG')
                                                                and '{' not in name_token):
                        self.missing.add((name, idx, actor, name_token))
                    forget_appearance(state, actor)
                if pair or actor in state:
                    layer = state.setdefault(actor, self.layer(pair, -16.0 if actor == MAIN else -16.1))
                    if pair:
                        layer['pair'] = pair
                        layer['names'] = names
                        layer['visible'] = True
                    apply_pose(layer, attrs)
            # Record pictures without dialogue also, but do not manufacture a visual at a label.
            visible = snapshot(state)
            if ref and live_choices:
                for f in live_choices:
                    f['lines'].append(ref)
                continue
            if not visible: continue
            if command not in ('back', 'hide', 'show') and not ref: continue
            if not scene:
                scene = self.make_scene(name, label, idx)
                if label in choice_labels:
                    scene['choice'] = choice_labels[label]
                stopped = False
            frame = self.frame(scene, state, idx, branch)
            if ref: frame['lines'].append(ref)
            if not scene['reveal']:
                scene['reveal'] = reveal_name(label,
                                              Path(self.lib.assets[visible[-1][1]['pair'][0]]['path']).stem)

    def dungeon(self, rows, loc):
        scene = None
        frame = None
        current_num = None
        for idx, kind, _, text, _ in rows:
            if kind == 'Label':
                label = text.lstrip().removeprefix('#').strip()
                event = re.fullmatch(r'event(\d+)(?:_(\w+))?', label, re.I)
                if not event or not 1 <= int(event[1]) <= 30 or int(event[1]) == 26:
                    current_num = scene = frame = None
                    continue
                n = int(event[1])
                if n != current_num:
                    p = self.lib.pair('OptionalCGBackground',
                                      f'DungeonEvent/{n}Me{{playerType}}') or self.lib.pair(
                                          'OptionalCGBackground', f'DungeonEvent/{n}')
                    if not p: raise ValueError(f'Missing dungeon image {n}')
                    scene = self.make_scene('Dungeon', label, idx, caption=f'迷宫事件 {n:02d}')
                    current_num = n
                frame = self.frame(scene, {'OptionalCGBackground': self.layer(p)}, idx, event[2] or '')
            elif frame and idx in loc:
                frame['lines'].append(loc[idx])

    def endings(self, rows):
        scene = None
        for idx, kind, _, text, _ in rows:
            if kind != 'Command': continue
            key = re.match(r'\s*@set endingImageSetKey="([^"]+)"', text)
            if key:
                branch = key[1]
                group = next((g for g in GROUPS if g.lower() in branch.lower()), 'Shared')
                scene = self.make_scene('Ending', branch, idx, group, 6, '结局回顾')
            if not scene: continue
            img = re.match(r'\s*@set endingImage([1-5])="(CG/[^"]+)"', text)
            if img:
                p = self.lib.pair(MAIN, img[2])
                if not p: raise ValueError(img[2])
                self.frame(scene, {MAIN: self.layer(p)}, idx, img[1] if ' if:' in text else '')
            if (m := re.match(r'\s*@set titleEndingBackground="(CG/[^"]+)"', text)):
                p = self.lib.pair(MAIN, m[1])
                if not p: raise ValueError(m[1])
                group = next((g for g in GROUPS if g.lower() in m[1].lower()), 'Shared')
                s = self.make_scene('Title', m[1], idx, group, 6, '结局标题画')
                self.frame(s, {MAIN: self.layer(p)}, idx)

    def supplements(self):
        used = {i for s in self.scenes for f in s['frames'] for i in f['layers'] + f.get('layers2', [])}
        pending = {a['id'] for a in self.lib.assets} - used
        byname = {Path(a['path']).stem.lower(): a for a in self.lib.assets}
        while pending:
            aid = min(pending)
            pending.remove(aid)
            a = self.lib.assets[aid]
            stem = Path(a['path']).stem
            pair = (aid, aid)
            if (m := re.search(r'(?i)(me)([12])', stem)):
                alt = stem[:m.start(2)] + str(3 - int(m[2])) + stem[m.end(2):]
                other = byname.get(alt.lower())
                if other and other['id'] in pending:
                    pending.remove(other['id'])
                    pair = (aid, other['id']) if m[2] == '1' else (other['id'], aid)
            bundle = a['bundle'].split('_')[0]
            group = next((g for g in GROUPS if bundle.startswith('partner' + g.lower())), None)
            group = group or next((g for g in GROUPS if g.lower() in stem.lower()), 'Shared')
            is_mask = aid in self.effects or any(tag in stem.lower() for tag in EFFECT_TYPES)
            is_illustration = '/CG/' in a['path'] or 'OptionalCGBackground' in a['path']
            if is_mask or not is_illustration or a['kind'] == 'technical':
                for texture_id in pair:
                    self.lib.assets[texture_id]['kind'] = 'technical'
                continue
            s = self.make_scene('Extras', stem, aid, group, 7, '资源画稿')
            s['type'] = 'asset'
            self.frame(s, {MAIN: self.layer(pair)}, aid)

    def finish(self):
        # Flash-color backgrounds have no intrinsic art. Without the game's animated material
        # they obscure otherwise correct artwork, so retain them only in the resource index.
        for scene in self.scenes:
            keep = []
            for frame in scene['frames']:
                visible = [
                    i for i, aid in enumerate(frame['layers']) if self.lib.assets[aid]['kind'] != 'technical'
                ]
                if not any(self.lib.assets[frame['layers'][i]]['kind'] == 'art' for i in visible): continue
                for key in ('layers', 'layers2', 'bindings', 'bindings2', 'layout'):
                    if key in frame: frame[key] = [frame[key][i] for i in visible]
                if 'poseAlternatives' in frame:
                    frame['poseAlternatives'] = [[poses[i] for i in visible] for poses in frame['poseAlternatives']]
                keep.append(frame)
            scene['frames'] = keep
        self.scenes = [s for s in self.scenes if s['frames']]
        # Some shared battle subroutines are called from several floors. Use the dedicated
        # illustration's owning route bundle when present and avoid assigning a guessed floor.
        for scene in self.scenes:
            if scene['source'] != 'Battle': continue
            assets = [self.lib.assets[i] for f in scene['frames'] for i in f['layers']]
            bundles = {
                m.groups()
                for a in assets if (m := re.match(r'partner(hero|mage|priest|warrior)([1-5])_', a['bundle']))
            }
            if len(bundles) == 1:
                group, chapter = bundles.pop()
                scene['group'], scene['chapter'] = group.title(), int(chapter)
            elif scene['group'] == 'Shared':
                scene['chapter'] = 5 if 'final' in scene['label'].lower() else 0
        self.supplements()
        return self.scenes


def catalog_identity(marker, binary):
    # The external .hash is optional for local Addressables players. Offsets and aliases
    # always come from the supplied original catalog, regardless of this descriptive marker.
    if marker.is_file():
        value = marker.read_text(encoding='utf-8-sig').strip()
        if value: return value
    return 'sha256:' + hashlib.sha256(binary).hexdigest()


def build(game, stage):
    data = game / 'Annihilated_Data'
    aa = data / 'StreamingAssets' / 'aa'
    stock = stage / 'catalog-stock.bin'
    binary = (stock if stock.is_file() else aa / 'catalog.bin').read_bytes()
    addr = address_paths(binary)
    places = address_paths(binary, BG_PREFIXES)
    metrics = json_read(stage / 'sprite-metrics.json')
    lib = Library(json_read(stage / 'images.json'), addr, metrics['localized'])
    builder = Builder(lib)
    scripts = json_read(stage / 'scripts.json')
    chinese = json_read(stage / 'zh.json')
    menus = {}
    source_refs = {}
    for name, rows in scripts.items():
        loc = translations(rows, chinese.get(name.lower(), []))
        menus[name] = collect_menus(rows, loc)
        source_refs[name] = loc
        if name == 'Dungeon': builder.dungeon(rows, loc)
        elif name == 'Ending': builder.endings(rows)
        elif name.startswith(('Opening', 'Scenario')) or name in ('GameOver', 'Battle', 'TrialEnd'):
            builder.script(name, rows, loc)
    scenes = builder.finish()
    title_backgrounds, unregistered = add_scenery(scenes, lib.assets, scripts, source_refs, places, metrics)
    apply_story_order(scenes, scripts, menus)
    add_companion_links(scenes, lib.assets)
    add_branch_links(scenes, menus)
    with (data / 'resources.assets').open('rb') as file:
        resource_hash = hashlib.file_digest(file, 'sha256').hexdigest()
    return {
        'version': 1,
        'catalogHash': catalog_identity(aa / 'catalog.hash', binary),
        'resourcesSize': (data / 'resources.assets').stat().st_size,
        'resourcesSha256': resource_hash,
        'assets': lib.assets,
        'titleBackgrounds': title_backgrounds,
        'scenes': scenes
    }, builder.missing


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('game', type=Path)
    ap.add_argument('stage', type=Path)
    ap.add_argument('output', type=Path)
    opt = ap.parse_args()
    catalog, missing = build(opt.game, opt.stage)
    opt.output.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
    print(
        f"{len(catalog['assets'])} distinct textures, {len(catalog['scenes'])} records. Unresolved literal appearances: {sorted(missing)}"
    )
