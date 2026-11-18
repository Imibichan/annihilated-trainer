"""Install or restore the two title-gallery data files for Annihilated."""
from contextlib import contextmanager
import hashlib
from inspect import signature
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid


STATE_DIR = ".annihilated-cg-gallery"
LEGACY_PATCH = (
    "a4d0e357f5e22761aafea8e44d846c79c076979dfab90173ca11d08200eefaa8",
    "8473ebaecfe8274ccba71ab31c5880b978971119a99ae715da9696ee5d56ee61",
)
WORK_OWNER = "Annihilated CG Gallery upgrade workspace v1"
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


def source_fingerprint(game, builder):
    fingerprint = getattr(builder, "source_fingerprint", None)
    if fingerprint is None:
        return None
    result = fingerprint(game)
    if not isinstance(result, str) or not DIGEST.fullmatch(result.lower()):
        raise GalleryError("无法核验生成画廊所用的游戏素材。")
    return result.lower()


def inputs_changed(game, manifest, builder):
    recorded = manifest.get("inputs") or getattr(builder, "LEGACY_SOURCE_FINGERPRINT", None)
    try:
        if recorded and hasattr(builder, "source_fingerprint"):
            return source_fingerprint(game, builder) != recorded.lower()
        # Older builders only captured the localization asset and content catalog marker.
        for name in ("Annihilated_Data/resources.assets", "Annihilated_Data/StreamingAssets/aa/catalog.hash"):
            path = game / name
            if manifest["version"].get(name) != (sha(checked_file(game, path)) if path.exists() else None):
                return True
    except Exception:
        # Missing or unreadable source art can prevent a rebuild; the verified
        # installed pair still belongs to the user and can be switched off.
        return True
    return False


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


def set_phase(directory, manifest, phase):
    manifest["phase"] = phase
    atomic_json(directory, manifest)


def revision(value):
    if type(value) is not int or value < 1:
        raise GalleryError("画廊版本号无效。")
    return value


def installed_revision(manifest):
    if "revision" in manifest:
        return revision(manifest["revision"])
    if tuple(record["patched"] for record in manifest["files"]) == LEGACY_PATCH:
        return 1
    return None


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


def require_stock(game, builder, source_game=None):
    validate = getattr(builder, "validate_stock", None)
    check = validate or builder.supported
    kwargs = {"source_game": source_game or game} if "source_game" in signature(check).parameters else {}
    result = check(game, **kwargs)
    if validate is None and not result:
        raise GalleryError("游戏文件与受支持的原版不一致，已保留当前文件和备份。")


def build_pair(builder, stock, output, source_game):
    # Older builders take only the stock inputs and destination. Art-aware builders
    # also need the original installation's read-only scenery and CG resources.
    if "source_game" in signature(builder.build).parameters:
        builder.build(stock, output, source_game=source_game)
    else:
        builder.build(stock, output)


def identify(files, manifest):
    states = []
    for path, record in zip(files, manifest["files"]):
        actual = sha(path)
        states.append(next((kind for kind in ("original", "patched", "previous") if record.get(kind) == actual), "unknown"))
    return states


def inspect(game, files, directory, builder, *, check_updates=True):
    if not os.path.lexists(directory):
        require_stock(game, builder)
        return "disabled", None
    manifest = read_manifest(directory)
    current_paths = [path.relative_to(game).as_posix() for path in files]
    if current_paths != [record["path"] for record in manifest["files"]]:
        require_stock(game, builder)
        return "disabled", manifest
    states = identify(files, manifest)
    if states == ["original", "original"]:
        return "disabled", manifest
    if "unknown" in states:
        require_stock(game, builder)
        return "disabled", manifest
    for i, record in enumerate(manifest["files"]):
        if sha(directory / f"original-{i}.bin") != record["original"]:
            raise GalleryError("原始文件备份校验失败，已保留游戏文件。")
    if states == ["patched", "patched"] and manifest["phase"] == "enabled":
        installed = installed_revision(manifest)
        if check_updates and installed is not None:
            current = revision(getattr(builder, "REVISION", 1))
            if installed < current or (installed == current and inputs_changed(game, manifest, builder)):
                return "update", manifest
        return "enabled", manifest
    return "recovery", manifest


def retire(directory):
    """Remove only the exact known contents of a previous healthy backup; keep unexpected extras."""
    known = {"manifest.json", "original-0.bin", "original-1.bin", "patched-0.bin", "patched-1.bin"}
    upgrade_files = {"previous-0.bin", "previous-1.bin", "next-0.bin", "next-1.bin"}
    try:
        children = list(directory.iterdir())
        names = {child.name for child in children}
        if known <= names <= known | upgrade_files and all(regular(child) for child in children):
            for child in children:
                child.unlink()
            directory.rmdir()
    except (OSError, GalleryError):
        pass


