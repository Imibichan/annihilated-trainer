"""Edit compiled Naninovel replay controls in a separate Unity game tree.

patch_scripts takes {script_name: {zero_based_index: replacement}}. Replacements
are simple control lines or (stock_script, stock_line_index) command donors.
Existing line IDs and hashes stay fixed. Additional rows must start at EOF and
be contiguous. The mounted stock scripts, localizations and game stay read-only.
"""
from copy import deepcopy
import gc
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import zlib

from addressables import bundle_locations
import catalog_crc
if __package__:
    from .script_reader import read_lines
    from .stock_controls import TEMPLATES
else:
    from script_reader import read_lines
    from stock_controls import TEMPLATES
import UnityPy
from UnityPy.helpers.TypeTreeHelper import read_typetree, write_typetree
from UnityPy.streams import EndianBinaryReader, EndianBinaryWriter


AA = Path("Annihilated_Data/StreamingAssets/aa")
PLATFORM = "StandaloneWindows64"
LINE_NS = "Naninovel"
RUNTIME = "Elringus.Naninovel.Runtime"
U32 = struct.Struct("<I")
I64 = struct.Struct("<q")


def _bundle(game):
    catalog = Path(game) / AA / "catalog.bin"
    names = [n for n in bundle_locations(catalog.read_bytes())
             if re.fullmatch(r"naninovel_assets_naninovel(?:_[A-Za-z0-9-]+)?\.bundle", n, re.I)]
    if len(names) != 1:
        raise ValueError("Expected one registered Naninovel script bundle")
    return catalog.parent / PLATFORM / names[0]


class ScriptDirectory(dict):
    def __init__(self):
        super().__init__()
        self.unavailable = {}


def _scripts(env):
    result = ScriptDirectory()
    for asset in env.assets:
        for name, ptr in asset.container.items():
            if name.startswith("Assets/Novel/") and name.endswith(".nani"):
                key = Path(name).stem
                if key in result.unavailable:
                    continue
                if key in result or ptr.m_FileID or ptr.m_PathID not in asset.objects:
                    result.pop(key, None)
                    result.unavailable[key] = f"当前原作脚本 {key} 存在重名或未解析的外部引用"
                    continue
                result[key] = asset.objects[ptr.m_PathID]
    if not result:
        raise ValueError("No compiled Naninovel scripts in the registered bundle")
    return result


def read_script_rows(game):
    """Inspect only the registered script bundle; same row shape as v1.4 inspect_game."""
    with _bundle(game).open("rb") as stream:
        env = UnityPy.load(stream)
        scripts = _scripts(env)
        rows = ScriptDirectory()
        rows.unavailable.update(scripts.unavailable)
        for name, obj in scripts.items():
            try:
                rows[name] = read_lines(obj)
            except (ValueError, struct.error) as error:
                rows.unavailable[name] = f"当前脚本 {name} 的行表无法解析：{error}"
        return rows


def _string(text):
    data = text.encode("utf-8")
    return U32.pack(len(data)) + data + bytes((-len(data)) % 4)


def _read_string(raw, pos):
    size = U32.unpack_from(raw, pos)[0]
    start = pos + 4
    end = start + size
    if end > len(raw):
        raise ValueError("Invalid compiled script string")
    return bytes(raw[start:end]).decode("utf-8"), (end + 3) & ~3


