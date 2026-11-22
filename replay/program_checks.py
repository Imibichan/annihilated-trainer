"""Check native command donors and static destinations before installing a replay tape."""
from collections import Counter, defaultdict
import re

from stock_controls import TEMPLATES


class ProgramChecks:
    def __init__(self, scripts):
        self.scripts = scripts
        self.labels = {}
        commands = defaultdict(set)
        for name, rows in scripts.items():
            self.labels[name] = Counter(r[3].strip().lstrip('#').strip() for r in rows if r[1] == 'Label')
            for _, kind, _, raw, *_ in rows:
                if kind == 'Command':
                    line = raw.strip()
                    commands[line.partition(' ')[0]].add(line)
        self.templates = {name for name, (_, pattern) in TEMPLATES.items()
                          if any(re.fullmatch(pattern, line) for line in commands['@'+name])}

    def validate(self, edits):
        labels = {name: existing.copy() for name, existing in self.labels.items()}
        links = []
        for name, changes in edits.items():
            if name not in self.scripts:
                raise ValueError('缺少原作脚本 ' + name)
            original = self.scripts[name]
            count = len(original)
            for idx, spec in sorted(changes.items()):
                if idx < 0 or idx > count:
                    raise ValueError(f'回放指令位置不连续 {name}:{idx}')
                if idx == count:
                    count += 1
                elif idx < len(original) and original[idx][1] == 'Label':
                    labels[name][original[idx][3].strip().lstrip('#').strip()] -= 1
                if isinstance(spec, str):
                    line = spec.strip()
                    if line.startswith('#'):
                        labels[name][line[1:].strip()] += 1
                        continue
                    if line == ';':
                        continue
                    if line.partition(' ')[0].lstrip('@') not in self.templates:
                        raise ValueError(f'当前游戏缺少原生指令模板 {line}')
                else:
                    donor, location = spec
                    rows = self.scripts.get(donor, ())
                    if not 0 <= location < len(rows) or rows[location][1] != 'Command':
                        raise ValueError(f'原生指令来源无效 {donor}:{location}')
                    line = rows[location][3].strip()
                match = re.match(r'@(?:goto|gosub)\s+"?([\w.{}-]+)', line, re.I)
                if not match and re.match(r'@choiceR?\b', line, re.I):
                    match = re.search(r'\bgoto:\s*"?([\w.{}-]+)', line)
                if match:
                    target = match[1]
                    if target.startswith('.') and not isinstance(spec, str) and spec[0] != name:
                        raise ValueError(f'原作局部跳转离开了所属脚本 {name}:{idx} {target}')
                    if '{' not in target:
                        links.append((name, idx, target))
        for name, idx, target in links:
            dest, _, label = target.partition('.')
            dest = dest or name
            if dest not in labels or label and labels[dest][label] != 1:
                raise ValueError(f'回放跳转目标缺失或重名 {name}:{idx} → {dest}.{label}')
