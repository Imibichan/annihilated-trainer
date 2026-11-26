"""Retire only independently identified replay copies after their replacement is ready."""
import hashlib
import hmac
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import stat
import tempfile
import zlib

from . import isolation as iso


STATE = ("Naninovel.CustomVariableManager+GlobalState, Elringus.Naninovel.Runtime, "
         "Version=0.0.0.0, Culture=neutral, PublicKeyToken=null")
SAVE = Path("NaninovelData/Saves/GlobalSave.nson")
LIMIT = 32 * 1024 * 1024
KEYS = ("G_v15Lead", "G_v15Last")
OLD_ID = re.compile(r"[0-9a-f]{12}")
BUILD_ID = re.compile(r"build-[0-9a-f]{20}")
JOURNAL = ".v16-retirement.json"
RETIRED = ".retiring-game"
# These edited-by-build Unity files differ between the two known official
# releases. The original V1.5 QA installation independently matches these
# fingerprints. Unknown changes to configuration or native plugins are kept.
HISTORIC_FILES = {
    iso.DATA + "/boot.config": "cbd2d90829b60cf1e78a2908c62a1b0424d8beeddec43d9576697df726458645",
    iso.DATA + "/RuntimeInitializeOnLoads.json": "d5f7213137d2355dda46fa3be47ecd3c6251e11dda2f7ef13ec56012f9a700cc",
    iso.AA + "settings.json": "bda87da580ad0d1504cdc61532ba57e65e7890f02ec3b427bacd742dfb37dcf9",
    iso.DATA + "/Plugins/x86_64/lib_burst_generated.dll": "2a8ce92f06f705c6dc1987b5f2ef2a4e356ba179f00c6fe5d570631efe8c56bf",
}


def _read(path, limit):
    path = iso._check_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise ValueError("回放记录文件类型或大小无效。")
    return path.read_bytes()


def _record(path):
    obj = json.loads(_read(path, iso.MARKER_LIMIT))
    if not isinstance(obj, dict):
        raise ValueError("无效回放记录。")
    return obj


def _legacy_id(source, game):
    identity = hashlib.sha256(os.path.normcase(str(iso.display_path(source.resolve()))).encode())
    path = game / (iso.AA + "catalog.hash")
    if path.exists():
        identity.update(_read(path, 1024))
    return identity.hexdigest()[:12]


def _candidates(folder):
    yield folder / "game"
    if not OLD_ID.fullmatch(folder.name):
        for name in iso.STAGING_NAMES:
            yield folder / name
    else:
        for entry in folder.glob(".orien-prepare-*"):
            if re.fullmatch(r"\.orien-prepare-[a-zA-Z0-9_-]{6,24}", entry.name):
                yield entry / "payload"


def legacy_folders(source, root):
    result = []
    current = _legacy_id(source, source)
    for folder in root.iterdir():
        if not OLD_ID.fullmatch(folder.name):
            continue
        try:
            iso._check_path(folder)
            if not folder.is_dir():
                continue
            if folder.name == current or any(
                    game.is_dir() and folder.name == _legacy_id(source, iso._check_path(game))
                    for game in _candidates(folder)):
                result.append(folder)
                continue
            # An interrupted retirement may have already removed catalog.hash.
            journal = _record_header(folder)
            if journal and iso._same_directory(journal.get("source"), source):
                result.append(folder)
        except (OSError, ValueError, TypeError):
            continue
    return sorted(result)


def check_running_games(cache, legacy):
    """A killed launcher can release its byte lock while its Unity child is still open."""
    folders = [*legacy, *(p for p in cache.iterdir() if BUILD_ID.fullmatch(p.name))]
    programs = [folder / "game" / (iso.GAME + ".exe") for folder in folders]
    programs = [p for p in programs if p.is_file()]
    if os.name != "nt" or not programs:
        return
    cmd = ("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
           "Get-Process -Name Annihilated -ErrorAction SilentlyContinue | ForEach-Object {$_.Path};exit 0")
    result = iso.windows_powershell(cmd, timeout=20)
    result.check_returncode()
    for line in result.stdout.decode("utf-8-sig").splitlines():
        if line and any(iso._same_directory(line, p) for p in programs):
            raise RuntimeError("请先退出正在运行的旧回放窗口，再重新启动回放。")


