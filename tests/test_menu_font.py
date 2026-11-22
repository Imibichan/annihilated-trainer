"""Native fixture checks. Set V16_GAME to a read-only game installation."""
import hashlib
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("V16_GAME"), "requires installed game and gallery support runtime")
class MenuFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from replay import menu_font
        cls.font = menu_font
        cls.source = Path(os.environ["V16_GAME"])
        cls.original = menu_font.font_bundle(cls.source)
        cls.catalog = cls.source / menu_font.AA / "catalog.bin"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.target = Path(temp.name)
        self.bundle = self.target / self.original.relative_to(self.source)
        self.copy_catalog = self.target / self.catalog.relative_to(self.source)
        self.bundle.parent.mkdir(parents=True)
        shutil.copyfile(self.original, self.bundle)
        shutil.copyfile(self.catalog, self.copy_catalog)

    def install(self, caption):
        return self.font.patch_menu_font(self.source, self.target, {
            "Test2": {0: f'@choice "{caption}" goto:.Home'},
            "Opening": {0: '@choice "无关文字" goto:.Start'},
        })

    def fingerprints(self):
        return tuple(hashlib.sha256(p.read_bytes()).digest() for p in (self.bundle, self.copy_catalog))

    def test_only_missing_characters_get_original_pixels_and_existing_font_data_is_preserved(self):
        outcome = self.install("魔法师战士僧侣")
        self.assertEqual(outcome["added"], 3)
        with self.bundle.open("rb") as f, self.original.open("rb") as stock:
            original = self.font.UnityPy.load(stock).assets[0]
            asset = self.font.UnityPy.load(f).assets[0]
            objects = list(asset.objects.values())
            fallback = next(o for o in objects if o.type.name == "MonoBehaviour" and
                            o.peek_name() == "Orien Replay Menu CJK")
            row = fallback.read_typetree()
            self.assertEqual({c["m_Unicode"] for c in row["m_CharacterTable"]}, set(map(ord, "师战侣")))
            for name in ("wlcmaru2004emoji SDF", "PixelMplus12-Regular-RASTER"):
                parent = next(o for o in objects if o.type.name == "MonoBehaviour" and o.peek_name() == name)
                data = parent.read_typetree()
                self.assertEqual(data["m_FallbackFontAssetTable"].pop(), {"m_FileID": 0, "m_PathID": fallback.path_id})
                self.assertEqual(data, original.objects[parent.path_id].read_typetree())
            material = asset.objects[row["m_Material"]["m_PathID"]].read_typetree()
            self.assertEqual(dict(material["m_SavedProperties"]["m_TexEnvs"])["_MainTex"]["m_Texture"],
                             row["m_AtlasTextures"][0])
            texture = asset.objects[row["m_AtlasTextures"][0]["m_PathID"]].read()
            pixels = texture.get_image_data()
            donor_bundle = self.font._registered(self.source, "chinesefontgroup_assets_")
            with donor_bundle.open("rb") as donor_file:
                donor = self.font.UnityPy.load(donor_file).assets[0]
                native = self.font._font(donor, "SourceHanSansCN-Medium SDF").read_typetree()
                glyphs = {g["m_Index"]: g for g in native["m_GlyphTable"]}
                for g in row["m_GlyphTable"]:
                    old = glyphs[g["m_Index"]]
                    self.assertEqual(g["m_Metrics"], old["m_Metrics"])
                    tex = donor.objects[native["m_AtlasTextures"][old["m_AtlasIndex"]]["m_PathID"]].read()
                    src = tex.get_image_data()
                    rect, before = g["m_GlyphRect"], old["m_GlyphRect"]
                    pad = row["m_AtlasPadding"]
                    width = before["m_Width"] + 2 * pad
                    for line in range(-pad, before["m_Height"] + pad):
                        a = (before["m_Y"] + line) * tex.m_Width + before["m_X"] - pad
                        b = (rect["m_Y"] + line) * texture.m_Width + rect["m_X"] - pad
                        self.assertEqual(pixels[b:b+width], src[a:a+width])
        previous, updated = self.catalog.read_bytes(), self.copy_catalog.read_bytes()
        offset = self.font.catalog_crc._record(updated, self.original, (outcome["crc"], outcome["size"]))
        self.assertEqual(previous[:offset] + previous[offset+8:], updated[:offset] + updated[offset+8:])
        self.assertEqual(struct.unpack_from("<II", updated, offset), (outcome["crc"], self.bundle.stat().st_size))

    def test_no_rebuild_for_covered_captions_and_unrelated_story_choices(self):
        before = self.fingerprints()
        self.assertEqual(self.install("魔法")["added"], 0)
        self.assertEqual(before, self.fingerprints())

    def test_missing_stock_glyph_preserves_both_files_and_reports_compatibility(self):
        before = self.fingerprints()
        with self.assertRaises(self.font.MenuFontUnavailable):
            self.install(chr(0x10FFFF))
        self.assertEqual(before, self.fingerprints())

    def test_registered_but_absent_bundle_uses_the_compatibility_path(self):
        unavailable = self.target / "other game"
        catalog = unavailable / self.font.AA / "catalog.bin"
        catalog.parent.mkdir(parents=True)
        shutil.copyfile(self.catalog, catalog)
        self.assertIsNone(self.font.font_bundle(unavailable))

    def test_source_alias_and_shared_destination_files_are_rejected_before_writing(self):
        with self.assertRaisesRegex(ValueError, "独立"):
            self.font.patch_menu_font(self.target, self.target / ".." / self.target.name, {})
        before = self.fingerprints()
        alias = self.bundle.with_name("shared.bundle")
        os.link(self.bundle, alias)
        with self.assertRaisesRegex(ValueError, "独立"):
            self.install("师")
        self.assertEqual(before, self.fingerprints())
        self.assertTrue(alias.samefile(self.bundle))

    def test_failed_catalog_install_restores_the_entire_original_pair(self):
        before = self.fingerprints()
        replace = os.replace
        def fail_catalog(source, target):
            if target == self.copy_catalog:
                raise PermissionError("catalog is locked")
            replace(source, target)
        with patch.object(self.font.os, "replace", side_effect=fail_catalog):
            with self.assertRaises(PermissionError):
                self.install("师")
        self.assertEqual(before, self.fingerprints())
        self.assertFalse(list(self.bundle.parent.glob(".replay-font-*")))
