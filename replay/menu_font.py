"""Supply missing replay choice characters from the installed game's own TMP atlas."""
from copy import copy
import gc
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile

import UnityPy
from addressables import bundle_locations
import catalog_crc
from replay.isolation import _check_path
from replay.script_assets import AA, PLATFORM, _crc


class MenuFontUnavailable(ValueError):
    """The installed build does not have the expected, compatible stock font assets."""


CHOICE_FONTS = ("wlcmaru2004emoji SDF", "PixelMplus12-Regular-RASTER")
CHINESE_FONT = "SourceHanSansCN-Medium SDF"
FALLBACK_NAME = "Orien Replay Menu CJK"


def _registered(game, stem):
    base = Path(game) / AA
    names = bundle_locations((base / "catalog.bin").read_bytes())
    found = [n for n in names if re.fullmatch(re.escape(stem) + r"(?:_[A-Za-z0-9-]+)?\.bundle", n, re.I)]
    if len(found) != 1:
        return None
    member = _check_path(base / PLATFORM / found[0], allow_missing=True)
    try:
        return member if stat.S_ISREG(member.stat().st_mode) else None
    except FileNotFoundError:
        return None


def font_bundle(source_game):
    """Return the registered startup font bundle, or None for an unfamiliar layout."""
    return _registered(source_game, "startupuiinitialdependencies_assets_all")


def _font(asset, name):
    found = [obj for obj in asset.objects.values()
             if obj.type.name == "MonoBehaviour" and obj.peek_name() == name]
    if len(found) != 1:
        raise MenuFontUnavailable("原作字库无法唯一定位：" + name)
    return found[0]


def _local(asset, ptr, kind):
    obj = asset.objects.get(ptr["m_PathID"])
    if ptr["m_FileID"] or not obj or obj.type.name != kind:
        raise MenuFontUnavailable("原作字体使用了不兼容的资源引用：" + kind)
    return obj


def _clone(asset, template, row):
    obj = copy(template)
    obj.path_id = max(asset.objects) + 1
    if obj.path_id >= 1 << 63:
        raise MenuFontUnavailable("原作字体资源编号无法分配")
    obj.save_typetree(row)
    asset.objects[obj.path_id] = obj
    return {"m_FileID": 0, "m_PathID": obj.path_id}


def _subset_atlas(donor_asset, font, missing):
    chars = [c for c in font["m_CharacterTable"] if c["m_Unicode"] in missing]
    if {c["m_Unicode"] for c in chars} != missing:
        raise MenuFontUnavailable("原作中文字库缺少目录使用的字形")
    indices = {c["m_GlyphIndex"] for c in chars}
    glyphs = [g for g in font["m_GlyphTable"] if g["m_Index"] in indices]
    if not glyphs or {g["m_Index"] for g in glyphs} != indices:
        raise MenuFontUnavailable("原作中文字表与字形索引不匹配")
    pad = font["m_AtlasPadding"]
    originals = {}
    side = max(max(g["m_GlyphRect"][k] for k in ("m_Width", "m_Height")) for g in glyphs) + 2 * pad
    slots_per_side = math.isqrt(len(glyphs) - 1) + 1
    size = 1 << (side * slots_per_side - 1).bit_length()
    if side <= 0 or pad < 0 or size > 4096:
        raise MenuFontUnavailable("原作目录补充字图的尺寸超出支持范围")
    across = size // side
    pixels = bytearray(size * size)
    for i, glyph in enumerate(glyphs):
        atlas_id = glyph["m_AtlasIndex"]
        if not 0 <= atlas_id < len(font["m_AtlasTextures"]):
            raise MenuFontUnavailable("原作字形引用了不存在的字图")
        if atlas_id not in originals:
            tex = _local(donor_asset, font["m_AtlasTextures"][atlas_id], "Texture2D").read()
            if tex.m_TextureFormat != 1 or tex.m_MipCount != 1:
                raise MenuFontUnavailable("原作中文字图不是单层 Alpha8 纹理")
            originals[atlas_id] = tex.m_Width, tex.m_Height, tex.get_image_data()
        width, height, source = originals[atlas_id]
        r = glyph["m_GlyphRect"]
        x, y, w, h = (r[k] for k in ("m_X", "m_Y", "m_Width", "m_Height"))
        if (len(source) != width * height or w <= 0 or h <= 0 or x < pad or y < pad or
                x + w + pad > width or y + h + pad > height):
            raise MenuFontUnavailable("原作中文字形的边缘或纹理尺寸无法核实")
        dx, dy = i % across * side, i // across * side
        for line in range(h + 2 * pad):
            start = (y - pad + line) * width + x - pad
            out = (dy + line) * size + dx
            pixels[out:out+w+2*pad] = source[start:start+w+2*pad]
        r.update(m_X=dx+pad, m_Y=dy+pad)
        glyph["m_AtlasIndex"] = 0
    font.update(m_GlyphTable=glyphs, m_CharacterTable=chars, m_AtlasWidth=size, m_AtlasHeight=size,
                m_UsedGlyphRects=[], m_FreeGlyphRects=[], m_AtlasTextureIndex=0,
                m_FontFeatureTable={k: [] for k in font["m_FontFeatureTable"]})
    return size, bytes(pixels)


