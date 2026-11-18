"""Physical Unity fixtures for structurally matching original and updated title resources."""
from pathlib import Path
import os
import struct
import tempfile
import unittest
from unittest.mock import patch

import UnityPy
import build_title
import catalog_crc

HERE=Path(__file__).resolve().parent
STOCK=Path(os.environ.get("GALLERY_TEST_STOCK_BUNDLE",str(next(HERE.glob("naninovelstartupui*.bundle"),HERE/"missing"))))
CATALOG=Path(os.environ.get("GALLERY_TEST_STOCK_CATALOG",str(HERE.parent/".work/catalog/catalog-stock.bin")))
GAME=Path(os.environ["GALLERY_TEST_GAME"]) if os.environ.get("GALLERY_TEST_GAME") else None


def load():
    return UnityPy.load(STOCK.read_bytes())


def clone_ids(env, change):
    """Rewrite serialized local PPtrs and the actual asset table as a Unity reimport would."""
    af=next(iter(env.file.files.values()))
    def remap(row):
        if isinstance(row,dict):
            if row.get("m_FileID")==0 and row.get("m_PathID") in change:
                row["m_PathID"]=change[row["m_PathID"]]
            else:
                for v in row.values():remap(v)
        elif isinstance(row,(list,tuple)):
            for v in row:remap(v)
    for oid in list(af.objects):
        obj=af.objects[oid]
        row=obj.read_typetree()
        remap(row)
        obj.save_typetree(row)
    af.objects={change.get(oid,oid):obj for oid,obj in af.objects.items()}
    for oid,obj in af.objects.items():obj.path_id=oid
    return UnityPy.load(env.file.save(packer="lz4"))


@unittest.skipUnless(STOCK.is_file(),"provide the stock title bundle to test Unity import")
class StructTitle(unittest.TestCase):
    def test_stock_resolves_actual_components_and_missing_or_patched_rejected(self):
        env=load()
        ids=build_title.validate_stock(env,GAME)
        self.assertEqual(ids.root,4005964447677479671)
        self.assertEqual(ids.entry_driver,6826171850826906359)
        self.assertEqual(ids.raw_image,-5794663642062750546)
        af=env.container[ids.title_path].deref().assets_file
        button=af.objects[ids.entry_button]
        row=button.read_typetree()
        row["m_OnClick"]["m_PersistentCalls"]["m_Calls"]=[build_title.active(ids.root,False)]
        button.save_typetree(row)
        with self.assertRaises(ValueError):build_title.validate_stock(UnityPy.load(env.file.save(packer="lz4")))
        g=build_title.Gallery(load())
        g.prepare()
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/"test.bundle";g.finish(output)
            patched=UnityPy.load(output.read_bytes())
            build_title.validate_modified(patched,g.ids)
            with self.assertRaises(ValueError):build_title.validate_stock(patched)

    def test_renamed_optional_donor_is_identified_in_its_own_prefab(self):
        env=load()
        ids=build_title.validate_stock(env)
        af=env.container[ids.title_path].deref().assets_file
        owner=af.objects[af.objects[ids.mask].read_typetree()["m_GameObject"]["m_PathID"]]
        data=owner.read_typetree()
        data["m_Name"]="UpdatedPortraitMask"
        owner.save_typetree(data)
        updated=UnityPy.load(env.file.save(packer="lz4"))
        self.assertEqual(build_title.validate_stock(updated).mask,ids.mask)

    @unittest.skipUnless(GAME,"set GALLERY_TEST_GAME to test with the installed MonoScript library")
    def test_changed_external_script_ids_are_resolved_by_runtime_assembly_and_class(self):
        from title_bindings import SCRIPTS
        env=load()
        folder=GAME/"Annihilated_Data/StreamingAssets/aa/StandaloneWindows64"
        library_path=next(folder.glob("*monoscripts*.bundle"))
        library=UnityPy.load(library_path.read_bytes())
        cab=next(f for f in library.file.files.values() if hasattr(f,"objects"))
        source=SCRIPTS[("UnityEngine.UI","UnityEngine.UI.RawImage")]
        target=83100000
        obj=cab.objects.pop(source)
        obj.path_id=target
        cab.objects[target]=obj
        af=next(iter(env.file.files.values()))
        for item in af.objects.values():
            if item.type.name!="MonoBehaviour":continue
            data=item.read_typetree()
            if data["m_Script"]["m_PathID"]==source:
                data["m_Script"]["m_PathID"]=target
                item.save_typetree(data)
        updated=UnityPy.load(env.file.save(packer="lz4"))
        with self.assertRaises(ValueError):build_title.validate_stock(updated)
        with tempfile.TemporaryDirectory() as tmp:
            platform=Path(tmp)/"Annihilated_Data/StreamingAssets/aa/StandaloneWindows64"
            platform.mkdir(parents=True)
            (platform/"updated_monoscripts.bundle").write_bytes(library.file.save(packer="lz4"))
            ids=build_title.validate_stock(updated,Path(tmp))
            self.assertEqual(ids.raw_image,-5794663642062750546)

    def test_unrelated_hierarchy_and_ids_reallocated_without_clobbering_existing_nodes(self):
        original=build_title.validate_stock(load())
        ids=original
        known=[ids.root,ids.root_rect,ids.buttons,ids.entry,ids.entry_button,ids.entry_label,ids.entry_text,
               ids.standard_button,ids.graphic,ids.renderer,ids.rect,ids.font_localizer,ids.canvas_group,
               ids.entry_driver,ids.label_driver,ids.raw_image,ids.scroll,ids.mask,ids.fitter,*ids.title_art]
        moved={k:83000001+i for i,k in enumerate(known)}
        env=clone_ids(load(),moved)
        changed=build_title.validate_stock(env)
        self.assertEqual(changed.root,moved[ids.root])
        self.assertEqual(changed.entry,moved[ids.entry])
        self.assertEqual(changed.raw_image,moved[ids.raw_image])
        g=build_title.Gallery(env,binding=changed)
        g.prepare()
        self.assertTrue(set(g.added).isdisjoint(moved.values()))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.bundle";g.finish(path)
            output=UnityPy.load(path.read_bytes())
            build_title.validate_modified(output,changed)
            with self.assertRaises(ValueError):build_title.validate_stock(output)


