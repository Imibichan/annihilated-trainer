"""Build the gallery on the player's machine from the installed title and dialogue."""
import hashlib
import gc
import json
import re
import sys
import tempfile
from pathlib import Path

REVISION = 4
TITLE_SHA = "954fd3c769c749584942e681398df9c203ec44b948f0f93efde90fc8af85517e"
CATALOG_SHA = "a5dfc10364064feeb51d707f1a2fc58b7aeab2d44e2087f4d15cc303fb7a89da"
CODE = Path(__file__).resolve().parent
STARTUP_NAME = re.compile(r"naninovelstartupui_assets_all_[0-9a-f]{32}\.bundle", re.I)
LEGACY_SOURCE_FINGERPRINT = "2f09db29d61d38cf242c241ea34b12413ec310daa3245fc8c85117e712d26bbe"

if not (CODE / "build_title.py").is_file():
    for module_dir in ("catalog", "title"):
        sys.path.insert(0, str(CODE.parent / module_dir))


def index_file():
    packaged = CODE / "gallery.json"
    return packaged if packaged.is_file() else CODE.parent / "catalog" / "gallery.json"


def targets(game):
    aa = game / "Annihilated_Data" / "StreamingAssets" / "aa"
    catalog = aa / "catalog.bin"
    from addressables import bundle_locations
    registered = bundle_locations(catalog.read_bytes())
    bundles = aa / "StandaloneWindows64"
    names = [name for name in registered if STARTUP_NAME.fullmatch(name)]
    if len(names) == 1:
        return [bundles / names[0], catalog]
    # A renamed Addressables group may still contain the same title prefab.
    import UnityPy
    candidates = names or registered
    matches = []
    for name in sorted(candidates):
        file = bundles / name
        if file.is_file():
            with file.open("rb") as stream:
                env = UnityPy.load(stream)
                if any(Path(key).name.lower() == "customtitleui.prefab" for key in env.container):
                    matches.append(file)
                del env
    if len(matches) != 1:
        raise ValueError("无法从当前资源索引唯一定位游戏标题菜单。")
    return [matches[0], catalog]


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_fingerprint(game):
    """Identify the content actually installed without treating a build label as data."""
    data = game / "Annihilated_Data"
    title, catalog = targets(game)
    from addressables import bundle_locations
    names = bundle_locations(catalog.read_bytes())
    inputs = [title.parent / name for name in names if name.lower() != title.name.lower()]
    inputs.extend(p for p in data.iterdir() if p.is_file() and
                  (p.name.startswith(("resources.", "globalgamemanagers", "sharedassets"))))
    digest = hashlib.sha256()
    for file in sorted(inputs, key=lambda p: p.as_posix().lower()):
        digest.update(file.relative_to(data).as_posix().lower().encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(file_hash(file)) if file.is_file() else b"missing")
    return digest.hexdigest()


def validate_stock(game, *, source_game=None):
    if not (game / "Annihilated.exe").is_file():
        raise ValueError("游戏目录中缺少 Annihilated.exe。")
    bundle, catalog = targets(game)
    resources = game / "Annihilated_Data" / "resources.assets"
    if not resources.is_file():
        raise ValueError("找不到游戏对白资源 resources.assets。")
    title_known = file_hash(bundle) == TITLE_SHA
    if not title_known or file_hash(catalog) != CATALOG_SHA:
        from catalog_crc import locate
        from addressables import address_paths
        blob = catalog.read_bytes()
        try:
            locate(blob, bundle)
        except ValueError as error:
            raise ValueError(f"标题资源与当前索引不匹配，无法启用画廊。{error}") from error
        if not address_paths(blob):
            raise ValueError("当前资源索引中没有可读取的 CG 地址。")
    if not title_known:
        import UnityPy
        import build_title
        with bundle.open("rb") as stream:
            env = UnityPy.load(stream)
            try:
                try:
                    build_title.validate_stock(env, game=source_game or game)
                except ValueError as error:
                    raise ValueError(f"当前标题菜单缺少鉴赏所需的控件或已有冲突。{error}") from error
            finally:
                del env
                gc.collect()


def supported(game, *, source_game=None):
    try:
        validate_stock(game, source_game=source_game)
    except (OSError, ValueError, KeyError, IndexError):
        return False
    return True


def build(game, output_directory, *, source_game=None):
    live_game = game if source_game is None else source_game
    validate_stock(game, source_game=live_game)
    source, catalog = targets(game)
    import UnityPy
    import build_title
    import catalog_ui
    from catalog_crc import replace

    background_index = None
    if file_hash(catalog) == CATALOG_SHA and source_fingerprint(live_game) == LEGACY_SOURCE_FINGERPRINT:
        index = json.loads(index_file().read_text(encoding="utf-8"))
    else:
        from compatible_content import prepare_content
        with tempfile.TemporaryDirectory(prefix="index-", dir=output_directory) as scratch:
            try:
                index, background_index = prepare_content(live_game, catalog, Path(scratch),
                                                         stock_title_path=source, stock_title_name=source.name)
            except (ValueError, FileNotFoundError, KeyError) as error:
                raise ValueError(f"无法从当前游戏重建 CG、场景或简中对白。{error}") from error
    # UnityPy's objects reference their file reader cyclically. Use memory readers
    # so Windows can swap the two checked resources immediately on return.
    env = UnityPy.load(source.read_bytes())
    binding = build_title.validate_stock(env, game=live_game)
    gallery = build_title.Gallery(env, binding=binding)
    del env
    target = output_directory / source.name
    try:
        gallery.prepare()
        # The trusted stock inputs can live in a small staging directory on upgrade.
        # The art renderer reads room textures and sprites from the full installation.
        catalog_ui.build(gallery, index, live_game, background_index=background_index)
        gallery.finish(target)
    finally:
        # The cached template accessor otherwise retains the gallery and its textures.
        gallery.source.cache_clear()
        del gallery
        gc.collect()

    # Decode the on-disk result once for both the prefab check and the Addressables CRC.
    data, _, _, _ = replace(catalog, source, target,
                            validate_modified=lambda env: build_title.validate_modified(env, binding))
    (output_directory / catalog.name).write_bytes(data)
