"""Update only the startup asset bundle's local Addressables CRC and byte count."""
import argparse
import gc
import os
from pathlib import Path
import struct
import sys
import zlib


def reader_crc(reader):
    view = getattr(reader, "view", None)
    if view is not None:
        return zlib.crc32(view)
    position = reader.Position
    try:
        reader.Position = 0
        checksum = 0
        while chunk := reader.read(1024 * 1024):
            checksum = zlib.crc32(chunk, checksum)
        return checksum
    finally:
        reader.Position = position


def crc_and_size(bundle, *, validate=None):
    import UnityPy
    with bundle.open("rb") as stream:
        env = UnityPy.load(stream)
        try:
            if len(env.file.files) != 1:
                raise ValueError("Expected the single-CAB startup UI bundle")
            if validate is not None:
                validate(env)
            reader = next(iter(env.file.files.values())).reader
            return reader_crc(reader), os.fstat(stream.fileno()).st_size
        finally:
            # Serialized assets own cyclic references to their environment.
            del env
            gc.collect()


_UINT = struct.Struct("<I")
_OPTIONS = struct.Struct("<5I")
_LOCATION = struct.Struct("<7I")
_PAIR = struct.Struct("<II")
_MAGIC = 0x0DE38942


def _string(blob, offset, separator="."):
    """Decode Addressables v2 direct strings or its linked, shared string segments."""
    if offset == 0xffffffff:
        raise ValueError("Missing catalog string")
    if offset >> 30 == 1:
        node = offset & 0x3fffffff
        segments = []
        for _ in range(32):
            part, node = _PAIR.unpack_from(blob,node)
            if part >> 30:
                raise ValueError("Invalid indirect string segment")
            segments.append(_string(blob,part))
            if node == 0xffffffff:
                return separator.join(reversed(segments))
        raise ValueError("Invalid or cyclic string link")
    if offset < 4 or offset >> 30:
        raise ValueError("Unknown catalog string encoding")
    size = _UINT.unpack_from(blob,offset-4)[0]
    if size>4096 or offset+size>len(blob):
        raise ValueError("Invalid catalog string length")
    return bytes(blob[offset:offset+size]).decode("utf8")


def _locations(blob, name):
    """Follow the binary catalog key table to the indices registered for this exact name."""
    table=_UINT.unpack_from(blob,8)[0]
    if table<4 or table>len(blob):raise ValueError("Invalid catalog key table")
    size=_UINT.unpack_from(blob,table-4)[0]
    if size%8 or table+size>len(blob):raise ValueError("Invalid key table length")
    result=set()
    for key,indices in _PAIR.iter_unpack(memoryview(blob)[table:table+size]):
        try:
            desc,data=_PAIR.unpack_from(blob,key)
            _,key_type=_PAIR.unpack_from(blob,desc)
            if _string(blob,key_type)!="System.String":continue
            string,separator=_PAIR.unpack_from(blob,data)
            if separator>0xffff or _string(blob,string,chr(separator))!=name:continue
            count=_UINT.unpack_from(blob,indices-4)[0]
            if count%4 or indices+count>len(blob):raise ValueError("Invalid location array")
            result.update(n[0] for n in _UINT.iter_unpack(memoryview(blob)[indices:indices+count]))
        except (struct.error,UnicodeError,ValueError):
            continue
    return result


def _record(blob, original, crc_size):
    if len(blob)<36 or _PAIR.unpack_from(blob)!=(_MAGIC,2):
        raise ValueError("Unrecognized Addressables binary catalog format")
    matches=set()
    for item in _locations(blob,original.name):
        try:
            primary,internal,provider,_,_,extra,res_type=_LOCATION.unpack_from(blob,item)
            location=_string(blob,internal).replace(chr(92),"/")
            if _string(blob,primary)!=original.name or location.rsplit("/",1)[-1]!=original.name:continue
            if _string(blob,provider)!="UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider":continue
            assembly,klass=_PAIR.unpack_from(blob,res_type)
            if _string(blob,klass)!="UnityEngine.ResourceManagement.ResourceProviders.IAssetBundleResource":continue
            type_info,options=_PAIR.unpack_from(blob,extra)
            option_assembly,option_class=_PAIR.unpack_from(blob,type_info)
            if assembly!=option_assembly or _string(blob,option_class)!="UnityEngine.ResourceManagement.ResourceProviders.AssetBundleRequestOptions":continue
            hash_pos,bundle_name,crc,size,common=_OPTIONS.unpack_from(blob,options)
            if not _string(blob,bundle_name) or hash_pos+16>len(blob) or common+8>len(blob):continue
            matches.add((options+8,crc,size))
        except (struct.error,UnicodeError,ValueError):
            continue
    if len(matches)!=1:
        raise ValueError("Expected one typed AssetBundleProvider request for the title bundle")
    offset,crc,size=matches.pop()
    checksum,file_size=crc_size
    if crc not in (0,checksum) or size!=file_size:
        raise ValueError("The title bundle bytes differ from their registered CRC or size")
    return offset


def locate(blob, original):
    """Locate the stock CRC/size by its typed Addressables location and installed bytes."""
    return _record(blob,original,crc_and_size(original))


def replace(catalog, original, modified, *, validate_modified=None):
    blob=catalog.read_bytes()
    cursor=locate(blob,original)
    checksum,size=crc_and_size(modified,validate=validate_modified)
    if not _UINT.unpack_from(blob,cursor)[0]:
        checksum=0
    return blob[:cursor]+_PAIR.pack(checksum,size)+blob[cursor+8:],cursor,checksum,size


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("catalog","original","modified","output"):
        p.add_argument(name,type=Path)
    p.add_argument("--unitypy",type=Path)
    a=p.parse_args()
    if a.output.resolve() in (a.catalog.resolve(),a.original.resolve(),a.modified.resolve()):
        p.error("Use a separate output file")
    if a.unitypy:
        sys.path.insert(0,str(a.unitypy.resolve()))
    result,offset,checksum,size=replace(a.catalog,a.original,a.modified)
    a.output.write_bytes(result)
    print(f"Offset {offset}, CRC 0x{checksum:08x}, bundle size {size}")
