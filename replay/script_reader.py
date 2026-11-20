"""Read the original Naninovel line table and its serialized byte offsets."""
import re
import struct


LINE_TYPE = re.compile(
    rb'(GenericTextScriptLine|CommandScriptLine|LabelScriptLine|CommentScriptLine|EmptyScriptLine)'
    rb'\x00{0,3}\x09\x00\x00\x00Naninovel\x00{3}\x1a\x00\x00\x00Elringus\.Naninovel\.Runtime\x00\x00'
)
U32 = struct.Struct('<I')


def read_lines(reader):
    raw = reader.get_raw_data()
    name_end = (32 + U32.unpack_from(raw, 28)[0] + 3) & ~3
    count = U32.unpack_from(raw, name_end)[0]
    expected_refs = struct.unpack_from(f'<{count}q', raw, name_end + 4)
    end_table = name_end + 4 + 8 * count
    rows = []
    for match in LINE_TYPE.finditer(raw, end_table):
        index, hash_length = struct.unpack_from('<II', raw, match.end())
        ref_id = struct.unpack_from('<q', raw, match.start() - 12)[0]
        if index >= count or ref_id != expected_refs[index]:
            continue
        hash_start = match.end() + 8
        size_offset = hash_start + ((hash_length + 3) & ~3)
        text_size = U32.unpack_from(raw, size_offset)[0]
        text_start = size_offset + 4
        rows.append([
            index, match[1].decode().removesuffix('ScriptLine'),
            raw[hash_start:hash_start + hash_length].decode('ascii'),
            raw[text_start:text_start + text_size].decode('utf8'), int(reader.byte_start) + text_start,
        ])
    if [row[0] for row in rows] != list(range(count)):
        raise ValueError(f'Could not decode all {count} source lines for {reader.path_id} (read {len(rows)})')
    return rows