class _Script:
    """Index managed records and deserialize only commands being transplanted."""

    def __init__(self, obj, types):
        raw = obj.get_raw_data()
        self.obj = obj
        self.name, pos = _read_string(raw, 28)
        self.prefix = raw[:pos]
        count, = U32.unpack_from(raw, pos)
        self.lines = list(struct.unpack_from(f"<{count}q", raw, pos + 4))
        pos += 4 + count * 8
        version, total = struct.unpack_from("<II", raw, pos)
        if version != 2:
            raise ValueError(f"Unknown managed reference registry version {version}")
        pos += 8
        # A null managed reference (rid -2) has three empty type names and no data.
        self.null = raw[pos:pos+20] if raw[pos:pos+20] == I64.pack(-2) + bytes(12) else b""
        pos += len(self.null)
        matches = list(types.regex.finditer(raw, pos))
        if len(matches) + bool(self.null) != total or not matches or matches[0].start() - 8 != pos:
            raise ValueError(f"Invalid managed reference table in {self.name}")
        self.records = {}
        buff = memoryview(raw)
        for i, match in enumerate(matches):
            start = match.start() - 8
            finish = matches[i + 1].start() - 8 if i + 1 < len(matches) else len(raw)
            rid = I64.unpack_from(raw, start)[0]
            if rid < 0 or rid in self.records:
                raise ValueError(f"Duplicate or negative managed reference {rid} in {self.name}")
            self.records[rid] = (types.by_header[match[0]], buff[match.end():finish])
        self.next_id = max(self.records) + 1
        self.types = types

    def alloc(self):
        rid = self.next_id
        self.next_id += 1
        return rid

    def line(self, index):
        if not 0 <= index < len(self.lines):
            raise ValueError(f"No line {self.name}:{index}")
        kind, raw = self.records[self.lines[index]]
        actual, = U32.unpack_from(raw)
        if actual != index or kind[1] != LINE_NS:
            raise ValueError(f"Invalid line reference at {self.name}:{index}")
        h, pos = _read_string(raw, 4)
        text, pos = _read_string(raw, pos)
        return kind[0], h, text, raw[pos:]

    def command(self, index):
        kind, _, text, tail = self.line(index)
        if kind != "CommandScriptLine" or len(tail) != 8:
            raise ValueError(f"Stock donor must be a compiled command: {self.name}:{index}")
        command_kind, raw = self.records[I64.unpack(tail)[0]]
        reader = EndianBinaryReader(raw, endian="<")
        data = read_typetree(self.types.nodes[command_kind], reader, byte_size=len(raw))
        return command_kind, data, text.strip()

    def install(self, index, spec, library):
        if index < len(self.lines):
            _, h, old_text, _ = self.line(index)
            line_id = self.lines[index]
            indent = old_text[:len(old_text) - len(old_text.lstrip())]
        elif index == len(self.lines):
            h = hashlib.blake2s(f"{self.name}\n{index}\n{spec}".encode(), digest_size=4).hexdigest()
            indent = ""
            line_id = self.alloc()
            self.lines.append(line_id)
        else:
            raise ValueError(f"Appended rows must be contiguous at {self.name}:{index}")
        if isinstance(spec, str) and (spec.lstrip().startswith("#") or spec.strip() == ";"):
            text = spec.strip()
            if text.startswith("#"):
                label = text[1:].strip()
                if not re.fullmatch(r"[\w-]+", label):
                    raise ValueError(f"Invalid replay label {text!r}")
                kind, tail = "LabelScriptLine", _string(label)
            else:
                kind, tail = "CommentScriptLine", _string("")
        else:
            if isinstance(spec, (tuple, list)) and len(spec) == 2:
                source, donor_row = spec
                ctype, data, text = library.script(source).command(donor_row)
            elif isinstance(spec, str):
                text = spec.strip()
                ctype, data = library.control(text)
            else:
                raise ValueError(f"Unsupported replay edit at {self.name}:{index}: {spec!r}")
            _move_spots(data, self.name, index)
            writer = EndianBinaryWriter(endian="<")
            write_typetree(data, self.types.nodes[ctype], writer)
            command_id = self.alloc()
            self.records[command_id] = ctype, writer.bytes
            kind, tail = "CommandScriptLine", I64.pack(command_id)
        self.records[line_id] = ((kind, LINE_NS, RUNTIME),
                                 U32.pack(index) + _string(h) + _string(indent + text) + tail)

    def finish(self):
        count = len(self.records) + bool(self.null)
        chunks = [self.prefix, U32.pack(len(self.lines)), struct.pack(f"<{len(self.lines)}q", *self.lines),
                  struct.pack("<II", 2, count), self.null]
        for rid, (kind, data) in self.records.items():
            chunks.extend((I64.pack(rid), self.types.headers[kind], data))
        packed = b"".join(chunks)
        self.obj.set_raw_data(packed)
        return hashlib.sha256(packed).digest()


def _move_spots(data, name, index):
    """Keep inactive parameter playback spots blank; relocate command and dynamic spots."""
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if key == "playbackSpot" or (key == "PlaybackSpot" and value.get("scriptName")):
            value.update(scriptName=name, lineIndex=index, inlineIndex=0)
        else:
            _move_spots(value, name, index)


class _Types:
    def __init__(self, refs):
        self.nodes = {(r.m_ClassName, r.m_NameSpace, r.m_AssemblyName): r.node for r in refs}
        self.headers = {key: b"".join(map(_string, key)) for key in self.nodes}
        self.by_header = {v: k for k, v in self.headers.items()}
        self.regex = re.compile(b"|".join(map(re.escape, self.by_header)))


def _param(data, field, value):
    p = data[field]
    p["value"] = value
    p["hasValue"] = 1


def _expression(data, field, text):
    matches = re.findall(r"\{[^{}]+\}", text)
    if not matches:
        _param(data, field, text)
        return
    remaining = re.sub(r"\{[^{}]+\}", "", text)
    if "{" in remaining or "}" in remaining:
        raise ValueError(f"Unsupported nested or unpaired expression in {text!r}")
    _param(data, field, "")
    data[field]["dynamicValue"].update(PlaybackSpot=deepcopy(data["playbackSpot"]),
                                       ValueText=text, Expressions=matches)