def _preload(asset, parents, additions):
    """Include new local dependencies in each stock preload range containing a patched font."""
    (obj,) = [o for o in asset.objects.values() if o.type.name == "AssetBundle"]
    row = obj.read_typetree()
    table = row["m_PreloadTable"]
    # The same range can serve several names or sub-assets. Keep those aliases together.
    ranges = {}
    for info in [row["m_MainAsset"], *(item for _, item in row["m_Container"])]:
        start, count = info["preloadIndex"], info["preloadSize"]
        key = start, count
        if key not in ranges:
            ptrs = table[start:start+count]
            if start < 0 or count < 0 or len(ptrs) != count:
                raise MenuFontUnavailable("原作字体预载表范围无效")
            if any(not p["m_FileID"] and p["m_PathID"] in parents for p in ptrs):
                deps = [p for p in additions if p not in ptrs]
                ranges[key] = len(table), count + len(deps)
                table.extend([*ptrs, *deps])
            else:
                ranges[key] = key
        info["preloadIndex"], info["preloadSize"] = ranges[key]
    obj.save_typetree(row)


def _supply(asset, donor_asset, parents, missing):
    font = _font(donor_asset, CHINESE_FONT).read_typetree()
    if font["m_AtlasPopulationMode"] or font["m_FallbackFontAssetTable"]:
        raise MenuFontUnavailable("原作中文字库已变更为动态或组合字体")
    size, pixels = _subset_atlas(donor_asset, font, missing)
    template, base = parents[0]
    texture = _local(asset, base["m_AtlasTextures"][0], "Texture2D")
    tx = texture.read_typetree()
    if tx["m_TextureFormat"] != 1 or tx["m_MipCount"] != 1:
        raise MenuFontUnavailable("原作菜单纹理格式不兼容")
    tx.update(m_Name=FALLBACK_NAME + " Atlas", m_Width=size, m_Height=size, m_CompleteImageSize=len(pixels),
              m_StreamData={"offset": 0, "size": 0, "path": ""})
    tx["image data"] = pixels
    tex_ptr = _clone(asset, texture, tx)

    material = _local(asset, base["m_Material"], "Material")
    mat = material.read_typetree()
    props = mat["m_SavedProperties"]
    tex_envs = dict(props["m_TexEnvs"])
    if (base["m_AtlasRenderMode"] != font["m_AtlasRenderMode"] or
            base["m_AtlasPadding"] != font["m_AtlasPadding"] or
            tex_envs["_MainTex"]["m_Texture"] != base["m_AtlasTextures"][0]):
        raise MenuFontUnavailable("原作菜单与中文距离场材质不兼容")
    mat["m_Name"] = FALLBACK_NAME + " Material"
    tex_envs["_MainTex"]["m_Texture"] = tex_ptr
    props["m_Floats"] = [(k, float(size) if k in ("_TextureWidth", "_TextureHeight") else v)
                         for k, v in props["m_Floats"]]
    mat_ptr = _clone(asset, material, mat)
    font.update(m_Name=FALLBACK_NAME, m_Script=base["m_Script"], m_Material=mat_ptr, m_AtlasTextures=[tex_ptr])
    font["m_FaceInfo"]["m_FamilyName"] = FALLBACK_NAME
    # Refuse a future font with additional donor-bundle dependencies such as a source font or weights.
    def check_refs(value):
        if isinstance(value, dict):
            if "m_FileID" in value and value["m_PathID"] and value not in (base["m_Script"], mat_ptr, tex_ptr):
                raise MenuFontUnavailable("原作中文字体包含未支持的依赖")
            for child in value.values():
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)
    check_refs(font)
    font_ptr = _clone(asset, template, font)
    for obj, data in parents:
        data["m_FallbackFontAssetTable"].append(font_ptr)
        obj.save_typetree(data)
    _preload(asset, {o.path_id for o, _ in parents}, [mat["m_Shader"], tex_ptr, mat_ptr, font_ptr])