def prepare(game, files, directory, builder):
    require_stock(game, builder)
    identity = version(game)
    inputs = source_fingerprint(game, builder)
    stage = Path(tempfile.mkdtemp(prefix=STATE_DIR + "-prepare-", dir=game))
    archived = None
    try:
        generated = stage / "build"
        generated.mkdir()
        records = []
        for i, path in enumerate(files):
            original = stage / f"original-{i}.bin"
            shutil.copyfile(path, original)
            with original.open("rb+") as backup:
                os.fsync(backup.fileno())
            records.append({"path": path.relative_to(game).as_posix(), "original": sha(original)})
        build_pair(builder, game, generated, game)
        for i, path in enumerate(files):
            output = regular(generated / path.name)
            records[i]["patched"] = sha(output)
            if not output.stat().st_size or records[i]["patched"] == records[i]["original"]:
                raise GalleryError("画廊构建未产生预期的更改：" + path.name)
            with output.open("rb+") as built:
                os.fsync(built.fileno())
            output.rename(stage / f"patched-{i}.bin")
        shutil.rmtree(generated)
        manifest = {"schema": 1, "phase": "enabling", "version": identity, "files": records,
                    "revision": revision(getattr(builder, "REVISION", 1))}
        if inputs is not None:
            manifest["inputs"] = inputs
        if (version(game) != identity or identify(files, manifest) != ["original", "original"]
                or source_fingerprint(game, builder) != inputs):
            raise GalleryError("构建期间游戏文件已改变，已停止安装。")
        require_stock(game, builder)
        atomic_json(stage, manifest)
        if os.path.lexists(directory):
            archived = game / (STATE_DIR + "-previous-" + uuid.uuid4().hex)
            directory.rename(archived)
        try:
            stage.rename(directory)
        except BaseException:
            if archived and not directory.exists():
                archived.rename(directory)
            raise
        if archived:
            retire(archived)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def replace_pair(game, files, directory, manifest, kind, *, expected_version, cache=None):
    for i, target in enumerate(files):
        if version(game) != expected_version:
            raise GalleryError("游戏版本已变化，已停止操作。")
        states = identify(files, manifest)
        if "unknown" in states:
            raise GalleryError("游戏文件在操作期间变化，已停止写入。")
        if manifest["files"][i][states[i]] == manifest["files"][i][kind]:
            continue
        record = manifest["files"][i]
        copy_verified(directory / f"{cache or kind}-{i}.bin", target, record[kind], game, record[states[i]])
    if version(game) != expected_version or any(sha(p) != r[kind] for p, r in zip(files, manifest["files"])):
        raise GalleryError("安装后的游戏文件校验失败。")


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


def remove_workspace(directory):
    work = directory / "upgrade-work"
    if not os.path.lexists(work):
        return True
    plain_directory(work)
    if not any(work.iterdir()):
        work.rmdir()
        return True
    marker = work / "owner.txt"
    if not marker.is_file() or regular(marker).stat().st_size != len(WORK_OWNER) or marker.read_bytes() != WORK_OWNER.encode("ascii"):
        return False
    shutil.rmtree(work)
    return True


@contextmanager
def upgrade_workspace(directory):
    if not remove_workspace(directory):
        raise GalleryError("临时构建目录含有未识别文件，已保留该目录。")
    work = directory / "upgrade-work"
    work.mkdir()
    try:
        (work / "owner.txt").write_bytes(WORK_OWNER.encode("ascii"))
        yield work
    finally:
        remove_workspace(directory)


def clear_upgrade_cache(directory):
    for name in ("next-0.bin", "next-1.bin", "previous-0.bin", "previous-1.bin"):
        try:
            (directory / name).unlink(missing_ok=True)
        except OSError:
            pass


