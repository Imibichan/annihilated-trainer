"""Read joined address strings from the game's Addressables v2 catalog."""
import struct
from functools import lru_cache

DEFAULT_PREFIXES = ('Naninovel/Backgrounds/MainBackground/CG/', 'Naninovel/Backgrounds/OptionalCGBackground')


def provider_records(binary, suffix):
    uint = struct.Struct('<I')
    pair = struct.Struct('<II')
    length_mask = (1 << 30) - 1
    joined = 1 << 30

    @lru_cache(maxsize=None)
    def node_path(node):
        parts = []
        for _ in range(32):
            string, previous = pair.unpack_from(binary, node)
            count = uint.unpack_from(binary, string - 4)[0]
            if count > 2048 or string + count > len(binary):
                raise ValueError('invalid string length')
            parts.append(binary[string:string + count].decode('utf8'))
            if previous == 0xffffffff:
                return '/'.join(reversed(parts))
            node = previous
        raise ValueError('invalid joined string')

    def read_string(encoded):
        if encoded & joined:
            return node_path(encoded & length_mask)
        count = uint.unpack_from(binary, encoded - 4)[0]
        if count > 4096:
            raise ValueError('invalid direct string')
        return binary[encoded:encoded + count].decode('utf8')

    position = binary.index(uint.pack(len(suffix)) + suffix) + 4
    node = position + len(suffix)
    if node_path(node).split('/')[-1].encode('ascii') != suffix:
        raise ValueError('Unrecognized Addressables provider layout')
    provider = uint.pack(joined | node)
    start = 0
    while (hit := binary.find(provider, start)) >= 0:
        start = hit + len(provider)
        if hit < 8: continue
        try:
            address, location = map(read_string, pair.unpack_from(binary, hit - 8))
        except (ValueError, struct.error, UnicodeError):
            continue
        yield address, location


def bundle_locations(binary):
    """Active local Windows player bundles, as registered by the AssetBundleProvider."""
    result = set()
    prefix = '{UnityEngine.AddressableAssets.Addressables.RuntimePath}/StandaloneWindows64/'
    for address, location in provider_records(binary, b'AssetBundleProvider'):
        location = location.replace('\\', '/')
        if not location.startswith(prefix):
            raise ValueError(f'Unsupported Addressables bundle location {location}')
        name = location[len(prefix):]
        if not name.lower().endswith('.bundle') or '/' in name or ':' in name:
            raise ValueError(f'Unsupported bundle file name {name}')
        if name in result: raise ValueError(f'Duplicate active bundle {name}')
        result.add(name)
    if not result: raise ValueError('No active local Addressables bundles')
    return tuple(sorted(result))


def address_paths(binary, prefixes=DEFAULT_PREFIXES, *, path_suffix=''):
    result = {}
    for address, location in provider_records(binary, b'BundledAssetProvider'):
        if location.startswith('Assets/') and location.endswith(path_suffix) and address.startswith(prefixes):
            if address in result and result[address] != location:
                raise ValueError(f'Ambiguous address: {address}')
            result[address] = location
    return result