def patch_menu_font(source_game, isolated_game, edits):
    """Install a local TMP fallback and update just its Addressables record in the private copy."""
    source, target = _check_path(source_game), _check_path(isolated_game)
    if (any(source.samefile(p) for p in (target, *target.parents)) or
            any(target.samefile(p) for p in source.parents)):
        raise ValueError("字体只能写入独立的回放游戏副本")
    original = font_bundle(source)
    if original is None:
        raise MenuFontUnavailable("未找到原作菜单字体资源包")
    out = _check_path(target / original.relative_to(source))
    cat = _check_path(target / AA / "catalog.bin")
    if (any(p.stat().st_nlink != 1 for p in (out, cat)) or out.samefile(original)
            or cat.samefile(source / AA / "catalog.bin")):
        raise ValueError("回放字体包与目录记录必须是独立的副本文件")
    stock_catalog = (source / AA / "catalog.bin").read_bytes()
    before = cat.read_bytes()
    captions = [m[1] for cmd in edits.get("Test2", {}).values() if isinstance(cmd, str)
                and (m := re.match(r'^@choice "([^"\r\n]+)" goto:', cmd.strip()))]
    needed = {ord(c) for text in captions for c in text}
    with tempfile.TemporaryDirectory(prefix=".replay-font-", dir=out.parent) as temp:
        work = Path(temp)
        packed = work / out.name
        with original.open("rb") as stream:
            env = UnityPy.load(stream)
            if len(env.assets) != 1 or not hasattr(env.file, "files"):
                raise MenuFontUnavailable("原作菜单字体资源包的格式无法识别")
            source_crc = _crc(env)
            offset = catalog_crc._record(stock_catalog, original, (source_crc, original.stat().st_size))
            if catalog_crc._record(before, original, struct.unpack_from("<II", before, offset)) != offset:
                raise ValueError("原作与副本的字体包目录记录不匹配")
            try:
                (asset,) = env.assets
                objects = [_font(asset, name) for name in CHOICE_FONTS]
                parents = [(obj, obj.read_typetree()) for obj in objects]
                missing = set().union(*(needed - {v["m_Unicode"] for v in d["m_CharacterTable"]} for _, d in parents))
                if not missing:
                    return {"added": 0, "bundle": original.name}
                donor = _registered(source, "chinesefontgroup_assets_")
                if donor is None:
                    raise MenuFontUnavailable("未找到原作中文字体资源包")
                with donor.open("rb") as donor_stream:
                    chinese = UnityPy.load(donor_stream)
                    (donor_asset,) = chinese.assets
                    _supply(asset, donor_asset, parents, missing)
            except MenuFontUnavailable:
                raise
            except (AttributeError, LookupError, TypeError, ValueError, struct.error) as error:
                raise MenuFontUnavailable("原作字体数据结构与本版不匹配：" + str(error)) from error
            packed.write_bytes(env.file.save("lz4"))
        del env, asset, parents, objects, chinese, donor_asset
        gc.collect()
        with packed.open("rb") as stream:
            reopened = UnityPy.load(stream)
            fallback = _font(reopened.assets[0], FALLBACK_NAME).read_typetree()
            if {v["m_Unicode"] for v in fallback["m_CharacterTable"]} != missing:
                raise ValueError("回放字体写入校验失败")
            crc = _crc(reopened)
        del reopened
        size = packed.stat().st_size
        stored = crc if struct.unpack_from("<I", stock_catalog, offset)[0] else 0
        updated = before[:offset] + struct.pack("<II", stored, size) + before[offset+8:]
        catalog_crc._record(updated, original, (crc, size))
        (work / "catalog.bin").write_bytes(updated)
        shutil.copyfile(out, work / "previous.bundle")
        os.replace(packed, out)
        try:
            os.replace(work / "catalog.bin", cat)
        except BaseException:
            os.replace(work / "previous.bundle", out)
            raise
    return {"bundle": original.name, "added": len(missing), "crc": stored, "size": size}
