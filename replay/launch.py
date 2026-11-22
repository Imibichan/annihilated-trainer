"""Prepare and start the isolated native replay player from the trainer."""
import argparse
from contextlib import ExitStack, contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
from replay.isolation import (AA, MARKER, _check_path, _overlap, atomic_json, build_folder_name, launch_environment,
                              local_low, prepare_copy, restore_members, source_stamp, verify_copy)


def file_sha(path):
    with path.open("rb") as reader:
        return hashlib.file_digest(reader, "sha256").hexdigest()


def cache_folder(source):
    identity = hashlib.sha256(os.path.normcase(str(source.resolve())).encode()).hexdigest()[:16]
    return Path(os.environ["LOCALAPPDATA"]) / "OrienWorkshop" / "AnnihilatedReplay" / ("v16-" + identity)


def program_inputs(index_file):
    modules = [p for p in HERE.iterdir() if p.suffix in {".py", ".json"} and not p.name.startswith("test_")]
    return {p.name: file_sha(p) for p in (*modules, index_file)}


def generation(cache, source, index_file):
    return cache / build_folder_name(source_stamp(source), program_inputs(index_file))


def compatibility_report(cache, generation_name, report, *, show):
    """Write the complete local report. Notify the player once per distinct warning set."""
    excluded = report.get("excluded", {})
    presets = [(scene, title, reason) for scene, values in sorted(report.get("excludedPresets", {}).items())
               for title, reason in sorted(values.items())]
    unresolved = report.get("unresolvedArtwork", {})
    preserved = report["migration"]["preserved"]
    font_warning = report.get("fontWarning")
    path = _check_path(cache / "replay-compatibility.txt", allow_missing=True)
    summary = f"当前可播放 {report['scenes']} 段剧情、{report['artworks']} 幅独立画稿。"
    lines = ["原作剧情回放 V1.6.1 兼容性报告", summary, "本次副本目录 " + report["gameRoot"]]
    if excluded:
        lines.extend(["", "本版游戏中未开放的回放入口"] + [f"{key}　{value}" for key, value in sorted(excluded.items())])
    if presets:
        lines.extend(["", "未开放的剧情分支"] + [f"{scene}　{title}　{reason}" for scene, title, reason in presets])
    if unresolved:
        lines.extend(["", "旧画面索引中未定位的条目"] + [f"{key}　{value}" for key, value in sorted(unresolved.items())])
    if font_warning:
        lines.extend(["", "回放目录字体", font_warning])
    if preserved:
        lines.extend(["", "保留在原处的旧回放目录"] + [f"{key}　{value}" for key, value in sorted(preserved)])
    if report["migration"]["removed"]:
        lines.extend(["", "已移除旧版游戏副本"] + report["migration"]["removed"])
    if report["migration"].get("preferencesUnreadable"):
        lines.extend(["", "未能读取下列回放偏好，原有私人存档仍在原处"] +
                     [f"{company}　{reason}" for company, reason in report["migration"]["preferencesUnreadable"]])
    if not excluded and not presets and not preserved:
        lines.extend(["", "所有回放入口均已通过本次兼容性检查。"])
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("回放兼容性报告路径不属于此目录。")
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(("\n".join(lines) + "\n").encode("utf-8-sig"))
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    notify_font = font_warning if report.get("replayLocale") != "zh-CN" else None
    if show and (excluded or presets or preserved or notify_font):
        notice = _check_path(cache / ".v16-notice.json", allow_missing=True)
        signature = hashlib.sha256(json.dumps([generation_name, excluded, presets, sorted(preserved), notify_font],
                                              sort_keys=True).encode()).hexdigest()
        try:
            previous = json.loads(notice.read_bytes()) if notice.stat().st_size < 4096 else {}
        except (FileNotFoundError, ValueError):
            previous = {}
        if previous != {"seen": signature}:
            details = [summary]
            if excluded:
                key, reason = next(iter(sorted(excluded.items())))
                details.append(f"{len(excluded)} 个入口在当前游戏版本下暂时关闭。\n{key}　{reason}")
            if presets:
                scene, title, reason = presets[0]
                details.append(f"{len(presets)} 个剧情分支暂时关闭。\n{scene}　{title}　{reason}")
            if preserved:
                details.append(f"{len(preserved)} 个旧目录已保留。\n{preserved[0][0]}　{preserved[0][1]}")
            if notify_font:
                details.append(notify_font)
            details.append(f"完整说明位于\n{path}\n\n点击确定启动回放。")
            ctypes.windll.user32.MessageBoxW(None, "\n\n".join(details), "原作剧情回放 V1.6.1", 64)
            atomic_json(notice, {"seen": signature})
    return str(path)


