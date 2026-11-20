"""Keep the stock title controller alive without its modal UI in the replay copy."""
import gc
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

import UnityPy
import catalog_crc
from title_bindings import Prefab
from .isolation import MARKER, STOCK_HASHES, V14_HASHES, verify_copy


TITLE_FILE, = [name for name in STOCK_HASHES if name.endswith(".bundle")]
AA = Path("Annihilated_Data/StreamingAssets/aa")
NULL = {"m_FileID": 0, "m_PathID": 0}
# Measured from the same two baseline files verified by prepare_copy. Recovery
# is allowed only if the current, structurally complete replay title is paired
# with a typed catalog request that still matches one of those originals.
BASELINE_RECORDS = {"stock": (1808649900, 316599), "published-v1.4": (742555541, 102187987)}


def _changes(env, game):
    assets = env.assets
    if len(assets) != 1:
        raise ValueError("无法唯一定位标题资源文件。")
    view = Prefab(assets[0], game)
    if view.row(view.root)["m_Name"] != "CustomTitleUI" or not view.row(view.root)["m_IsActive"]:
        raise ValueError("回放副本的原版 TitleUI 根节点不匹配。")
    children = {view.row(go)["m_Name"]: go for go in view.children(view.root)}
    core = {"TitleImageRight", "TitleImageLeft", "Logo", "Text (TMP)", "ButtonsPanel", "EngineVersionText"}
    if set(children) not in (core, core | {"MemoryGallery"}):
        raise ValueError(f"回放副本的标题层级与原版不同：{sorted(children)}")
    def component(kind, **values):
        oid = view.component(view.root, kind, tuple(values))
        return oid, values
    targets = [
        # Keep TitleMenu enabled so native title-entry/exit code and Title.nani still run.
        component(("Elringus.Naninovel.Runtime", "Naninovel.UI.TitleMenu"),
                  disableInteraction=1, blockInputWhenVisible=0, modalUI=0,
                  controlOpacity=0, focusMode=0, focusObject=NULL),
        component("Canvas", m_Enabled=0),
        component("CanvasGroup", m_Alpha=0.0, m_Interactable=False, m_BlocksRaycasts=False),
        component(("UnityEngine.UI", "UnityEngine.UI.GraphicRaycaster"), m_Enabled=0),
        # This component re-enables the character illustrations when the native title opens.
        component(("Assembly-CSharp", "CustomVariableExpressionTrigger"), m_Enabled=0),
        component(("Assembly-CSharp", "TitleCameraHandheldImpulse"), m_Enabled=0),
    ]
    targets.extend((go, {"m_IsActive": False}) for go in children.values())
    result = {}
    for oid, adjustments in targets:
        original = view.row(oid)
        if any(original[key] != value for key, value in adjustments.items()):
            result[oid] = {**original, **adjustments}
    return view.file, result


def ensure_replay_title(source_game, isolated_game):
    """Idempotently hide only the private stock title, retaining the current catalog.

    A clean title bundle was resolved by prepare_copy, including while v1.4
    is active on Steam. This function reads no source game assets.
    """
    source = Path(source_game).resolve()
    game = verify_copy(isolated_game).root
    marker = json.loads((game / MARKER).read_bytes())
    if source != Path(marker["source"]) or source == game or source in game.parents or game in source.parents:
        raise ValueError("回放副本与安装来源不匹配。")
    bundle = game / TITLE_FILE
    catalog = game / AA / "catalog.bin"
    before = catalog.read_bytes()
    raw = bundle.read_bytes()
    env = UnityPy.load(raw)
    serialized, changes = _changes(env, game)
    if not changes:
        crc, size = catalog_crc.reader_crc(serialized.reader), len(raw)
        try:
            cursor = catalog_crc._record(before, bundle, (crc, size))
        except ValueError:
            baseline = BASELINE_RECORDS[marker.get("galleryBaseline", "stock")]
            cursor = catalog_crc._record(before, bundle, baseline)
            recovered = before[:cursor] + struct.pack("<II", crc, size) + before[cursor+8:]
            with tempfile.TemporaryDirectory(prefix=".replay-title-record-", dir=catalog.parent) as temp:
                fresh = Path(temp) / "catalog.bin"
                fresh.write_bytes(recovered)
                os.replace(fresh, catalog)
            return {"changed": True, "crc": crc, "size": size, "bundle": bundle.name}
        stored_crc, _ = struct.unpack_from("<II", before, cursor)
        return {"changed": False, "crc": stored_crc, "size": size, "bundle": bundle.name}
    if hashlib.sha256(raw).hexdigest() not in (STOCK_HASHES[TITLE_FILE], V14_HASHES[TITLE_FILE]):
        raise ValueError("标题资源并非可验证的原版或已完成的回放副本。")
    for oid, row in changes.items():
        serialized.objects[oid].save_typetree(row)
    with tempfile.TemporaryDirectory(prefix=".replay-title-", dir=bundle.parent) as temp:
        stage = Path(temp)
        packed = stage / bundle.name
        packed.write_bytes(env.file.save("lz4"))
        old_bundle = stage / "previous.bundle"
        old_bundle.write_bytes(raw)
        del env, serialized, raw, changes
        gc.collect()
        def verify(reopened):
            _, missing = _changes(reopened, game)
            if missing:
                raise ValueError("回放标题资源写回后未通过校验。")
        blob, _, crc, size = catalog_crc.replace(catalog, bundle, packed, validate_modified=verify)
        new_catalog = stage / "catalog.bin"
        new_catalog.write_bytes(blob)
        try:
            os.replace(packed, bundle)
            os.replace(new_catalog, catalog)
        except BaseException:
            os.replace(old_bundle, bundle)
            raise
    return {"changed": True, "crc": crc, "size": size, "bundle": bundle.name}