@unittest.skipUnless(STOCK.is_file() and CATALOG.is_file(),"provide original Addressables catalog and title bundle")
class StructCrc(unittest.TestCase):
    def test_real_options_links_are_required_and_other_crc_occurrences_irrelevant(self):
        blob=CATALOG.read_bytes()
        off=catalog_crc.locate(blob,STOCK)
        self.assertEqual(off,73826)
        duplicate=blob+blob[off:off+8]
        self.assertEqual(catalog_crc.locate(duplicate,STOCK),off)
        damaged=bytearray(blob)
        struct.pack_into("<I",damaged,off+40,0xffffffff)
        with self.assertRaises(ValueError):catalog_crc.locate(damaged,STOCK)

    def test_orphaned_matching_location_is_not_a_catalog_entry(self):
        blob=bytearray(CATALOG.read_bytes())
        table=struct.unpack_from('<I',blob,8)[0]
        # Keep every matching filename, typed request record and correct CRC reachable
        # in the file, but remove the key registrations for all entries.
        struct.pack_into('<I',blob,table-4,0)
        with self.assertRaises(ValueError):catalog_crc.locate(blob,STOCK)

    def test_an_updated_bundle_name_size_hash_and_checksum_are_supported(self):
        blob=CATALOG.read_bytes()
        pos=73826
        old=STOCK.stem.rsplit("_",1)[-1]
        new="9a"*16
        checksum,size=0x12345678,317006
        changed=bytearray(blob.replace(old.encode(),new.encode()).replace(bytes.fromhex(old),bytes.fromhex(new)))
        struct.pack_into("<II",changed,pos,checksum,size)
        with patch.object(catalog_crc,'crc_and_size',return_value=(checksum,size)):
            self.assertEqual(catalog_crc.locate(changed,STOCK.with_name(STOCK.name.replace(old,new))),pos)
        with self.assertRaises(ValueError):catalog_crc.locate(changed,STOCK)

if __name__=="__main__":unittest.main()
