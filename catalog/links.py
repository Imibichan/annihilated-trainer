"""Gallery links between verified images and source-script choices."""
from collections import defaultdict
from pathlib import Path
import re

# Curated from the illustrations and the dialogue accompanying the shot. The two player designs
# are the soldier; a shot of the soldier together with one companion is not a joint memory.
CAST = {
    'endingtitlemagesecretme': ('Hero', 'Mage', 'Warrior', 'Priest'),
    'hero5soupriesthutaridekirume': ('Hero', 'Priest'),
    'hero5soupriesthutaridekiruswordosamerume': ('Hero', 'Priest'),
    'killheroandmage': ('Hero', 'Mage'),
    'mage5soupriesttoujou': ('Hero', 'Warrior', 'Priest'),
    'mage5sousitaitazusaetewaraupriestme': ('Hero', 'Warrior', 'Priest'),
    'mage5soupriesttoujouwithhero': ('Hero', 'Priest'),
    'mage5souyuujou7ninseizoroime': ('Hero', 'Mage', 'Warrior'),
    'mageeploguenotmaryokupartywithnewmember': ('Hero', 'Warrior'),
    'outcastpast3_mage': ('Hero', 'Mage'),
    'partyscene': ('Hero', 'Mage', 'Warrior', 'Priest'),
    'priest5soumaouclearme': ('Hero', 'Mage', 'Warrior', 'Priest'),
    'priestkaisou02': ('Hero', 'Mage'),
    'priestkaisou02-2': ('Hero', 'Mage'),
    'trump': ('Hero', 'Mage', 'Warrior', 'Priest'),
    'villainesswarrior18': ('Hero', 'Priest'),
    'villainesswarrior31': ('Hero', 'Warrior', 'Priest'),
    'warrior5idolepilogue': ('Mage', 'Warrior'),
    'warrior5idolepiloguehakoniwa': ('Mage', 'Warrior'),
    'warrior5souillusionbstartkutinonakanibakudan': ('Hero', 'Warrior'),
    'cuthero': ('Hero', ),
    'cutmage': ('Mage', ),
    'cutwarrior': ('Warrior', ),
    'cutpriest': ('Priest', ),
}


def add_companion_links(scenes, assets):
    cast = {}
    for a in assets:
        stem = Path(a['path']).stem.lower()
        cast[a['id']] = CAST.get(re.sub(r'me[12]$', 'me', stem), ())
    for s in scenes:
        links = {}
        for index, frame in enumerate(s['frames']):
            roles = {role for aid in frame['layers'] for role in cast[aid]}
            if len(roles) < 2: continue
            for role in ('Hero', 'Mage', 'Warrior', 'Priest'):
                if role in roles and role != s['group']:
                    links.setdefault(role, index)
        if links:
            s['alsoGroups'] = list(links)
            s['alsoFrames'] = links


def choice_key(ref):
    return ref['offset'], ref['length']


def collect_menus(rows, refs):
    """Only group adjacent, translated @choice commands with a literal local jump."""
    menus = []
    current = []
    for idx, kind, _, text, _ in rows:
        if kind in ('Empty', 'Comment'): continue
        cmd = re.match(r'^\s*@choice(?:R)?\s', text, re.I) if kind == 'Command' else None
        target = re.search(r'(?:^|\s)goto:"?\.([A-Za-z0-9_]+)\b', text, re.I) if cmd else None
        ref = refs.get(idx)
        if target and ref and ref.get('kind') == 'choice':
            current.append((target[1], ref))
            continue
        if current:
            menus.append(current)
            current = []
    if current: menus.append(current)
    return menus


def add_branch_links(scenes, source_menus):
    """Link a displayed decision and its illustrated outcomes without interpreting any scenario."""
    by_source = defaultdict(list)
    for s in scenes:
        by_source[s['source']].append(s)
    for source, menus in source_menus.items():
        group = by_source[source]
        targets = defaultdict(list)
        origins = defaultdict(list)
        for s in group:
            if 'choice' in s:
                targets[choice_key(s['choice'])].append(s)
            for f in s['frames']:
                for ref in f['lines']:
                    if ref['kind'] == 'choice':
                        origins[choice_key(ref)].append((s, f))
        for menu in menus:
            verified = []
            for label, ref in menu:
                matches = [
                    s for s in targets[choice_key(ref)]
                    if s['label'] == label or s.get('choiceLabel') == label
                ]
                if matches:
                    first = min(matches, key=lambda s: s['line'])
                    verified.append({'sceneId': first['id'], 'choice': ref})
            if not verified: continue
            for _, ref in menu:
                key = choice_key(ref)
                for scene in targets[key]:
                    append_unique(scene, [b for b in verified if b['sceneId'] != scene['id']])
                for scene, frame in origins[key]:
                    outgoing = [b for b in verified if b['sceneId'] != scene['id']]
                    append_unique(scene, outgoing)
                    append_unique(frame, outgoing)


def append_unique(obj, links):
    if not links: return
    existing = obj.setdefault('branches', [])
    present = {item['sceneId'] for item in existing}
    existing.extend(item for item in links if item['sceneId'] not in present)
