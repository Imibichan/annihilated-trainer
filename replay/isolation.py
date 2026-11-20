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
import tempfile


GAME = "Annihilated"
DATA = GAME + "_Data"
APP_INFO = DATA + "/app.info"
MANAGERS = DATA + "/globalgamemanagers"
AA = DATA + "/StreamingAssets/aa/"
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
        company = "Or15" + secrets.token_hex(4)[:7]
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


def _source_stamp(source):
    # The game assembly and Addressables hash distinguish the installed game build;
    # a gallery toggle changes neither, so it does not invalidate the private tree.
    return {name: _file_hash(_check_path(source / name)) for name in ("GameAssembly.dll", AA + "catalog.hash")
            if (source / name).exists()}


def _verify_owned(destination, allow_missing_vendor=False):
    root = _check_path(destination)
    marker = _check_path(root / MARKER)
    if marker.stat().st_size > 32768:
        raise ValueError("隔离目录记录无效。")
    info = json.loads(marker.read_text(encoding="utf-8"))
    company = info.get("company", "")
    if (info.get("schema") != 1 or not isinstance(info.get("root"), str) or Path(info["root"]) != root
            or not isinstance(company, str) or not re.fullmatch(r"Or15[0-9a-f]{7}", company)):
        raise ValueError("当前目录不属于此回放安装。")
    for file in _tree_files(root):
        if _steam_file(file.name) and file != root / VENDOR:
            raise ValueError(f"隔离目录内出现了 Steam 平台文件：{file}")
    vendor = root / VENDOR
    if vendor.exists():
        if _file_hash(vendor) != VENDOR_HASH:
            raise ValueError("回放副本里的 Steam 运行库与已核实的 Valve 原件不符。")
    elif not allow_missing_vendor:
        raise ValueError("回放副本缺少原版 Steam 运行库。")
    for name in ROOT_REQUIRED:
        if not (root / name).is_file():
            raise ValueError(f"隔离目录缺少 {name}。")
    if _company_info((root / APP_INFO).read_bytes()) != company or _file_hash(root / MANAGERS) != info.get("managerSha256"):
        raise ValueError("隔离版存档配置已改变，已取消启动。")
    return IsolatedGame(root, root / (GAME + ".exe"), company, _profile(company))


def verify_copy(destination):
    return _verify_owned(destination)


def prepare_copy(source, destination, *, stock_fallback=None):
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
    if _file_hash(sdk) != VENDOR_HASH:
        raise ValueError("游戏的 Steam 运行库与已核实的 Valve 原件不符，请检查游戏安装。")
    if os.path.lexists(destination):
        game = _verify_owned(destination, allow_missing_vendor=True)
        marker = json.loads((destination / MARKER).read_text(encoding="utf-8"))
        if (not isinstance(marker.get("source"), str) or Path(marker["source"]) != source
                or marker.get("sourceBuild") != _source_stamp(source)):
            raise ValueError("该回放目录对应另一套游戏安装或版本，请选择新的回放目录。")
        vendor = destination / VENDOR
        if not vendor.exists():
            parent = _check_path(vendor.parent)
            with tempfile.TemporaryDirectory(prefix=".sdk-", dir=parent) as private:
                temp = Path(private) / vendor.name
                shutil.copyfile(sdk, temp)
                if _file_hash(temp) != VENDOR_HASH:
                    raise ValueError("复制期间 Steam 运行库发生变化。")
                temp.rename(vendor)
            return verify_copy(destination)
        return game
    company = _new_company()
    configs = _private_configs(source, company)
    stock, expected_hashes, gallery_baseline = _gallery_inputs(source, stock_fallback)
    stamp = _source_stamp(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".orien-prepare-", dir=destination.parent) as workspace:
        stage = Path(workspace) / "payload"
        stage.mkdir()
        for path in _source_members(source):
            name = path.relative_to(source).as_posix()
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if name in configs:
                dest.write_bytes(configs[name])
            else:
                shutil.copyfile(stock.get(name, path), dest)
        for name, expected in expected_hashes.items():
            if _file_hash(stage / name) != expected:
                raise ValueError(f"原版资源复制校验失败：{name}")
        if _source_stamp(stage) != stamp or _source_stamp(source) != stamp:
            raise ValueError("复制期间游戏版本发生变化。")
        marker = {"schema": 1, "root": str(destination), "source": str(source), "sourceBuild": stamp,
                  "company": company, "galleryBaseline": gallery_baseline, "managerSha256": _file_hash(stage / MANAGERS)}
        (stage / MARKER).write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        # Windows rename fails when the destination already exists, including concurrent builders.
        stage.rename(destination)
    return verify_copy(destination)


def launch_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.casefold().startswith(("steam", "gameoverlay", "enable_vk_layer_valve_steam_overlay"))}
    windows = Path(env.get("SystemRoot") or env.get("SYSTEMROOT") or r"C:\Windows")
    for key in list(env):
        if key.casefold() == "path":
            del env[key]
    env["PATH"] = os.pathsep.join(str(p) for p in (windows / "System32", windows))
    return env
