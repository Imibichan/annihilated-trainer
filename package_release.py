"""Build a V1.6.2 stage or checked release from a player-independent V1.4 toolkit."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import hashlib
import json
import sys
from zipfile import ZipFile, ZIP_DEFLATED


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TRAINER = "勇者小队全灭了修改器-v1.6.2.exe"
SOURCE = "源码"
DOC_NAMES = {"使用说明.txt", "更新说明.txt", "验证记录.txt", "使用说明.md", "更新说明.md", "验证记录.md"}

# UnityPy's serialized object + bundle pipeline, including Brotli/LZMA for
# structurally compatible builds. Texture/sprite export and audio conversion
# are separate optional features. UnityPy imports PIL.Image eagerly even for
# data-only operations, so Pillow's core binary must remain present.
ASSET_PACKAGES = {"UnityPy", "attr", "attrs", "brotli.py", "fsspec", "lz4", "tpk_ar"}
ASSET_DISTRIBUTIONS = {"unitypy", "attrs", "brotli", "fsspec", "lz4", "tpk_ar", "pillow"}
PIL_CORE = {"__init__.py", "_version.py", "Image.py", "ExifTags.py", "ImageMode.py", "TiffTags.py",
            "_binary.py", "_deprecate.py", "_util.py"}


def runtime_file(relative):
    parts = relative.parts
    name = relative.name
    if ("licenses" in (s.lower() for s in parts) or
            name.lower().startswith(("license", "licence", "copying", "notice"))):
        return True
    if parts[0] != "Lib":
        # No SQL, sound playback or Python install-catalog tooling is used by this launcher.
        return name not in {"sqlite3.dll", "_sqlite3.pyd", "winsound.pyd", "python.cat"}
    package = parts[1]
    if package.endswith(".dist-info"):
        distribution = package.split("-", 1)[0].lower()
        return distribution in ASSET_DISTRIBUTIONS and name in {"METADATA", "WHEEL", "entry_points.txt"}
    if relative.suffix.lower() in {".iobj", ".ipdb", ".lib", ".pdb", ".pyi"} or name == "py.typed":
        return False
    if package == "PIL":
        return name in PIL_CORE or name.startswith("_imaging.") and name.endswith(".pyd")
    if package == "UnityPy" and (parts[2] in {"tools", "cli", "export"} or name == "__main__.py"):
        return False
    return package in ASSET_PACKAGES or package.startswith("_brotli.") and package.endswith(".pyd")


def copy_files(source, target, pick):
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        if path.is_file() and "__pycache__" not in rel.parts and path.suffix.lower() != ".pyc" and pick(path):
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)


def build(stage, base, docs):
    if stage.exists() and any(stage.iterdir()):
        raise ValueError(f"请选择不存在或空的构建目录：{stage}")
    stage.mkdir(parents=True, exist_ok=True)
    for file in ("gallery/runtime/python.exe", "gallery/runtime/pythonw.exe", "gallery/runtime/python313._pth",
                 "gallery/code/gallery.json"):
        if not (base / file).is_file():
            raise FileNotFoundError(base / file)
    subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(HERE / "trainer/Build.ps1")], check=True)
    shutil.copyfile(HERE / "trainer/Trainer.exe", stage / TRAINER)
    (stage / "打开剧情回放.cmd").write_text(
        '@echo off\nchcp 65001 >nul\nstart "" "%~dp0' + TRAINER + '" --gallery\n',
        encoding="utf-8", newline="\r\n")
    runtime = base / "gallery/runtime"
    copy_files(runtime, stage / "gallery/runtime", lambda p: runtime_file(p.relative_to(runtime)))
    code = stage / "gallery/code"
    code.mkdir(parents=True, exist_ok=True)
    # Shared readers for the game's catalog and native title resources.
    for name in ("addressables.py", "catalog_crc.py", "title_bindings.py"):
        shutil.copyfile(base / "gallery/code" / name, code / name)
    shutil.copyfile(HERE / "legacy_gallery.py", code / "legacy_gallery.py")
    from replay_index import make_replay_index
    gallery = json.loads((base / "gallery/code/gallery.json").read_bytes())
    (code / "replay_index.json").write_text(
        json.dumps(make_replay_index(gallery), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    replay = HERE / "replay"
    for name in ("launch.py", "isolation.py", "scenes.py", "program.py", "script_assets.py",
                 "hero_replay.py", "mage_replay.py", "warrior_replay.py", "priest_replay.py",
                 "dungeon_scenes.py", "private_title.py", "artwork_scale.py", "script_reader.py",
                 "language.py", "menu_font.py"):
        if not (replay / name).is_file():
            raise FileNotFoundError(replay / name)
    copy_files(replay, stage / "gallery/code/replay", lambda p: p.suffix in {".py", ".json"} and not p.name.startswith("test_"))
    source = stage / SOURCE
    copy_files(HERE / "trainer", source / "trainer", lambda p: p.suffix.lower() in {".cs", ".ico", ".manifest", ".ps1"})
    copy_files(replay, source / "replay", lambda p: p.suffix.lower() in {".py", ".json"})
    copy_files(HERE / "tests", source / "tests", lambda p: p.suffix == ".py")
    for name in ("legacy_gallery.py", "replay_index.py"):
        shutil.copyfile(HERE / name, source / name)
    shutil.copyfile(Path(__file__), source / "package_release.py")
    if docs:
        for path in docs.iterdir():
            if path.name in DOC_NAMES and path.is_file():
                shutil.copyfile(path, stage / path.name)


def archive(folder, target):
    # The archive is verified by re-reading every file and comparing all digests against the staged payload.
    if target.exists():
        raise FileExistsError(f"发布文件已存在，请选择新文件名：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        with path.open("rb") as reader:
            rows[path.relative_to(folder).as_posix()] = hashlib.file_digest(reader, "sha256").hexdigest()
    sums = "".join(f"{value}  {name}\r\n" for name, value in rows.items()).encode("utf-8")
    if "SHA256SUMS.txt" in rows:
        raise ValueError("构建目录内含有旧的 SHA256SUMS.txt。")
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".orien-zip-") as workspace:
        temp = Path(workspace) / "release.zip"
        with ZipFile(temp, "w", ZIP_DEFLATED, compresslevel=6) as packed:
            for name in rows:
                packed.write(folder / name, name)
            packed.writestr("SHA256SUMS.txt", sums)
        rows["SHA256SUMS.txt"] = hashlib.sha256(sums).hexdigest()
        with ZipFile(temp) as packed:
            if packed.namelist() != list(rows):
                raise ValueError("压缩包文件列表不一致。")
            for name, expected in rows.items():
                with packed.open(name) as reader:
                    if hashlib.file_digest(reader, "sha256").hexdigest() != expected:
                        raise ValueError("压缩包回读校验失败：" + name)
        temp.rename(target)
    print(f"{target}: {len(rows)} files, {target.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="original V1.4 toolkit release folder")
    parser.add_argument("--stage", type=Path, help="optional empty staging folder to retain")
    parser.add_argument("--docs", type=Path, help="directory containing V1.6.2 使用说明 / 验证记录 / 更新说明")
    parser.add_argument("--archive", type=Path, help="write verified release ZIP")
    parser.add_argument("--source-archive", type=Path, help="also write a source-only ZIP")
    args = parser.parse_args()
    if not any([args.stage, args.archive, args.source_archive]):
        parser.error("choose --stage, --archive or --source-archive")
    def produce(stage):
        build(stage, args.base.resolve(), args.docs)
        for root, target in ((stage, args.archive), (stage / SOURCE, args.source_archive)):
            if target:
                if target.resolve().is_relative_to(stage.resolve()):
                    raise ValueError("发布压缩包必须位于构建目录之外。")
                archive(root, target.resolve())
    if args.stage:
        produce(args.stage.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="orien-v16-") as workspace:
            produce(Path(workspace))


if __name__ == "__main__":
    main()