def _sequence(obj):
    keys, values = obj["keys"], obj["values"]
    if (not isinstance(keys, list) or not isinstance(values, list) or len(keys) != len(values)
            or not all(isinstance(item, str) for item in keys + values) or len(set(keys)) != len(keys)):
        raise ValueError("回放全局存档键值结构无效。")
    return keys, values


def _preferences(profile):
    path = profile / SAVE
    packed = _read(path, LIMIT)
    decoder = zlib.decompressobj(-15)
    raw = decoder.decompress(packed, LIMIT + 1)
    if len(raw) > LIMIT or not decoder.eof or decoder.unused_data:
        raise ValueError("回放全局存档压缩格式无效。")
    keys, values = _sequence(json.loads(raw.decode("utf-8-sig"))["objectJsonMap"])
    data = json.loads(values[keys.index(STATE)])
    keys, values = _sequence(data["GlobalVariableMap"])
    fields = dict(zip(keys, values))
    result = {}
    if fields.get(KEYS[0]) in ("1", "2"):
        result[KEYS[0]] = fields[KEYS[0]]
    last = fields.get(KEYS[1], "")
    if re.fullmatch(r"[1-9][0-9]{0,7}", last) and int(last) <= 0xffffff:
        result[KEYS[1]] = last
    return path.stat().st_mtime_ns, result


def _seed(profile, fields):
    output = iso._check_path(profile / SAVE, allow_missing=True)
    if not fields or os.path.lexists(output):
        return False
    # Naninovel's generic state map can contain a subset of manager states.
    # Only these two variables may enter the new company's first global save.
    inner = {"GlobalVariableMap": {"keys": list(fields), "values": list(fields.values())}}
    outer = {"objectJsonMap": {"keys": [STATE], "values": [json.dumps(inner)]}}
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(json.dumps(outer).encode("utf-8-sig")) + compressor.flush()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(packed)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # Windows rename is atomic and refuses to replace an existing file.
        tmp.rename(output)
    finally:
        tmp.unlink(missing_ok=True)
    if _preferences(profile)[1] != fields:
        raise OSError("回放偏好写入后未通过复核。")
    return True


