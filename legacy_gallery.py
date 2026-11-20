"""Read a local V1.4 title-gallery record and restore its verified original files."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile


STATE_DIR = ".annihilated-cg-gallery"


PHASES = {"enabling", "enabled", "disabling", "disabled"}


DIGEST = re.compile(r"[0-9a-f]{64}\Z")


VERSION_FILES = (
    "Annihilated.exe", "GameAssembly.dll", "Annihilated_Data/resources.assets",
    "Annihilated_Data/StreamingAssets/aa/catalog.hash",
)


class GalleryError(Exception):
    pass


@contextmanager
def install_lock(game):
    key = hashlib.sha256(os.fsencode(os.path.normcase(str(game)))).hexdigest()
    if os.name != "nt":
        import fcntl
        with open(Path(tempfile.gettempdir()) / ("annihilated-cg-" + key + ".lock"), "ab") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, False, "Global\\Annihilated.CG." + key)
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = kernel.WaitForSingleObject(mutex, 0)
        if result not in (0, 0x80):  # signaled or previous owner exited
            raise GalleryError("另一项画廊操作正在进行，请稍后重新读取。")
        try:
            yield
        finally:
            kernel.ReleaseMutex(mutex)
    finally:
        kernel.CloseHandle(mutex)


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise GalleryError("需要常规文件：" + str(path))
    return path


def plain_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise GalleryError("不支持链接或重解析点目录：" + str(path))


def checked_file(game, path):
    path = Path(path)
    relative = path.relative_to(game)
    if ".." in relative.parts or not relative.parts or relative.parts[0] == STATE_DIR:
        raise GalleryError("画廊文件路径不在受支持的游戏目录内。")
    for parent in relative.parents:
        plain_directory(game / parent)
    return regular(path)


def sha(path):
    with regular(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def version(game):
    result = {}
    for name in VERSION_FILES:
        path = game / name
        result[name] = sha(checked_file(game, path)) if path.exists() else None
    return result


def atomic_json(directory, manifest):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as writer:
        temp = Path(writer.name)
        try:
            json.dump(manifest, writer, ensure_ascii=False, separators=(",", ":"))
            writer.flush()
            os.fsync(writer.fileno())
        except BaseException:
            writer.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, directory / "manifest.json")
    finally:
        temp.unlink(missing_ok=True)


def read_manifest(directory):
    plain_directory(directory)
    path = regular(directory / "manifest.json")
    if path.stat().st_size > 32768:
        raise GalleryError("画廊安装记录过大。")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("phase") not in PHASES:
        raise GalleryError("画廊安装记录损坏或版本不受支持。")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 2 or not isinstance(manifest.get("version"), dict):
        raise GalleryError("画廊安装记录缺少文件信息。")
    for record in files:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise GalleryError("画廊安装记录中的路径无效。")
        for column in ("original", "patched", "previous") if "previous" in record else ("original", "patched"):
            if not isinstance(record.get(column), str) or not DIGEST.fullmatch(record[column]):
                raise GalleryError("画廊安装记录中的校验值无效。")
        if record["original"] == record["patched"]:
            raise GalleryError("画廊安装记录中的文件版本无效。")
    return manifest


def identify(files, manifest):
    states = []
    for path, record in zip(files, manifest["files"]):
        actual = sha(path)
        states.append(next((kind for kind in ("original", "patched", "previous") if record.get(kind) == actual), "unknown"))
    return states


def copy_verified(source, target, expected, game=None, expected_live=None):
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            with regular(source).open("rb") as stream:
                shutil.copyfileobj(stream, output)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        if sha(temp) != expected:
            raise GalleryError("复制画廊文件时校验失败：" + source.name)
        if expected_live is not None and sha(checked_file(game, target)) != expected_live:
            raise GalleryError("目标文件在写入前已变化，已停止操作。")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


AA = Path("Annihilated_Data/StreamingAssets/aa")
TITLE_NAME = re.compile(r"naninovelstartupui_assets_all_[0-9a-f]{32}\.bundle", re.I)
STOCK = ("954fd3c769c749584942e681398df9c203ec44b948f0f93efde90fc8af85517e",
         "a5dfc10364064feeb51d707f1a2fc58b7aeab2d44e2087f4d15cc303fb7a89da")
PUBLISHED_TITLE = "3b144dea62365f0776e6446c446bf80697c9d30c88fdb3820ca7979c6b37a814"
TITLE_PREFAB = "customtitleui.prefab"


def active_targets(game):
    """Get only the two active resources. A manifest cannot choose an arbitrary write target."""
    from addressables import bundle_locations
    catalog = checked_file(game, game / AA / "catalog.bin")
    registered = bundle_locations(catalog.read_bytes())
    folder = catalog.parent / "StandaloneWindows64"
    names = [n for n in registered if TITLE_NAME.fullmatch(n)]
    if len(names) == 1:
        return [checked_file(game, folder / names[0]), catalog]
    # V1.4 also supported a renamed Addressables group via the unique title prefab.
    import gc
    import UnityPy
    matches = []
    for name in names or registered:
        path = checked_file(game, folder / name)
        with path.open("rb") as stream:
            env = UnityPy.load(stream)
            if any(key.rsplit("/", 1)[-1].lower() == TITLE_PREFAB
                   for asset in env.assets for key in asset.container.keys()):
                matches.append(path)
            del env
        gc.collect()
    if len(matches) != 1:
        raise GalleryError("无法唯一定位游戏当前使用的标题资源。")
    return [matches[0], catalog]


def clean_title(game, files, digests):
    if tuple(digests) == STOCK:
        return True
    if digests[0] == PUBLISHED_TITLE:
        return False
    # A fully repaired or updated Steam installation can have a stale backup record.
    # Require both a valid catalog request and the original title controls.
    try:
        import UnityPy
        import catalog_crc
        from title_bindings import validate_stock
        title, catalog = files
        with title.open("rb") as stream:
            env = UnityPy.load(stream)
            if len(env.assets) != 1:
                return False
            validate_stock(env.assets[0], game)
        catalog_crc.locate(catalog.read_bytes(), title)
        return True
    except (ValueError, OSError, TypeError, AttributeError, EOFError, KeyError, IndexError, AssertionError):
        return False


def inspect_pair(game, files, directory):
    digests = [sha(p) for p in files]
    if tuple(digests) == STOCK:
        return "disabled", None
    if not os.path.lexists(directory):
        if clean_title(game, files, digests):
            return "disabled", None
        raise GalleryError("当前标题资源无法核实为原版，找不到 V1.4 的本机安装记录和原版备份。"
                           "可通过 Steam 验证游戏文件完整性来恢复。")
    try:
        manifest = read_manifest(directory)
    except OSError as error:
        raise GalleryError("无法读取 V1.4 的本机安装记录或原版备份。请检查目录权限，或通过 Steam 验证游戏文件完整性。") from error
    rows = manifest["files"]
    expected_paths = [p.relative_to(game).as_posix() for p in files]
    if [r["path"] for r in rows] != expected_paths:
        if clean_title(game, files, digests):
            return "disabled", None
        raise GalleryError("当前游戏使用的标题资源与本机 V1.4 记录不一致，已保留游戏文件。")
    states = [next((s for s in ("original", "patched", "previous") if r.get(s) == d), "unknown")
              for r, d in zip(rows, digests)]
    if states == ["original", "original"]:
        return "disabled", manifest
    if "unknown" in states:
        if clean_title(game, files, digests):
            return "disabled", None
        raise GalleryError("当前资源与原版、已安装及上次升级版本均不匹配，已保留游戏文件。"
                           "可通过 Steam 验证游戏文件完整性来恢复。")
    for i, row in enumerate(rows):
        try:
            valid = sha(directory / f"original-{i}.bin") == row["original"]
        except OSError:
            valid = False
        if not valid:
            raise GalleryError("缺少可验证的原版备份，或备份校验失败。已保留游戏文件。"
                               "请检查本机 V1.4 备份，或通过 Steam 验证游戏文件完整性。")
    return ("enabled" if states == ["patched", "patched"] and manifest["phase"] == "enabled"
            else "recovery"), manifest


def write_pair(game, files, manifest, sources, wanted, guard):
    for i, target in enumerate(files):
        if version(game) != guard:
            raise GalleryError("恢复期间游戏版本已变化，已停止操作。")
        states = identify(files, manifest)
        if "unknown" in states:
            raise GalleryError("恢复期间游戏文件被其他程序修改，已停止操作。")
        actual = manifest["files"][i][states[i]]
        if actual != wanted[i]:
            copy_verified(sources[i], target, wanted[i], game, actual)
    if version(game) != guard or [sha(p) for p in files] != wanted:
        raise GalleryError("操作后的游戏文件校验失败。")


def restore(game, files, directory, manifest):
    guard = version(game)
    with tempfile.TemporaryDirectory(prefix="restore-", dir=directory) as temp:
        temp = Path(temp)
        previous = [temp / f"before-{i}" for i in range(2)]
        before = [sha(p) for p in files]
        for i, row in enumerate(manifest["files"]):
            if before[i] not in [row.get(k) for k in ("original", "patched", "previous")]:
                raise GalleryError("恢复前游戏文件发生变化，已停止操作。")
            copy_verified(files[i], previous[i], before[i])
        if read_manifest(directory) != manifest:
            raise GalleryError("本机安装记录在恢复前发生变化，已停止操作。")
        atomic_json(directory, dict(manifest, phase="disabling"))
        try:
            originals = [directory / f"original-{i}.bin" for i in range(2)]
            wanted = [row["original"] for row in manifest["files"]]
            write_pair(game, files, manifest, originals, wanted, guard)
            atomic_json(directory, dict(manifest, phase="disabled"))
        except Exception as error:
            try:
                write_pair(game, files, manifest, previous, before, guard)
                atomic_json(directory, manifest)
            except Exception as rollback:
                raise GalleryError(f"恢复操作中断：{error}。回退未完成：{rollback}。请重新读取状态。") from rollback
            raise


def execute(verb, game):
    if verb not in ("status", "disable"):
        raise GalleryError("此迁移工具仅支持 status 和 disable。")
    if not game.is_absolute() or ".." in game.parts:
        raise GalleryError("请选择游戏安装目录的绝对路径。")
    for folder in (*reversed(game.parents), game):
        plain_directory(folder)
    game = game.resolve(strict=True)
    checked_file(game, game / "Annihilated.exe")
    with install_lock(game):
        files = active_targets(game)
        directory = game / STATE_DIR
        state, manifest = inspect_pair(game, files, directory)
        if verb == "status":
            if state == "recovery":
                raise GalleryError("RECOVERY_REQUIRED V1.4 画廊处于部分安装状态，可恢复本机原版备份。")
            return state
        if state != "disabled":
            restore(game, files, directory, manifest)
            if inspect_pair(game, files, directory)[0] != "disabled":
                raise GalleryError("恢复后的标题资源未通过最终校验。")
        return "disabled"


def main(args=None):
    args = sys.argv[1:] if args is None else args
    try:
        if len(args) != 2 or args[0] not in ("status", "disable"):
            raise GalleryError("用法：legacy_gallery.py status|disable <游戏目录绝对路径>")
        state = execute(args[0], Path(args[1]))
        print("V1.4 旧画廊已启用。" if state == "enabled" else "V1.4 旧画廊已关闭。")
        return 10 if args[0] == "status" and state == "disabled" else 0
    except Exception as error:
        print(str(error) or type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
