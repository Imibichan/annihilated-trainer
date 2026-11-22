"""Build a private Windows Unity player tree from the player's installed game."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import tempfile


GAME = "Annihilated"
DATA = GAME + "_Data"
APP_INFO = DATA + "/app.info"
MANAGERS = DATA + "/globalgamemanagers"
AA = DATA + "/StreamingAssets/aa/"
TITLE_BUNDLE = re.compile(r"naninovelstartupui_assets_all(?:_[A-Za-z0-9-]+)?\.bundle", re.I)
MENU_FONT_BUNDLE = re.compile(r"startupuiinitialdependencies_assets_all(?:_[A-Za-z0-9-]+)?\.bundle", re.I)
STOCK_HASHES = {
    AA + "StandaloneWindows64/naninovelstartupui_assets_all_3b70a54d9568632d966864a781231a5e.bundle":
        "954fd3c769c749584942e681398df9c203ec44b948f0f93efde90fc8af85517e",
    AA + "catalog.bin": "a5dfc10364064feeb51d707f1a2fc58b7aeab2d44e2087f4d15cc303fb7a89da",
}
# The complete matched baseline published with V1.4 (验证记录.txt). The replay title
# bypasses the legacy title panel. No individual legacy file may be substituted alone.
V14_HASHES = {
    AA + "StandaloneWindows64/naninovelstartupui_assets_all_3b70a54d9568632d966864a781231a5e.bundle":
        "3b144dea62365f0776e6446c446bf80697c9d30c88fdb3820ca7979c6b37a814",
    AA + "catalog.bin": "905917be4f3f2fedd0bab4d02d8c42a1c8001329a84006322c2279a145901215",
}
MARKER = ".orien-replay-copy.json"
MARKER_LIMIT = 4 * 1024 * 1024
STATE = ".annihilated-cg-gallery"
SOURCE_COMPANY = "DeathKumiai"
ROOT_FILES = {"Annihilated.exe", "UnityPlayer.dll", "GameAssembly.dll", "baselib.dll", "UnityCrashHandler64.exe"}
ROOT_DIRS = {DATA, "D3D12"}
ROOT_REQUIRED = {"Annihilated.exe", "GameAssembly.dll", "UnityPlayer.dll", "baselib.dll"}
NATIVE_PLUGINS = {"lib_burst_generated.dll", "libonigwrap.dll"}
VENDOR = DATA + "/Plugins/x86_64/steam_api64.dll"
# SHA-256 of the original Valve Corp. Authenticode-signed SDK from the supported game.
VENDOR_HASH = "a44e5537939ae4eebc69000589aa9b2437a667813a1657cc779198bae9b815a9"


@dataclass(frozen=True)
class IsolatedGame:
    root: Path
    executable: Path
    company: str
    profile: Path


def local_low():
    """Use the same Windows Known Folder that Unity uses, including redirected profiles."""
    if os.name != "nt":
        return Path.home() / "AppData" / "LocalLow"
    import ctypes
    import uuid
    guid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("A520A1A4-1780-4FF6-BD18-167343C5AF16").bytes_le)
    folder = ctypes.c_wchar_p()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(folder))
    if result:
        # An unpackaged/sandbox child can inherit the actual user profile while its
        # restricted token has no KnownFolder entry. Use the conventional location
        # only if the inherited LocalAppData independently identifies this profile.
        profile = os.environ.get("USERPROFILE")
        local = os.environ.get("LOCALAPPDATA")
        if profile and local and Path(local).parent == Path(profile) / "AppData":
            conventional = Path(profile) / "AppData/LocalLow"
            if conventional.is_dir():
                return conventional
        raise OSError(f"无法确定 Windows LocalLow 存档目录（{result:#x}）。")
    try:
        return Path(folder.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(folder)


def _check_path(path, *, allow_missing=False):
    """Reject symlinks and Windows junctions, including those in parent directories."""
    path = Path(os.path.abspath(path))
    for member in (*reversed(path.parents), path):
        try:
            info = member.lstat()
        except FileNotFoundError:
            if allow_missing:
                break
            raise
        _reject_link(member, info)
    return path


def _reject_link(path, info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError(f"隔离目录不支持链接或重解析点：{path}")


def _file_hash(path):
    with path.open("rb") as reader:
        return hashlib.file_digest(reader, "sha256").hexdigest()


def atomic_json(path, value, *, temp_dir=None):
    with tempfile.NamedTemporaryFile(dir=temp_dir or path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(json.dumps(value, ensure_ascii=False).encode())
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _overlap(first, second):
    return first.is_relative_to(second) or second.is_relative_to(first)


def _steam_file(name):
    # Includes both 32/64-bit SDK DLLs, Steam app-id overrides and auto-cloud hints.
    return name.casefold().startswith(("steam_api", "steamclient", "steam_appid", "steam_autocloud", "steamworks."))


def _source_members(source):
    """Ignore other root-level mods, launchers, backups, and their configuration."""
    for name in sorted(ROOT_FILES | ROOT_DIRS):
        path = source / name
        if not os.path.lexists(path):
            if name in ROOT_REQUIRED or name == DATA:
                raise FileNotFoundError(f"游戏目录缺少 {name}。")
            continue
        _reject_link(path, path.lstat())
        if name in ROOT_FILES:
            if not path.is_file():
                raise ValueError(f"游戏文件不是常规文件：{path}")
            yield path
            continue
        if not path.is_dir():
            raise ValueError(f"无效游戏目录：{path}")
        yield from _tree_files(path, source=True)
    yield _check_path(source / VENDOR)


def _tree_files(root, *, source=False):
    for entry in root.iterdir():
        if source and (_steam_file(entry.name) or entry.name in {"Saves", "NaninovelData"}):
            continue
        info = entry.lstat()
        _reject_link(entry, info)
        if stat.S_ISDIR(info.st_mode):
            yield from _tree_files(entry, source=source)
        elif stat.S_ISREG(info.st_mode):
            if source and entry.suffix.lower() in {".dll", ".exe"} and "Plugins" in entry.parts:
                if entry.name.lower() not in NATIVE_PLUGINS:
                    continue
            if not source and info.st_nlink != 1:
                raise ValueError(f"回放文件存在共享硬链接：{entry}")
            yield entry
        else:
            raise ValueError(f"不支持的游戏文件：{entry}")


def _stock_inputs(source, fallback):
    result = {}
    manifest = None
    for name, expected in STOCK_HASHES.items():
        installed = _check_path(source / name)
        if _file_hash(installed) == expected:
            result[name] = installed
            continue
        try:
            state = source / STATE
            if manifest is None:
                manifest_path = _check_path(state / "manifest.json")
                if manifest_path.stat().st_size > 32768:
                    raise ValueError("V1.4 备份记录过大。")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows = manifest["files"]
            if manifest.get("schema") != 1 or not isinstance(rows, list) or len(rows) != len(STOCK_HASHES):
                raise ValueError("V1.4 备份记录无效。")
            index, = [i for i, row in enumerate(rows) if row.get("path") == name and row.get("original") == expected]
            original = _check_path(state / f"original-{index}.bin")
            if _file_hash(original) != expected:
                raise ValueError("V1.4 原版备份校验失败。")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            if fallback is None:
                raise ValueError(f"无法从当前安装或 V1.4 备份核实原版资源 {name}。请指定同版本原版目录。") from error
            original = _check_path(fallback / name)
            if _file_hash(original) != expected:
                raise ValueError(f"备用目录中的原版资源校验失败：{name}") from error
        result[name] = original
    return result


def _gallery_inputs(source, fallback):
    catalog_name = AA + "catalog.bin"
    catalog = _check_path(source / catalog_name)
    catalog_hash = _file_hash(catalog)
    recorded_legacy = False
    manifest = source / STATE / "manifest.json"
    if manifest.is_file():
        try:
            manifest = _check_path(manifest)
            if manifest.stat().st_size <= 32768:
                data = json.loads(manifest.read_bytes())
                rows = data["files"]
                recorded_legacy = (data["schema"] == 1 and len(rows) == len(STOCK_HASHES)
                                   and {r["path"] for r in rows} == set(STOCK_HASHES)
                                   and all(r["original"] == STOCK_HASHES[r["path"]] and
                                           r["patched"] == _file_hash(_check_path(source / r["path"])) for r in rows))
        except (OSError, KeyError, ValueError, TypeError):
            pass
    if not recorded_legacy and catalog_hash not in (STOCK_HASHES[catalog_name], V14_HASHES[catalog_name]):
        # A Steam update can retain an old V1.4 backup directory. Its catalog
        # has no authority over this newly installed set of bundles.
        import catalog_crc
        from addressables import bundle_locations
        binary = catalog.read_bytes()
        names = [n for n in bundle_locations(binary) if TITLE_BUNDLE.fullmatch(n)]
        if len(names) != 1:
            raise ValueError("当前资源目录未唯一登记 Naninovel 启动界面。")
        title_name = AA + "StandaloneWindows64/" + names[0]
        title = _check_path(source / title_name)
        catalog_crc.locate(binary, title)
        return ({title_name: title, catalog_name: catalog},
                {title_name: _file_hash(title), catalog_name: catalog_hash}, "installed")
    try:
        return _stock_inputs(source, fallback), STOCK_HASHES, "stock"
    except (PermissionError, FileNotFoundError, ValueError) as error:
        installed = {name: _check_path(source / name) for name in V14_HASHES}
        if all(_file_hash(path) == V14_HASHES[name] for name, path in installed.items()):
            return installed, V14_HASHES, "published-v1.4"
        raise ValueError("游戏画廊资源不匹配已验证的完整 V1.4 文件组，且无法恢复原版。"
                         "请检查同版本原版备份，或在 Steam 中验证游戏文件。") from error


def _new_company():
    saves = local_low()
    while True:
        company = "Or16" + secrets.token_hex(4)[:7]
        if os.path.lexists(saves / company):
            continue
        if os.name == "nt":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\" + company):
                    continue
            except FileNotFoundError:
                pass
        return company


def _company_info(raw):
    lines = raw.decode("utf-8-sig").splitlines()
    if len(lines) != 2 or lines[1] != GAME:
        raise ValueError("无法核实 Unity 产品名和存档公司名。")
    return lines[0]


def _private_configs(source, company):
    app = _check_path(source / APP_INFO).read_bytes()
    manager = _check_path(source / MANAGERS).read_bytes()
    old = SOURCE_COMPANY.encode()
    if _company_info(app) != SOURCE_COMPANY or app.count(old) != 1 or manager.count(old) != 1:
        raise ValueError("当前 Unity 存档配置无法安全隔离，请选择原版安装目录。")
    return {name: data.replace(old, company.encode("ascii")) for name, data in [(APP_INFO, app), (MANAGERS, manager)]}


def _profile(company):
    path = _check_path(local_low() / company / GAME, allow_missing=True)
    if path.exists():
        # The game writes inside this tree; do not allow a redirected child to point at a real save.
        for _ in _tree_files(path):
            pass
    return path


def legacy_stamp(source):
    return {name: _file_hash(_check_path(source / name)) for name in ("GameAssembly.dll", AA + "catalog.hash")
            if (source / name).exists()}


def source_stamp(source):
    stamp = legacy_stamp(source)
    stamp[AA + "catalog.bin"] = _file_hash(_check_path(source / (AA + "catalog.bin")))
    inventory = hashlib.sha256()
    names = []
    for path in sorted(_source_members(source)):
        info = path.stat()
        name = path.relative_to(source).as_posix()
        names.append(name)
        inventory.update(f"{name}\0{info.st_size}\0{info.st_mtime_ns}\n".encode())
    stamp["installedFiles"] = inventory.hexdigest()
    stamp["fileNames"] = file_names_hash(names)
    return stamp


def file_names_hash(names):
    return hashlib.sha256(json.dumps(sorted(names), ensure_ascii=True).encode()).hexdigest()


def build_folder_name(stamp, inputs):
    identity = json.dumps([stamp, inputs], sort_keys=True).encode()
    return "build-" + hashlib.sha256(identity).hexdigest()[:20]


def windows_powershell(command, *, environment=None, timeout=30):
    directory = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0"
    env = {k: v for k, v in os.environ.items() if k.casefold() != "psmodulepath"}
    env.update(environment or {})
    env["PSModulePath"] = str(directory / "Modules")
    return subprocess.run([str(directory / "powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", command],
                          env=env, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout)


def _vendor_hash(path):
    digest = _file_hash(path)
    if digest == VENDOR_HASH:
        return digest
    if os.name == "nt":
        # Only a valid, trusted Authenticode chain with Valve's signing
        # identity can authorize a previously unseen Steamworks SDK.
        command = ("$ErrorActionPreference='Stop';"
                   "$s=Get-AuthenticodeSignature -LiteralPath $env:ORIEN_VERIFY_SDK;"
                   "if ($s.Status -eq 'Valid' -and "
                   "$s.SignerCertificate.GetNameInfo('SimpleName',$false) -in "
                   "@('Valve Corp.','Valve Corporation')) {exit 0};exit 1")
        result = windows_powershell(command, environment={"ORIEN_VERIFY_SDK": str(path)}, timeout=45)
        if result.returncode == 0 and _file_hash(path) == digest:
            return digest
    raise ValueError("Steam 运行库未通过 Valve 原件或 Windows 数字签名校验。")


def _same_directory(recorded, actual):
    if not isinstance(recorded, str) or not Path(recorded).is_absolute():
        return False
    try:
        candidate = _check_path(recorded)
        return candidate.samefile(actual)
    except (OSError, ValueError):
        return False


def _owned(destination):
    root = _check_path(destination)
    marker = _check_path(root / MARKER)
    if marker.stat().st_size > MARKER_LIMIT:
        raise ValueError("隔离目录记录无效。")
    info = json.loads(marker.read_text(encoding="utf-8"))
    company = info.get("company", "")
    if (info.get("schema") != 2 or info.get("directoryId") != root.stat().st_ino
            or not _same_directory(info.get("root"), root)
            or not isinstance(company, str) or not re.fullmatch(r"Or16[0-9a-f]{7}", company)):
        raise ValueError("当前目录不属于此回放安装。")
    for file in _tree_files(root):
        if _steam_file(file.name) and file != root / VENDOR:
            raise ValueError(f"隔离目录内出现了 Steam 平台文件：{file}")
    hashes = info.get("payloadSha256", {})
    if (not isinstance(hashes, dict) or file_names_hash(hashes) != info["sourceBuild"]["fileNames"]
            or set(hashes) != set(info["copiedFiles"])):
        raise ValueError("回放副本的文件校验清单无效。")
    for name in hashes:
        member = Path(name)
        if (not member.parts or member.anchor or member.as_posix() != name or ".." in member.parts or ":" in name
                or not (name in ROOT_FILES or member.parts[0] in ROOT_DIRS)):
            raise ValueError("回放文件清单包含越界路径。")
    if (not ROOT_REQUIRED.issubset(hashes) or not {APP_INFO, MANAGERS, VENDOR}.issubset(hashes)
            or hashes[VENDOR] != info.get("vendorSha256") or hashes[MANAGERS] != info.get("managerSha256")):
        raise ValueError("回放运行文件记录不完整。")
    return IsolatedGame(root, root / (GAME + ".exe"), company, _profile(company)), info


def _mutable(info):
    names = {info["titleFile"], AA + "catalog.bin"}
    if info.get("scriptFile"):
        names.add(info["scriptFile"])
    font = info.get("fontFile")
    if font is not None:
        if (not isinstance(font, str) or not MENU_FONT_BUNDLE.fullmatch(Path(font).name)
                or font != AA + "StandaloneWindows64/" + Path(font).name
                or font not in info.get("copiedFiles", [])):
            raise ValueError("回放字体资源记录无效。")
        names.add(font)
    return names


def _mismatches(game, info):
    mutable = _mutable(info)
    for name, digest in info["payloadSha256"].items():
        path = game.root / name
        if not path.is_file() or (name not in mutable and _file_hash(path) != digest):
            yield name


def restore_members(source, game, info, names, fallback=None):
    """Repair regular members from verified official bytes. Never write through an existing file."""
    stock = _gallery_inputs(source, fallback)[0] if set(names) & {info["titleFile"], AA + "catalog.bin"} else {}
    configs = _private_configs(source, game.company)
    for name in names:
        path = _check_path(game.root / name, allow_missing=True)
        if not path.is_relative_to(game.root) or name not in info["payloadSha256"]:
            raise ValueError("回放修复清单包含不安全的路径。")
        expected = info["payloadSha256"][name]
        if path.is_file() and _file_hash(path) == expected:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=game.root.parent, delete=False) as stream:
            tmp = Path(stream.name)
        try:
            if name in configs:
                tmp.write_bytes(configs[name])
            else:
                shutil.copyfile(_check_path(stock.get(name, source / name)), tmp)
            if _file_hash(tmp) != expected:
                raise ValueError(f"当前原版无法核实回放文件 {name}，请在 Steam 中验证游戏文件。")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def verify_copy(destination):
    game, info = _owned(destination)
    damaged = next(_mismatches(game, info), None)
    if damaged:
        raise ValueError(f"隔离目录内的文件缺失或损坏：{damaged}")
    _verify_profile_settings(game)
    return game


def _verify_profile_settings(game):
    manager = (game.root / MANAGERS).read_bytes()
    if (_company_info((game.root / APP_INFO).read_bytes()) != game.company or
            manager.count(game.company.encode()) != 1 or SOURCE_COMPANY.encode() in manager):
        raise ValueError("隔离版存档配置已改变，已取消启动。")


def prepare_copy(source, destination, *, stock_fallback=None, program_inputs=None, script_file=None, font_file=None):
    """Prepare once, then verify and reuse. Never overwrite or adopt an existing unmarked directory."""
    source = _check_path(source)
    destination = _check_path(destination, allow_missing=True)
    if _overlap(source, destination) or _overlap(destination, local_low()):
        raise ValueError("回放目录必须与游戏安装和 Windows 存档目录分开。")
    if stock_fallback is not None:
        stock_fallback = _check_path(stock_fallback)
        if _overlap(stock_fallback, destination):
            raise ValueError("备用原版目录不能与回放目录重叠。")
    sdk = _check_path(source / VENDOR)
    sdk_hash = _vendor_hash(sdk)
    if os.path.lexists(destination):
        game, marker = _owned(destination)
        if (not _same_directory(marker.get("source"), source)
                or marker.get("sourceBuild") != source_stamp(source) or marker.get("scriptFile") != script_file
                or marker.get("fontFile") != font_file):
            raise ValueError("该回放目录对应另一套游戏安装或版本，请选择新的回放目录。")
        damaged = list(_mismatches(game, marker))
        if damaged:
            restore_members(source, game, marker, damaged, stock_fallback)
        _verify_profile_settings(game)
        return game
    stock, expected_hashes, gallery_baseline = _gallery_inputs(source, stock_fallback)
    stamp = source_stamp(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = _check_path(destination.with_name("." + destination.name + ".building"), allow_missing=True)
    paths = {p.relative_to(source).as_posix(): p for p in _source_members(source)}
    title_file, = (name for name in expected_hashes if name.endswith(".bundle"))
    if stage.exists():
        marker_path = _check_path(stage / MARKER)
        if marker_path.stat().st_size > MARKER_LIMIT:
            raise ValueError("回放临时目录的记录过大。")
        saved = json.loads(marker_path.read_bytes())
        company = saved.get("company", "")
        if (saved.get("schema") != 2 or Path(saved.get("root", "")) != destination or
                not _same_directory(saved.get("source"), source) or saved.get("sourceBuild") != stamp or
                saved.get("directoryId") != stage.stat().st_ino or not re.fullmatch(r"Or16[0-9a-f]{7}", company)):
            raise ValueError("回放临时目录的归属无法核实。")
        if any(p.relative_to(stage).as_posix() not in paths and p != stage / MARKER for p in _tree_files(stage)):
            raise ValueError("回放临时目录内有无法核实的文件。")
    else:
        company = _new_company()
    configs = _private_configs(source, company)
    marker = {"schema": 2, "root": str(destination), "source": str(source), "sourceBuild": stamp,
              "company": company, "galleryBaseline": gallery_baseline, "copiedFiles": sorted(paths),
              "programInputs": program_inputs, "scriptFile": script_file, "fontFile": font_file,
              "managerSha256": hashlib.sha256(configs[MANAGERS]).hexdigest(),
              "runtimeHashes": {name: _file_hash(source / name) for name in sorted(ROOT_REQUIRED)},
              "vendorSha256": sdk_hash, "titleFile": title_file, "sourceTitleSha256": expected_hashes[title_file]}
    if not stage.exists():
        # Install the ownership marker before making an interrupted copy visible.
        with tempfile.TemporaryDirectory(dir=stage.parent, prefix=".orien-init-") as tmp:
            initial = Path(tmp) / "payload"
            initial.mkdir()
            marker["directoryId"] = initial.stat().st_ino
            atomic_json(initial / MARKER, marker)
            initial.rename(stage)
    else:
        marker["directoryId"] = stage.stat().st_ino
        atomic_json(stage / MARKER, marker, temp_dir=stage.parent)
    digests = {}
    for name, path in paths.items():
        dest = stage / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if name in configs:
            dest.write_bytes(configs[name])
            digests[name] = hashlib.sha256(configs[name]).hexdigest()
        else:
            original = stock.get(name, path)
            shutil.copyfile(original, dest)
            digests[name] = _file_hash(original)
    for name, expected in expected_hashes.items():
        if _file_hash(stage / name) != expected:
            raise ValueError(f"原版资源复制校验失败：{name}")
    if (legacy_stamp(stage) != legacy_stamp(source) or _file_hash(stage / VENDOR) != sdk_hash
            or source_stamp(source) != stamp):
        raise ValueError("复制期间游戏版本发生变化。")
    if any(_file_hash(stage / name) != digest for name, digest in marker["runtimeHashes"].items()):
        raise ValueError("回放程序复制校验失败。")
    marker["payloadSha256"] = digests
    if any(_file_hash(stage / name) != digest for name, digest in digests.items()):
        raise ValueError("游戏副本未通过逐文件复制校验。")
    atomic_json(stage / MARKER, marker, temp_dir=stage.parent)
    stage.rename(destination)
    return _owned(destination)[0]


def launch_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.casefold().startswith(("steam", "gameoverlay", "enable_vk_layer_valve_steam_overlay"))}
    windows = Path(env.get("SystemRoot") or env.get("SYSTEMROOT") or r"C:\Windows")
    for key in list(env):
        if key.casefold() == "path":
            del env[key]
    env["PATH"] = os.pathsep.join(str(p) for p in (windows / "System32", windows))
    return env