def _owner(source, folder, game):
    """Corroborate the directory name and marker with the Unity files inside it."""
    iso._check_path(game)
    marker = _record(game / iso.MARKER) if (game / iso.MARKER).exists() else None
    legacy = bool(OLD_ID.fullmatch(folder.name))
    if not legacy and (not BUILD_ID.fullmatch(folder.name) or marker is None):
        raise ValueError("没有可验证的回放副本。")
    build_hash = game / (iso.AA + "catalog.hash")
    if (legacy and folder.name != _legacy_id(source, game)
            and (build_hash.exists() or folder.name != _legacy_id(source, source))):
        raise ValueError("旧副本与游戏安装路径和资源版本不一致。")
    if marker:
        if not iso._same_directory(marker.get("source"), source) or marker.get("schema") != (1 if legacy else 2):
            raise ValueError("副本来源不同。")
        if game.name in (*iso.STAGING_NAMES, "payload"):
            intended = Path(marker.get("root", ""))
            if intended.name != "game" or not iso._same_directory(str(intended.parent), folder):
                raise ValueError("未完成的回放副本路径无效。")
        elif not iso._same_directory(marker.get("root"), game):
            raise ValueError("副本记录的目录不同。")
        if not legacy and marker.get("directoryId") != game.stat().st_ino:
            raise ValueError("副本目录已被替换。")
        if not legacy and (folder.name != iso.build_folder_name(marker["sourceBuild"], marker["programInputs"])
                or marker["sourceBuild"]["fileNames"] != iso.file_names_hash(marker.get("copiedFiles", []))):
            raise ValueError("副本来源清单与已生成的回放版本不符。")
    prefix = "Or15" if legacy else "Or16"
    if game.name in iso.STAGING_NAMES:
        company = marker["company"]
    elif marker and (not (game / iso.APP_INFO).is_file() or not (game / iso.MANAGERS).is_file()):
        company = marker["company"]
        app, manager = game / iso.APP_INFO, game / iso.MANAGERS
        stamp = iso.legacy_stamp(game)
        if (not (app.is_file() or manager.is_file()) or not stamp or
                any(marker["sourceBuild"].get(k) != v for k, v in stamp.items()) or
                (app.is_file() and iso._company_info(_read(app, 1024)) != company) or
                (manager.is_file() and (iso._file_hash(manager) != marker["managerSha256"] or
                                        _read(manager, LIMIT).count(company.encode()) != 1))):
            raise ValueError("未完成旧副本的存档配置缺少独立佐证。")
    else:
        company = iso._company_info(_read(game / iso.APP_INFO, 1024))
        manager = _read(game / iso.MANAGERS, LIMIT)
        if manager.count(company.encode()) != 1 or iso.SOURCE_COMPANY.encode() in manager:
            raise ValueError("副本未使用独立公司名。")
        if marker:
            if company != marker.get("company") or hashlib.sha256(manager).hexdigest() != marker.get("managerSha256"):
                raise ValueError("副本的独立存档配置无法核实。")
            build = marker.get("sourceBuild")
            if not isinstance(build, dict) or any(build.get(k) != v for k,v in iso.legacy_stamp(game).items()):
                raise ValueError("副本游戏版本无法核实。")
        else:
            old_stamp = iso.legacy_stamp(game)
            installed = iso.legacy_stamp(source)
            same_build = (bool(old_stamp) and all(installed.get(k) == v for k,v in old_stamp.items()) and
                          manager.replace(company.encode(), iso.SOURCE_COMPANY.encode()) ==
                          (source / iso.MANAGERS).read_bytes())
            # A later content update may replace the assembly and Unity manager.
            # The directory name already binds this old catalog.hash to the exact
            # source path. Additionally require two independently matching player
            # binaries and the validated platform SDK for an unmarked old build.
            if not same_build and not (build_hash.is_file() and (game / iso.VENDOR).is_file() and
                    all((game / n).is_file() and iso._file_hash(game / n) == iso._file_hash(source / n)
                        for n in (iso.GAME + ".exe", "UnityPlayer.dll"))):
                raise ValueError("无标记旧副本缺少同一安装的独立佐证。")
    if not isinstance(company, str) or not re.fullmatch(prefix + r"[0-9a-f]{7}", company):
        raise ValueError("副本存档公司名无效。")
    if (game / iso.VENDOR).exists():
        iso._vendor_hash(game / iso.VENDOR)
    return company


def _file_id(path):
    info = path.lstat()
    iso._reject_link(path, info)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("旧副本含共享文件。")
    return [info.st_ino, info.st_size, info.st_mtime_ns]


def _workfiles(game, bundle_names):
    aa = game / iso.AA
    locations = [(aa, ".replay-title-record-", {"catalog.bin"}),
                 (aa / "StandaloneWindows64", ".replay-font-", {"previous.bundle", "catalog.bin",
                    *(name for name in bundle_names if iso.MENU_FONT_BUNDLE.fullmatch(name))}),
                 (aa / "StandaloneWindows64", ".replay-title-", {"previous.bundle", "catalog.bin",
                    *(name for name in bundle_names if iso.TITLE_BUNDLE.fullmatch(name))}),
                 (aa / "StandaloneWindows64", ".replay-build-", {"previous.bundle", "catalog.bin",
                    *(name for name in bundle_names if name.lower().startswith("naninovel_assets_naninovel"))})]
    for parent, prefix, names in locations:
        for directory in parent.glob(prefix + "*"):
            if re.fullmatch(re.escape(prefix) + r"[a-z0-9_]{8}", directory.name):
                iso._check_path(directory)
                if directory.is_dir():
                    yield directory, names


def clean_interrupted_work(game, names):
    for directory, allowed in _workfiles(game, names):
        observed = list(directory.iterdir())
        if not all(p.name in allowed for p in observed):
            continue
        identities = [(p, _file_id(p)) for p in observed]
        for path, identity in identities:
            if _file_id(path) != identity:
                raise ValueError("回放临时文件在清理时发生变化。")
            path.unlink()
        directory.rmdir()