def upgrade(game, files, directory, old, builder):
    identity = version(game)
    inputs = source_fingerprint(game, builder)
    new = {**old, "phase": "enabling", "revision": revision(getattr(builder, "REVISION", 1)),
           "version": identity, "files": []}
    if inputs is not None:
        new["inputs"] = inputs
    # The builder requires stock inputs. Leave both live gallery files in place while it runs.
    with upgrade_workspace(directory) as folder:
        stock, output = folder / "game", folder / "output"
        output.mkdir()
        for i, (target, record) in enumerate(zip(files, old["files"])):
            destination = stock / target.relative_to(game)
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy_verified(directory / f"original-{i}.bin", destination, record["original"])
        for name, expected in identity.items():
            if name not in VERSION_FILES or expected is None:
                continue
            destination = stock / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy_verified(checked_file(game, game / name), destination, expected)
        require_stock(stock, builder, source_game=game)
        build_pair(builder, stock, output, game)
        for i, (target, old_file) in enumerate(zip(files, old["files"])):
            built = regular(output / target.name)
            digest = sha(built)
            if not built.stat().st_size or digest == old_file["original"]:
                raise GalleryError("新版画廊构建未产生有效文件：" + target.name)
            new["files"].append({**old_file, "previous": old_file["patched"], "patched": digest})
        if (inspect(game, files, directory, builder, check_updates=False) != ("enabled", old)
                or version(game) != identity or source_fingerprint(game, builder) != inputs):
            raise GalleryError("构建期间游戏或安装记录已变化，已停止更新。")
        if all(r["patched"] == r["previous"] for r in new["files"]):
            # A source change may not affect these gallery frames. The currently
            # installed bytes already match the independently rebuilt result.
            atomic_json(directory, {**new, "phase": "enabled", "files": old["files"]})
            return
        try:
            for i, (target, record) in enumerate(zip(files, new["files"])):
                copy_verified(target, directory / f"previous-{i}.bin", record["previous"])
                copy_verified(output / target.name, directory / f"next-{i}.bin", record["patched"])
        except Exception:
            clear_upgrade_cache(directory)
            raise
    try:
        atomic_json(directory, new)
    except Exception:
        if read_manifest(directory) == old:
            clear_upgrade_cache(directory)
        raise
    try:
        replace_pair(game, files, directory, new, "patched", expected_version=identity, cache="next")
        for i, record in enumerate(new["files"]):
            copy_verified(directory / f"next-{i}.bin", directory / f"patched-{i}.bin", record["patched"])
        # Keep the original release's manifest and backup layout readable by its disable action.
        committed = {**new, "phase": "enabled", "files": [
            {key: value for key, value in record.items() if key != "previous"} for record in new["files"]
        ]}
        atomic_json(directory, committed)
    except Exception as first:
        try:
            replace_pair(game, files, directory, new, "previous", expected_version=identity)
            for i, record in enumerate(new["files"]):
                copy_verified(directory / f"previous-{i}.bin", directory / f"patched-{i}.bin", record["previous"])
            atomic_json(directory, old)
        except Exception as rollback:
            raise GalleryError(f"画廊更新中断：{first}。回退未完成：{rollback}。请重新读取状态。") from rollback
        raise
    finally:
        # Leave rollback material in place if the process was interrupted or a rollback failed.
        live = read_manifest(directory)
        if live["phase"] == "enabled":
            clear_upgrade_cache(directory)


def transition(game, files, directory, manifest, enable, old_state):
    kind, final = ("patched", "enabled") if enable else ("original", "disabled")
    # Restoring is authorized by exact live and backup hashes; take a new guard
    # for this operation instead of requiring the old executable to be installed.
    guard = manifest["version"] if enable else version(game)
    try:
        set_phase(directory, manifest, "enabling" if enable else "disabling")
        replace_pair(game, files, directory, manifest, kind, expected_version=guard)
        set_phase(directory, manifest, final)
    except Exception as first:
        if old_state in ("disabled", "enabled"):
            try:
                previous_kind = "original" if old_state == "disabled" else "patched"
                replace_pair(game, files, directory, manifest, previous_kind, expected_version=guard)
                set_phase(directory, manifest, old_state)
            except Exception as rollback:
                raise GalleryError(f"操作中断：{first}。回退未完成：{rollback}。请重新读取状态。") from rollback
        raise


def execute(verb, game, builder):
    if not game.is_absolute():
        raise GalleryError("请选择游戏安装目录的绝对路径。")
    game = game.resolve(strict=True)
    checked_file(game, game / "Annihilated.exe")
    plain_directory(game / "Annihilated_Data")
    with install_lock(game):
        files = [checked_file(game, path) for path in builder.targets(game)]
        if len(files) != 2 or len({p.name.casefold() for p in files}) != 2:
            raise GalleryError("无法识别画廊所需的两个游戏文件。")
        directory = game / STATE_DIR
        state, manifest = inspect(game, files, directory, builder, check_updates=verb != "disable")
        if verb == "status":
            if state == "recovery":
                raise GalleryError("RECOVERY_REQUIRED 上次安装中断或游戏仅还原了部分文件，可恢复原始画面。")
            return state
        if verb == "enable" and state == "recovery":
            raise GalleryError("RECOVERY_REQUIRED 请先恢复原始画面，再启用画廊。")
        if verb == "disable" and manifest is not None:
            remove_workspace(directory)
        desired = "enabled" if verb == "enable" else "disabled"
        if state != desired:
            if state == "update" and verb == "enable":
                upgrade(game, files, directory, manifest, builder)
            else:
                if verb == "enable":
                    manifest = prepare(game, files, directory, builder)
                transition(game, files, directory, manifest, verb == "enable", "enabled" if state == "update" else state)
            actual, _ = inspect(game, files, directory, builder)
            if actual != desired:
                raise GalleryError("安装状态核验失败，请重新读取。")
        return desired


def main(args=None, builder=None):
    args = sys.argv[1:] if args is None else args
    try:
        if len(args) != 2 or args[0] not in ("status", "enable", "disable"):
            raise GalleryError("用法：GallerySetup.exe status|enable|disable <游戏目录绝对路径>")
        if builder is None:
            import gallery_builder as builder
        state = execute(args[0], Path(args[1]), builder)
        print({"enabled": "画廊已启用", "disabled": "画廊已关闭", "update": "画廊已启用，有可用更新。"}[state])
        return {"enabled": 0, "disabled": 10, "update": 11}[state] if args[0] == "status" else 0
    except Exception as error:
        print(str(error) or type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
