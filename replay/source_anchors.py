"""Resolve gallery observations against the mounted game's native labels and commands."""
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re


def appearance(row):
    if row[1] != 'Command':
        return ''
    match = re.match(r'@back\s+(?:"([^"]*)"|([^\s"]+))', row[3].strip(), re.I)
    return (match[1] or match[2] or '') if match else ''


def illustration(row):
    art = appearance(row)
    if art.startswith('CG/') or art and re.search(r'\bid:"?OptionalCGBackground\d*"?\b', row[3]):
        return art
    return ''


@lru_cache(maxsize=1)
def _original_appearances():
    return json.loads(Path(__file__).with_name('original_appearances.json').read_bytes())


class SourceBlocks:
    def __init__(self, rows):
        self.blocks = defaultdict(list)
        scope = ''
        for row in rows:
            if row[1] == 'Label':
                scope = row[3].strip().lstrip('#').strip()
            if row[1] not in ('Empty', 'Comment'):
                self.blocks[scope].append(row)

    def resolve(self, anchor):
        scope, identity = anchor[:2]
        rows = self.blocks.get(scope, ())
        previous = anchor[2] if len(anchor) > 2 else ''
        resource = anchor[3] if len(anchor) > 3 else ''
        matches = [r for i, r in enumerate(rows) if r[2] == identity and
                   (not previous or i and rows[i-1][2] == previous)]
        if not matches and resource:
            # The author added a protagonist suffix to an existing illustration.
            # Other edits to presentation (scale, time) also leave this address usable.
            matches = [r for i, r in enumerate(rows)
                       if appearance(r).removesuffix('Me{playerType}') == resource.removesuffix('Me{playerType}')
                       and (not previous or i and rows[i-1][2] == previous)]
        if len(matches) == 1:
            return matches[0][0]
        return None


@lru_cache(maxsize=1)
def _anchors():
    return json.loads(Path(__file__).with_name('source_anchors.json').read_bytes())


def resolve_gallery(scripts, gallery):
    """Keep legacy IDs stable and return only live semantic locations for tracing."""
    anchors = _anchors()
    sources = {}
    def blocks(name):
        if name not in sources:
            sources[name] = SourceBlocks(scripts.get(name, ()))
        return sources[name]

    resolved, missing = [], {}
    for original in gallery['scenes']:
        key, source = original['id'], original['source']
        if source in ('Extras', 'Title'):
            # Independent assets and ending-title lookups have no story row.
            resolved.append(original)
            continue
        anchor = anchors.get(key)
        line = blocks(source).resolve(anchor) if anchor else None
        if line is None:
            missing[key] = '无法在当前脚本内唯一定位画面 ' + source + '.' + original['label']
            continue
        row = dict(original, line=line)
        if 'storyOrigins' in original and source == 'Ending':
            row['storyOrigins'] = []
            for i, origin in enumerate(original['storyOrigins']):
                ref = anchors.get(f'{key}/{i}')
                current = blocks(origin['source']).resolve(ref) if ref else None
                if current is not None:
                    row['storyOrigins'].append(dict(origin, line=current))
                else:
                    missing[f'{key}/{i}'] = '无法定位结局的原作入口 ' + origin['source']
        resolved.append(row)
    if any(s['source'].startswith('Scenario_') for s in gallery['scenes']):
        # Observe new native illustrations in every role callback, including named
        # optional CG layers. A revised existing cue keeps its legacy gallery ID.
        previous = _original_appearances()
        mapped = {(s['source'], s['line']) for s in resolved}
        for source in scripts:
            if not source.startswith('Scenario_'):
                continue
            for scope, rows in blocks(source).blocks.items():
                known = previous.get(source + '.' + scope, ())
                additions = defaultdict(list)
                for row in rows:
                    art = illustration(row)
                    if art and art not in known and (source, row[0]) not in mapped:
                        additions[art].append(row[0])
                for art, lines in additions.items():
                    key = source + '.' + scope + '/' + art
                    resolved.append(dict(id=key, source=source, label=scope, line=lines[0], nativeLines=lines))
    return resolved, missing

def missing_cues(scripts, gallery, addresses):
    """Check concrete native artwork addresses for both playable protagonists."""
    rows, _ = resolve_gallery(scripts, gallery)
    unavailable = {}
    for row in rows:
        required = set()
        if row['source'] == 'Extras':
            for frame in row.get('frames', ()):
                for key in ('bindings', 'bindings2'):
                    for binding in frame.get(key, ()):
                        required.add(f"Naninovel/Backgrounds/{binding['actor']}/{binding['appearance']}")
        elif row['source'] != 'Title':
            command = scripts[row['source']][row['line']]
            art = illustration(command)
            if art:
                match = re.search(r'\bid:(?:"([^"]+)"|([^\s]+))', command[3])
                actor = (match[1] or match[2]) if match else 'MainBackground'
                for lead in (1, 2):
                    resource = art.replace('{playerType}', str(lead)).replace('{otherPlayerType}', str(3-lead))
                    # Arbitrary Naninovel expressions are evaluated by the native game.
                    if '{' not in resource and '{' not in actor:
                        required.add(f'Naninovel/Backgrounds/{actor}/{resource}')
        absent = sorted(a for a in required if a not in addresses)
        if absent:
            unavailable[row['id']] = '当前游戏缺少画面地址 ' + '、'.join(absent)
    return unavailable