def _path(argument):
    if not re.fullmatch(r"(?:[\w-]+(?:\.[\w-]+)?|\.[\w-]+)", argument):
        raise ValueError(f"Invalid static playback path {argument!r}")
    script, _, label = argument.partition(".")
    return {"name": {"value": script, "hasValue": int(bool(script))},
            "value": {"value": label, "hasValue": int(bool(label))}}


class _Library:
    def __init__(self, objs):
        self.objects = objs
        self.types = _Types(next(iter(objs.values())).assets_file.ref_types)
        self.scripts = {}
        self.templates = {}

    def script(self, name):
        if name not in self.scripts:
            if name not in self.objects:
                raise ValueError(f"No stock script named {name!r}")
            self.scripts[name] = _Script(self.objects[name], self.types)
        return self.scripts[name]

    def template(self, name):
        if name not in self.templates:
            preferred, signature = TEMPLATES[name]
            pattern = re.compile(signature)
            for script in dict.fromkeys((preferred, *self.objects)):
                if script not in self.objects:
                    continue
                try:
                    source = self.script(script)
                except (ValueError, struct.error):
                    continue
                for i in range(len(source.lines)):
                    kind, _, text, _ = source.line(i)
                    if kind == "CommandScriptLine" and pattern.fullmatch(text.strip()):
                        self.templates[name] = source.command(i)[:2]
                        break
                if name in self.templates:
                    break
            else:
                raise ValueError(f"No stock template for @{name}")
        kind, data = self.templates[name]
        return kind, deepcopy(data)

    def control(self, text):
        command, _, argument = text.partition(" ")
        name = command.removeprefix("@")
        if not command.startswith("@") or name not in TEMPLATES:
            raise ValueError(f"Unsupported generated replay command {text!r}")
        argument = argument.strip()
        # Engine condition suffix; quoted expressions may contain internal spaces.
        condition = ""
        for word in re.finditer(r'"(?:\\.|[^"\\])*"|(?<!\S)if:', argument):
            if word[0] == "if:":
                condition = argument[word.end():].strip()
                if not condition:
                    raise ValueError(f"Empty command condition in {text!r}")
                argument = argument[:word.start()].strip()
                break
        kind, data = self.template(name)
        if condition:
            _expression(data, "ConditionalExpression", condition)
        if name in ("goto", "gosub"):
            _param(data, "Path", _path(argument))
        elif name == "set":
            if not argument:
                raise ValueError("Expected an assignment for @set")
            _expression(data, "Expression", argument)
        elif name == "storeEnemyNextActionSet":
            match = re.fullmatch(r'enemyId:([1-9]\d*|\{\w+\}) actionSetName:"(\w+)"', argument)
            if not match:
                raise ValueError(f"Invalid enemy action checkpoint {argument!r}")
            slot = match[1]
            if slot.isdecimal():
                data["EnemyId"]["dynamicValue"] = deepcopy(data["ActionValueAdd"]["dynamicValue"])
                _param(data, "EnemyId", int(slot))
            else:
                data["EnemyId"]["dynamicValue"].update(ValueText=slot, Expressions=[slot])
            _param(data, "ActionSetName", match[2])
        elif name == "choice":
            match = re.fullmatch(r'"([^"\n]+)"\s+goto:(\S+)', argument)
            if not match:
                raise ValueError(f"Invalid @choice {text!r}")
            _param(data, "ChoiceSummary", match[1])
            _param(data, "GotoPath", _path(match[2]))
            _param(data, "IsTrans", 0)
        elif name == "hideUI":
            if not re.fullmatch(r"[\w]+(?:,[\w]+)*", argument):
                raise ValueError(f"Invalid @hideUI {argument!r}")
            _param(data, "UINames", [{"value": t, "hasValue": 1} for t in argument.split(",")])
        elif name == "wait":
            if not re.fullmatch(r"i(?:\d+(?:\.\d+)?)?|\d+(?:\.\d+)?", argument):
                raise ValueError(f"Invalid @wait {argument!r}")
            _param(data, "WaitMode", argument)
        elif name == "back":
            _background(data, argument)
        elif name == "save" and argument:
            if "SlotId" not in data:
                raise ValueError("This stock save command has no named SlotId")
            _param(data, "SlotId", argument)
        elif argument and not (name == "clearChoice" and argument == "*"):
            raise ValueError(f"Unsupported parameters in {text!r}")
        return kind, data


