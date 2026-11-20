"""Prepare and start the isolated native replay player from the trainer."""
import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
from isolation import launch_environment, prepare_copy, verify_copy


def file_sha(path):
    with path.open("rb") as reader:
        return hashlib.file_digest(reader, "sha256").hexdigest()


def cache_folder(source):
    identity = hashlib.sha256(os.path.normcase(str(source.resolve())).encode())
    build = source / "Annihilated_Data/StreamingAssets/aa/catalog.hash"
    if build.is_file():
        identity.update(build.read_bytes())
    game_id = identity.hexdigest()[:12]
    return Path(os.environ["LOCALAPPDATA"]) / "OrienWorkshop" / "AnnihilatedReplay" / game_id


@contextmanager
def session_lock(folder):
    import msvcrt
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".active").open("a+b") as lock:
        lock.seek(0,2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("回放窗口已开启，或另一份修改器正在准备回放。") from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def prepare(source, destination, index_file, fallback=None):
    from program import make_program
    from replay.private_title import ensure_replay_title, TITLE_FILE
    from scenes import build_catalog
    from dungeon_scenes import add_dungeon_helpers, build_dungeon_scenes
    from script_assets import AA, PLATFORM, _bundle, patch_scripts, read_script_rows
    game = prepare_copy(source, destination, stock_fallback=fallback)
    original = _bundle(source)
    modules = [p for p in HERE.glob("*.py") if not p.name.startswith("test_")]
    stamp = {p.name: file_sha(p) for p in (*modules, index_file, original)}
    receipt = game.root / ".v15-program.json"
    catalog_path = game.root / AA / "catalog.bin"
    installed = game.root / AA / PLATFORM / original.name
    try:
        prior = json.loads(receipt.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, ValueError):
        prior = {}
    if (isinstance(prior,dict) and prior.get("inputs") == stamp and installed.is_file() and
            prior.get("bundleSha") == file_sha(installed) and prior.get("catalogSha") == file_sha(catalog_path)
            and prior.get("titleSha") == file_sha(game.root / TITLE_FILE)):
        return game, prior
    ensure_replay_title(source, game.root)
    gallery = json.loads(index_file.read_text(encoding="utf-8"))
    scripts = read_script_rows(source)
    catalog = build_catalog(scripts, gallery)
    scenes = catalog["scenes"] + build_dungeon_scenes(scripts, gallery)
    edits = make_program(scripts, scenes, catalog["artworks"], gallery["assets"])
    add_dungeon_helpers(edits, scripts)
    outcome = patch_scripts(source, game.root, edits)
    report = {"inputs":stamp, "packed":outcome, "bundleSha":file_sha(installed),
              "catalogSha":file_sha(catalog_path), "titleSha":file_sha(game.root / TITLE_FILE),
              "scenes":2+sum(s["status"] in ("script-reviewed","live-verified") for s in scenes),
              "candidates":sum(s["status"] == "candidate" for s in scenes),
              "artworks":len(catalog["artworks"])}
    tmp = receipt.with_suffix(".tmp")
    tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp, receipt)
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
    source = args.game.resolve()
    cache = (args.cache or cache_folder(source)).resolve()
    if cache == source or cache.is_relative_to(source) or source.is_relative_to(cache):
        raise ValueError("回放数据目录必须独立于原版游戏。")
    with session_lock(cache):
        game, report = prepare(source, cache/"game", args.index, args.stock_fallback)
        if args.prepare_only:
            if sys.stdout:
                print(json.dumps(report, ensure_ascii=True))
            return 0
        command = [str(game.executable), "-logFile", str(cache/"replay-player.log")]
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
        ctypes.windll.user32.MessageBoxW(None, str(error), "原作剧情回放 V1.5", 16)
        sys.exit(1)
