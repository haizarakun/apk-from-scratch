"""A minimal resources.arsc writer.

`resources.arsc` is the compiled resource table `aapt` produces. Without it an
app can run, but it has no label and no launcher icon — the manifest's
`android:label` and `android:icon` must point at *resource references*
(`@string/app_name`, `@mipmap/ic_launcher`), and those references resolve
through this table.

This writes a table with one package and the two resource types an installable
app needs: a `string` type holding the app label, and a `mipmap` type holding
the icon, whose value is the path to a packaged PNG. It is intentionally
minimal — one configuration (default), one entry per type — but it is a real,
parseable `ResTable` that `aapt`/androguard read back correctly.

Chunk reference: frameworks/base ResourceTypes.h.
"""
import struct

# Chunk type codes.
RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_TYPE = 0x0002
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC_TYPE = 0x0202

UTF8_FLAG = 0x0100

# Res_value data types.
TYPE_STRING = 0x03
TYPE_REFERENCE = 0x01


def _u8_len(n):
    """ULEB-ish length prefix used by UTF-8 string pool entries: one byte for
    lengths < 128, otherwise two bytes with the high bit of the first set."""
    if n < 0x80:
        return bytes([n])
    return bytes([(n >> 8) | 0x80, n & 0xFF])


def string_pool(strings, utf8=True):
    """Encode a ResStringPool chunk. Returns bytes."""
    count = len(strings)
    data = bytearray()
    offsets = []
    for s in strings:
        offsets.append(len(data))
        if utf8:
            b = s.encode("utf-8")
            # UTF-8 entry: <UTF-16 char-count><byte-count><bytes><NUL>. The
            # first length is in UTF-16 code units (astral chars count twice).
            char_count = sum(1 if ord(c) < 0x10000 else 2 for c in s)
            data += _u8_len(char_count) + _u8_len(len(b)) + b + b"\0"
        else:
            b = s.encode("utf-16-le")
            data += struct.pack("<H", len(s)) + b + b"\0\0"
    while len(data) % 4:
        data += b"\0"

    header_size = 28
    offs_blob = b"".join(struct.pack("<I", o) for o in offsets)
    strings_start = header_size + len(offs_blob)
    chunk_size = strings_start + len(data)
    flags = UTF8_FLAG if utf8 else 0
    header = struct.pack(
        "<HHIIIIII", RES_STRING_POOL_TYPE, header_size, chunk_size,
        count, 0, flags, strings_start, 0)
    return header + offs_blob + bytes(data)


def _res_config(size=64):
    """A default (matches-everything) ResTable_config of the given size."""
    cfg = bytearray(size)
    struct.pack_into("<I", cfg, 0, size)
    return bytes(cfg)


def _type_spec(type_id, entry_count):
    body = b"".join(struct.pack("<I", 0) for _ in range(entry_count))
    header = struct.pack("<HHIBBHI", RES_TABLE_TYPE_SPEC_TYPE, 16,
                         16 + len(body), type_id, 0, 0, entry_count)
    return header + body


def _type_chunk(type_id, entries):
    """entries: list of (key_index, value_type, value_data) or None for a hole.

    Each present entry is a ResTable_entry (size 8, key ref) + Res_value
    (size 8, type, data)."""
    config = _res_config()
    header_size = 20 + len(config)
    count = len(entries)

    entry_blobs = bytearray()
    offsets = []
    for e in entries:
        if e is None:
            offsets.append(0xFFFFFFFF)
            continue
        key_index, vtype, vdata = e
        offsets.append(len(entry_blobs))
        entry_blobs += struct.pack("<HHI", 8, 0, key_index)       # ResTable_entry
        entry_blobs += struct.pack("<HBBI", 8, 0, vtype, vdata)   # Res_value

    offs_blob = b"".join(struct.pack("<I", o) for o in offsets)
    entries_start = header_size + len(offs_blob)
    chunk_size = entries_start + len(entry_blobs)
    header = struct.pack("<HHIBBHII", RES_TABLE_TYPE_TYPE, header_size,
                         chunk_size, type_id, 0, 0, count, entries_start)
    return header + config + offs_blob + bytes(entry_blobs)


def build(package_id, package_name, value_strings, types):
    """Assemble a resources.arsc.

    value_strings: the global value string pool (labels, file paths).
    types: ordered list of dicts:
        {"name": "string", "keys": ["app_name"],
         "entries": [(key_idx, TYPE_STRING, value_str_idx)]}
    Type IDs are assigned 1..N in order.
    """
    type_names = [t["name"] for t in types]
    key_names = []
    for t in types:
        key_names += t["keys"]

    global_pool = string_pool(value_strings)
    type_pool = string_pool(type_names)
    key_pool = string_pool(key_names)

    # Package header is a fixed 288 bytes; the two pools follow it, then the
    # per-type spec and type chunks.
    pkg_header_size = 288
    type_strings_off = pkg_header_size
    key_strings_off = pkg_header_size + len(type_pool)

    # Entries reference their key by position within their own type's `keys`;
    # translate that to the index in the concatenated global key pool.
    chunks = bytearray()
    key_base = 0
    for i, t in enumerate(types, start=1):
        entries = [(key_base + local_key, vtype, vdata)
                   for (local_key, vtype, vdata) in t["entries"]]
        chunks += _type_spec(i, len(entries))
        chunks += _type_chunk(i, entries)
        key_base += len(t["keys"])

    name_utf16 = package_name.encode("utf-16-le")[:254]
    name_field = name_utf16 + b"\0" * (256 - len(name_utf16))
    pkg_body = type_pool + key_pool + bytes(chunks)
    pkg_size = pkg_header_size + len(pkg_body)
    pkg_header = struct.pack(
        "<HHII", RES_TABLE_PACKAGE_TYPE, pkg_header_size, pkg_size, package_id)
    pkg_header += name_field
    pkg_header += struct.pack("<IIII", type_strings_off, 0, key_strings_off, 0)
    # Pad the package header out to its declared size.
    pkg_header += b"\0" * (pkg_header_size - len(pkg_header))
    package = pkg_header + pkg_body

    table_header_size = 12
    table_size = table_header_size + len(global_pool) + len(package)
    table_header = struct.pack("<HHII", RES_TABLE_TYPE, table_header_size,
                               table_size, 1)  # one package
    return table_header + global_pool + package


def res_id(package_id, type_id, entry_id):
    """Compose a resource id: PPTTEEEE (package, type, entry)."""
    return (package_id << 24) | (type_id << 16) | (entry_id & 0xFFFF)