def _background(data, argument):
    m = re.fullmatch(r'(?:"([^"{}]+)"|([^\s{}]+))(?:\s+(.*))?', argument)
    if not m:
        raise ValueError(f"Invalid static artwork address {argument!r}")
    address = m[1] or m[2]
    _param(data, "AppearanceAndTransition",
           {"name": {"value": address, "hasValue": 1}, "value": {"value": "", "hasValue": 0}})
    for opt in (m[3] or "").split():
        key, sep, val = opt.partition(":")
        val = val.strip('"')
        if key == "id" and sep:
            _param(data, "Id", val)
        elif key == "time" and sep:
            _param(data, "Duration", float(val))
        elif key in ("scale", "pos") and sep:
            values = [{"value": float(v) if v else 0.0, "hasValue": int(bool(v))}
                      for v in val.split(",")]
            _param(data, "Scale" if key == "scale" else "ScenePosition", values)
        else:
            raise ValueError(f"Unknown @back option {opt!r}")


def _crc(env):
    # Unity's bundle CRC includes every uncompressed CAB and resource stream,
    # in directory order. This differs from a checksum of the compressed file.
    crc = 0
    for file in env.file.files.values():
        reader = getattr(file, "reader", file)
        crc = zlib.crc32(reader.view, crc)
    return crc


def patch_scripts(source_game, isolated_game, edits):
    """Rebuild from stock in a disposable game copy, preserving other catalog edits.

    Requires UnityPy and the replay support modules on sys.path. A repeated installation
    can use the same isolated copy. Only the script bundle and catalog are
    replaced. Both files are staged before the first replacement.
    """
    source = Path(source_game).resolve()
    target = Path(isolated_game).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("The isolated and source games must be separate directories")
    original = _bundle(source)
    out = target / AA / PLATFORM / original.name
    catalog = target / AA / "catalog.bin"
    if not all(p.resolve().is_relative_to(target) for p in (out.parent, catalog.parent)):
        raise ValueError("The isolated asset directory resolves outside its game")
    if not catalog.is_file() or not out.parent.is_dir():
        raise ValueError("Prepare the isolated game's data directories and catalog first")
    before = catalog.read_bytes()
    if not edits or not any(indices for indices in edits.values()):
        raise ValueError("At least one compiled replay row must be specified")
    expected_digests = {}
    with tempfile.TemporaryDirectory(prefix=".replay-build-", dir=out.parent) as tmp:
        tmp = Path(tmp)
        packed = tmp / original.name
        new_catalog = tmp / "catalog.bin"
        with original.open("rb") as stream:
            env = UnityPy.load(stream)
            original_crc = _crc(env)
            source_data = (source / AA / "catalog.bin").read_bytes()
            offset = catalog_crc._record(source_data, original, (original_crc, original.stat().st_size))
            # Other mods can change CRC/size fields at other catalog locations.
            offset_target = catalog_crc._record(before, original,
                                              struct.unpack_from("<II", before, offset))
            if offset_target != offset:
                raise ValueError("Source and isolated game catalogs have different script locations")
            objs = _scripts(env)
            library = _Library(objs)
            for script, indices in edits.items():
                if script not in objs:
                    raise ValueError(f"Unknown replay script {script!r}")
                # Keep the immutable donor graph separate from modifications.
                changed = _Script(objs[script], library.types)
                for i, spec in sorted(indices.items()):
                    if not isinstance(i, int) or i < 0:
                        raise ValueError(f"Invalid replay row number {i!r}")
                    changed.install(i, spec, library)
                # Cache stock source before assigning new bytes to its Unity reader.
                library.script(script)
                expected_digests[script] = changed.finish()
            packed.write_bytes(env.file.save("lz4"))
        del env, objs, library, changed
        gc.collect()
        with packed.open("rb") as stream:
            check = UnityPy.load(stream)
            checksum = _crc(check)
            check_objs = _scripts(check)
            for script, indices in edits.items():
                if hashlib.sha256(check_objs[script].get_raw_data()).digest() != expected_digests[script]:
                    raise ValueError(f"Compiled payload changed while writing {script}")
                rows = read_lines(check_objs[script])
                if any(i >= len(rows) or rows[i][0] != i for i in indices):
                    raise ValueError(f"Compiled row did not round-trip in {script}")
        del check, check_objs
        gc.collect()
        size = packed.stat().st_size
        stored_crc = checksum if U32.unpack_from(source_data, offset)[0] else 0
        blob = before[:offset] + struct.pack("<II", stored_crc, size) + before[offset+8:]
        catalog_crc._record(blob, original, (checksum, size))
        new_catalog.write_bytes(blob)
        # Replacing hardlinks instead of writing through protects the source game.
        backup = tmp / "previous.bundle"
        if out.exists():
            # The active file stays present until the atomic replacement even
            # if power is lost in this window. The previous row map is still
            # available to roll back an ordinary catalog replacement failure.
            shutil.copyfile(out, backup)
        try:
            os.replace(packed, out)
            os.replace(new_catalog, catalog)
        except BaseException:
            if backup.exists():
                os.replace(backup, out)
            elif out.exists():
                out.unlink()
            raise
    return {"bundle": original.name, "scripts": {s: len(rows) for s, rows in edits.items()},
            "crc": stored_crc, "size": size}