@contextmanager
def session_lock(folder):
    import msvcrt
    folder = _check_path(folder, allow_missing=True)
    folder.mkdir(parents=True, exist_ok=True)
    active = _check_path(folder / ".active", allow_missing=True)
    if active.exists() and (not active.is_file() or active.stat().st_nlink != 1):
        raise ValueError("回放进程锁不属于此目录。")
    with active.open("a+b") as lock:
        lock.seek(0,2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("请先关闭所有已开启的回放窗口（包括 V1.5 和 V1.6 系列），并等待其他修改器完成准备。") from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def prepare(source, destination, index_file, fallback=None):
    from addressables import address_paths
    from program import compile_replays
    from replay.menu_font import MenuFontUnavailable, font_bundle, patch_menu_font
    from replay.migration import clean_interrupted_work
    from replay.private_title import ensure_replay_title, title_path
    from script_assets import AA, PLATFORM, _bundle, patch_scripts, read_script_rows
    inputs = program_inputs(index_file)
    original = _bundle(source)
    font = font_bundle(source)
    font_file = font.relative_to(source).as_posix() if font else None
    game = prepare_copy(source, destination, stock_fallback=fallback, program_inputs=inputs,
                        script_file=original.relative_to(source).as_posix(), font_file=font_file)
    stamp = {**inputs, original.name: file_sha(original)}
    if font:
        stamp[font.name] = file_sha(font)
    receipt = game.root / ".v16-program.json"
    marker = json.loads((game.root / MARKER).read_bytes())
    title = title_path(game.root, marker)
    catalog_path = game.root / AA / "catalog.bin"
    installed = game.root / AA / PLATFORM / original.name
    members = [marker["titleFile"], marker["scriptFile"], (AA / "catalog.bin").as_posix()]
    if font_file:
        members.append(font_file)
    clean_interrupted_work(game.root, [Path(name).name for name in members])
    try:
        prior = json.loads(receipt.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, ValueError):
        prior = {}
    if (isinstance(prior,dict) and prior.get("inputs") == stamp and installed.is_file() and
            prior.get("bundleSha") == file_sha(installed) and prior.get("catalogSha") == file_sha(catalog_path)
            and prior.get("titleSha") == file_sha(title)
            and (not font_file or prior.get("fontSha") == file_sha(game.root / font_file))):
        return game, prior
    restore_members(source, game, marker, members, fallback)
    ensure_replay_title(source, game.root)
    gallery = json.loads(index_file.read_text(encoding="utf-8"))
    scripts = read_script_rows(source)
    edits, coverage = compile_replays(scripts, gallery,
                                     artwork_addresses=address_paths((source / AA / "catalog.bin").read_bytes()))
    outcome = patch_scripts(source, game.root, edits)
    font_report = {}
    if font_file:
        try:
            font_report["menuFont"] = patch_menu_font(source, game.root, edits)
        except MenuFontUnavailable as exc:
            font_report["fontWarning"] = "外语模式下部分中文菜单字形可能缺失。" + str(exc)
        font_report["fontSha"] = file_sha(game.root / font_file)
    else:
        font_report["fontWarning"] = "当前游戏未找到回放目录使用的字库，外语模式下部分中文可能显示为方框。"
    report = {"inputs":stamp, "packed":outcome, "bundleSha":file_sha(installed),
              "catalogSha":file_sha(catalog_path), "titleSha":file_sha(title), **font_report, **coverage}
    atomic_json(receipt, report, temp_dir=game.root.parent)
    return verify_copy(destination), report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--index", "--gallery", type=Path, default=HERE.parent/"replay_index.json")
    parser.add_argument("--stock-fallback", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    args = parser.parse_args()
    from replay.language import sync_replay_language
    from replay.migration import check_running_games, legacy_folders, retire_old_games
    source = _check_path(args.game)
    cache = _check_path(args.cache or cache_folder(source), allow_missing=True)
    if _overlap(cache, source) or _overlap(cache, local_low()):
        raise ValueError("回放数据目录必须独立于原版游戏。")
    with ExitStack() as locks:
        locks.enter_context(session_lock(cache))
        # An explicit scratch cache confines legacy discovery to that tree.
        legacy = legacy_folders(source, cache if args.cache else cache.parent)
        for folder in legacy:
            locks.enter_context(session_lock(folder))
        check_running_games(cache, legacy)
        current = generation(cache, source, args.index)
        game, report = prepare(source, current/"game", args.index, args.stock_fallback)
        if generation(cache, source, args.index) != current:
            raise ValueError("准备期间游戏文件发生变化，请重试。")
        locale = sync_replay_language(game)
        migration = retire_old_games(source, cache, game, legacy)
        report = {**report, "gameRoot": str(game.root), "profile": str(game.profile), "migration": migration,
                  "replayLocale": locale}
        report["compatibilityReport"] = compatibility_report(cache, current.name, report, show=not args.prepare_only)
        if args.prepare_only:
            if sys.stdout:
                print(json.dumps(report, ensure_ascii=True))
            return 0
        log = _check_path(cache / "replay-player.log", allow_missing=True)
        if log.exists() and (not log.is_file() or log.stat().st_nlink != 1):
            raise ValueError("回放日志不属于此目录。")
        command = [str(game.executable), "-logFile", str(log)]
        if args.windowed:
            command += ["-screen-fullscreen","0","-screen-width","960","-screen-height","540"]
        result = subprocess.run(command, cwd=game.root, env=launch_environment(), check=False)
        if result.returncode:
            raise RuntimeError(f"回放游戏退出，代码 {result.returncode}。日志位于 {cache/'replay-player.log'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        if sys.stderr:
            raise
        ctypes.windll.user32.MessageBoxW(None, str(error), "原作剧情回放 V1.6.1", 16)
        sys.exit(1)