def _legacy_member(source, rel, file, registered, groups):
    if rel in iso.ROOT_FILES | {iso.APP_INFO, iso.MANAGERS, iso.MARKER, ".v15-program.json",
                                iso.VENDOR, iso.AA+"catalog.hash", iso.AA+"catalog.bin"}:
        return
    if file.name in registered and rel == iso.AA + "StandaloneWindows64/" + file.name:
        return
    known = {iso.DATA + "/" + n for n in ("boot.config", "RuntimeInitializeOnLoads.json", "ScriptingAssemblies.json",
             "Resources/unity default resources", "Resources/unity_builtin_extra", "StreamingAssets/LICENSES.txt")}
    known.update(iso.DATA + "/Plugins/x86_64/" + n for n in iso.NATIVE_PLUGINS)
    known.update((iso.AA + "settings.json", "D3D12/D3D12Core.dll"))
    if re.fullmatch(re.escape(iso.DATA) + r"/(?:level\d+|(?:globalgamemanagers|resources|sharedassets\d+)\.(?:resource|assets(?:\.resS)?))",rel):
        return
    if rel == iso.DATA + "/il2cpp_data/Metadata/global-metadata.dat" or re.fullmatch(
            re.escape(iso.DATA) + r"/il2cpp_data/Resources/[\w.\-]+\.dll-resources\.dat", rel):
        return
    orphan_bundle = (rel == iso.AA + "StandaloneWindows64/" + file.name and
                     file.name.partition("_assets_")[0] in groups and
                     re.fullmatch(r"[\w-]+_[a-f0-9]{32}\.bundle", file.name, re.I))
    if rel in known or orphan_bundle:
        digest = iso._file_hash(file)
        current = source / rel
        if digest == HISTORIC_FILES.get(rel) or (current.is_file() and iso._file_hash(current) == digest):
            return
    raise ValueError("旧副本含来源不明或由玩家修改的文件：" + rel)


def _snapshot(source, source_names, game, legacy):
    # A Steam update can rename hundreds of content-hashed Addressables.
    # The old typed local bundle registry authenticates those historical names.
    allowed = set(source_names)
    if not legacy:
        # The copy manifest is written before the first asset and includes old
        # names removed by subsequent Steam builds. A partial catalog may still
        # be truncated when a new generation supersedes this one.
        recorded = _record(game / iso.MARKER).get("copiedFiles", [])
        for rel in recorded:
            path = Path(rel)
            if (not path.parts or path.is_absolute() or path.drive or ".." in path.parts or ":" in rel
                    or not (rel in iso.ROOT_FILES or path.parts[0] in iso.ROOT_DIRS)):
                raise ValueError("旧回放清单含不安全的文件路径。")
        allowed.update(recorded)
    allowed.update((iso.MARKER, ".v15-program.json" if legacy else ".v16-program.json"))
    catalog = game / (iso.AA + "catalog.bin")
    names = []
    if catalog.is_file():
        from addressables import bundle_locations
        if not legacy and game.name in iso.STAGING_NAMES:
            names = [Path(n).name for n in recorded if n.endswith(".bundle")]
        else:
            names = bundle_locations(_read(catalog, LIMIT))
        allowed.update(iso.AA + "StandaloneWindows64/" + name for name in names)
    dirs = {parent.as_posix() for name in allowed for parent in Path(name).parents}
    temporary_members = set()
    for directory, temporary in _workfiles(game, names):
        dirs.add(directory.relative_to(game).as_posix())
        temporary_members.update((directory / n).relative_to(game).as_posix() for n in temporary)
    allowed.update(temporary_members)
    registered = set(names)
    groups = {n.partition("_assets_")[0] for n in names if "_assets_" in n}
    info = {} if legacy else _record(game / iso.MARKER)
    digests = info.get("payloadSha256", {})
    mutable = set() if legacy else iso._mutable(info)
    files, directories = {}, {}
    for base, subdirs, members in os.walk(game, onerror=lambda error: (_ for _ in ()).throw(error)):
        base = Path(base)
        for name in subdirs:
            path = base / name
            iso._reject_link(path, path.lstat())
            relative = path.relative_to(game).as_posix()
            if relative not in dirs:
                raise ValueError("旧副本含无法识别的目录。")
            directories[relative] = path.stat().st_ino
        for name in members:
            path = base / name
            rel = path.relative_to(game).as_posix()
            if rel not in allowed:
                raise ValueError("旧副本含无法识别的文件：" + rel)
            files[rel] = _file_id(path)
            if legacy and rel not in temporary_members:
                _legacy_member(source, rel, path, registered, groups)
            elif game.name not in iso.STAGING_NAMES and rel in digests and rel not in mutable:
                if iso._file_hash(path) != digests[rel]:
                    raise ValueError("旧回放中包含已修改的文件：" + rel)
    return files, directories


def _record_header(folder):
    path = folder / JOURNAL
    if path.is_file():
        record = json.loads(_read(path, 4 * 1024 * 1024))
        if not isinstance(record, dict):
            raise ValueError("无效的回放清理记录。")
        return record


def _sign(cache, plan, *, create=False):
    keyfile = iso._check_path(cache / ".retirement-key", allow_missing=True)
    if create and not keyfile.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(secrets.token_bytes(32))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            tmp.rename(keyfile)
        finally:
            tmp.unlink(missing_ok=True)
    key = _read(keyfile, 32)
    if len(key) != 32:
        raise ValueError("回放清理签名密钥格式不正确。")
    body = {name: value for name, value in plan.items() if name != "signature"}
    return hmac.new(key, json.dumps(body, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def _strict_child(root, name):
    relative = PureWindowsPath(name)
    if (not name or relative.anchor or ".." in relative.parts or relative.as_posix() != name or ":" in name
            or any(ntpath.isreserved(p) for p in relative.parts)):
        raise ValueError("清理记录包含不安全路径。")
    path = iso._check_path(root / name, allow_missing=True)
    resolved = path.resolve()
    resolved_root = root.resolve()
    # MSIX can report the normal LocalAppData path for directories, and
    # LocalCache/Local for each file inside the very same directory. Require
    # the *entire* relative suffix and independently compare its ancestor's NTFS
    # identity. A shared prefix or a coincidentally matching basename is insufficient.
    if resolved.parent == resolved or resolved == resolved_root:
        raise ValueError("清理目标超出旧回放目录。")
    if not resolved.is_relative_to(resolved_root):
        depth = len(relative.parts)
        if len(resolved.parents) < depth:
            raise ValueError("清理目标超出旧回放目录。")
        backing_root = resolved.parents[depth - 1]
        if (resolved.relative_to(backing_root) != Path(name)
                or not iso._same_directory(str(backing_root), root)):
            raise ValueError("清理目标超出旧回放目录。")
    return path


def _finish(source, cache, folder, plan):
    """Delete only previously inspected regular files still bearing the same file identity."""
    if (not hmac.compare_digest(_sign(cache, plan), plan.get("signature", ""))
            or not iso._same_directory(plan.get("source"), source)
            or not iso._same_directory(plan.get("cache"), cache)
            or not iso._same_directory(plan.get("folder"), folder)):
        raise ValueError("清理记录与本次安装不一致。")
    rel = plan["target"]
    if rel not in ("game", *iso.STAGING_NAMES) and not re.fullmatch(r"\.orien-prepare-[\w-]{6,24}/payload", rel):
        raise ValueError("清理记录的目标无效。")
    original = iso._check_path(folder / rel, allow_missing=True)
    retired = iso._check_path(folder / RETIRED, allow_missing=True)
    journal = folder / JOURNAL
    for name in (*plan["files"], *plan["directories"]):
        _strict_child(retired if retired.exists() else original, name)
    if not retired.exists():
        if not original.exists():
            journal.unlink()
            return
        if original.stat().st_ino != plan["directoryId"]:
            raise ValueError("旧回放目录已被替换。")
        original.rename(retired)
    if (_strict_child(folder, RETIRED).stat().st_ino != plan["directoryId"]
            or not iso._same_directory(str(retired.resolve().parent), folder)):
        raise ValueError("旧回放目录身份已改变。")
    # Do not use recursive deletion. An unexpected addition, junction or shared
    # link is never deleted, even if another process inserts it after the rename.
    files = plan["files"]
    for name, identity in files.items():
        path = _strict_child(retired, name)
        if path.exists() and _file_id(path) != identity:
            raise ValueError("清理期间回放文件已被替换。")
    for name, identity in files.items():
        path = _strict_child(retired, name)
        if path.exists():
            if _file_id(path) != identity:
                raise ValueError("清理期间回放文件发生变化。")
            path.unlink()
    for name, inode in sorted(plan["directories"].items(), key=lambda item: len(Path(item[0]).parts), reverse=True):
        directory = _strict_child(retired, name)
        if os.path.lexists(directory):
            if directory.stat().st_ino != inode:
                raise ValueError("旧回放子目录已被替换。")
            directory.rmdir()
    if retired.exists():
        retired.rmdir()
    journal.unlink()
    if original.parent != folder and original.parent.is_dir() and not any(original.parent.iterdir()):
        original.parent.rmdir()
    if BUILD_ID.fullmatch(folder.name) and not any(folder.iterdir()):
        folder.rmdir()


def retire_old_games(source, cache, game, legacy):
    folders = [*legacy, *(p for p in cache.iterdir() if BUILD_ID.fullmatch(p.name) and p != game.root.parent)]
    folders = [p for p in folders if (p / JOURNAL).exists() or any(os.path.lexists(g) for g in _candidates(p))]
    if not folders:
        return {"removed": [], "preserved": [], "preferences": [], "preferencesUnreadable": []}
    game = iso.verify_copy(game.root)
    receipt = json.loads(_read(game.root / ".v16-program.json", 4 * 1024 * 1024))
    marker = _record(game.root / iso.MARKER)
    script = receipt["packed"]["bundle"]
    if not re.fullmatch(r"naninovel_assets_naninovel(?:_[a-zA-Z0-9-]+)?\.bundle", script, re.I):
        raise ValueError("新回放的剧本资源记录无效。")
    checks = {"bundleSha": iso.AA + "StandaloneWindows64/" + script, "titleSha": marker["titleFile"],
              "catalogSha": iso.AA + "catalog.bin"}
    if marker.get("fontFile"):
        checks["fontSha"] = marker["fontFile"]
    if (not iso._same_directory(marker["source"], source) or
            any(receipt.get(k) != iso._file_hash(iso._check_path(game.root / p)) for k,p in checks.items())):
        raise ValueError("新回放尚未完成资源回读。")
    sources = None
    plans, preferences, preserved, removed, unreadable = [], [], [], [], []
    for folder in folders:
        try:
            iso._check_path(folder)
            prior = _record_header(folder)
            if prior:
                _finish(source, cache, folder, prior)
                removed.append(folder.name)
        except (ValueError, TypeError, KeyError, OSError) as error:
            preserved.append([folder.name, str(error)])
            continue
        for old in _candidates(folder):
            if not os.path.lexists(old):
                continue
            try:
                company = _owner(source, folder, old)
                if sources is None:
                    sources = {p.relative_to(source).as_posix() for p in iso._source_members(source)}
                files, directories = _snapshot(source, sources, old, folder in legacy)
                plans.append((folder, {"source": str(iso.display_path(source)), "cache": str(iso.display_path(cache)),
                                       "folder": str(iso.display_path(folder)),
                                       "directoryId": old.stat().st_ino,
                                       "target": old.relative_to(folder).as_posix(), "files": files,
                                       "directories": directories}))
            except (OSError, ValueError, KeyError, TypeError) as error:
                preserved.append([str(old), str(error)])
                continue
            try:
                preferences.append(_preferences(iso._profile(company)))
            except FileNotFoundError:
                pass
            except (OSError, ValueError, KeyError, TypeError, zlib.error) as error:
                unreadable.append([company, str(error)])
    fields = {}
    for _, prefs in sorted(preferences, key=lambda x: x[0], reverse=True):
        for key, value in prefs.items():
            fields.setdefault(key, value)
    inherited = _seed(game.profile, fields)
    for folder, plan in plans:
        if (folder / JOURNAL).exists() or (folder / RETIRED).exists():
            preserved.append([str(folder), "已存在未完成的清理记录。"])
            continue
        plan["signature"] = _sign(cache, plan, create=True)
        iso.atomic_json(folder / JOURNAL, plan)
        _finish(source, cache, folder, plan)
        removed.append(folder.name)
    return {"removed": removed, "preserved": preserved, "preferences": list(fields) if inherited else [],
            "preferencesUnreadable": unreadable}
