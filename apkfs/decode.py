"""Decoders — the read side of the toolkit.

The encoders in this project write the binary formats an APK is made of; these
functions read them back. Having both directions makes the repo a complete,
auditable reference: a format you can both emit and parse is one you actually
understand, and an encode -> decode round-trip is a correctness check that
needs no external tooling.

Covered here:
  - decode_axml:   binary AndroidManifest.xml -> XML text
  - read_arsc:     resources.arsc -> {package: {type: {entry: value}}}
  - dex_summary:   classes.dex -> classes, fields, methods
"""
import struct

ANDROID_NS = "http://schemas.android.com/apk/res/android"


# --- string pools (both AXML and arsc use the same chunk layout) ----------

class MalformedError(ValueError):
    """Raised when input does not parse as the expected format. Readers operate
    on untrusted APKs, so they fail with this rather than crashing."""


def _need(data, off, n):
    """Ensure n bytes are readable at off; return off. Bounds every read so a
    truncated or hostile file raises cleanly instead of IndexError/struct."""
    if off < 0 or off + n > len(data):
        raise MalformedError(f"read of {n} bytes at {off} is out of bounds")
    return off


def _read_string_pool(data, off):
    """Parse a ResStringPool chunk at `off`. Returns (strings, next_off)."""
    _need(data, off, 28)
    (_type, header_size, size, count, style_count, flags,
     strings_start, _styles_start) = struct.unpack_from("<HHIIIIII", data, off)
    utf8 = bool(flags & 0x0100)
    # A count can be huge in a hostile file; it cannot exceed the bytes that
    # could hold that many 4-byte offsets.
    if count > (len(data) - off) // 4:
        raise MalformedError("string pool count exceeds file size")
    offsets = [struct.unpack_from(
        "<I", data, _need(data, off + header_size + 4 * i, 4))[0]
        for i in range(count)]
    base = off + strings_start
    out = []
    for o in offsets:
        p = base + o
        if utf8:
            # <char-count><byte-count><bytes>; each length is 1 or 2 bytes.
            _, p = _read_u8_len(data, p)          # skip the char count
            byte_len, p = _read_u8_len(data, p)
            out.append(data[p:p + byte_len].decode("utf-8"))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            p += 2
            out.append(data[p:p + n * 2].decode("utf-16-le"))
    return out, off + size


def _read_u8_len(data, p):
    first = data[p]
    if first & 0x80:
        return ((first & 0x7F) << 8) | data[p + 1], p + 2
    return first, p + 1


def mutf8_decode(b):
    """Decode Modified UTF-8 (as used by DEX) into a Python string.

    Handles the C0 80 encoding of U+0000 and CESU-8 surrogate pairs for astral
    characters, recombining surrogates into a single code point.
    """
    out = []
    i = 0
    n = len(b)
    while i < n:
        c = b[i]
        if c < 0x80:
            out.append(c)
            i += 1
        elif c & 0xE0 == 0xC0:
            if i + 1 >= n:
                raise MalformedError("truncated MUTF-8 2-byte sequence")
            out.append(((c & 0x1F) << 6) | (b[i + 1] & 0x3F))
            i += 2
        else:  # 3-byte form (BMP or one half of a surrogate pair)
            if i + 2 >= n:
                raise MalformedError("truncated MUTF-8 3-byte sequence")
            cp = ((c & 0x0F) << 12) | ((b[i + 1] & 0x3F) << 6) | (b[i + 2] & 0x3F)
            i += 3
            if 0xD800 <= cp <= 0xDBFF and i + 2 < n:
                lo = ((b[i] & 0x0F) << 12) | ((b[i + 1] & 0x3F) << 6) | (b[i + 2] & 0x3F)
                if 0xDC00 <= lo <= 0xDFFF:
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                    i += 3
            out.append(cp)
    return "".join(chr(c) for c in out)


# --- AXML -----------------------------------------------------------------

def decode_axml(data):
    """Decode binary AndroidManifest.xml (AXML) back into XML text."""
    _need(data, 0, 8)
    if struct.unpack_from("<H", data, 0)[0] != 0x0003:
        raise MalformedError("not an AXML file")
    pos = 8  # skip the XML file header
    strings = []
    lines = []
    indent = 0

    def s(i):
        return strings[i] if 0 <= i < len(strings) else ""

    while pos + 8 <= len(data):
        ctype, header_size, size = struct.unpack_from("<HHI", data, pos)
        if size < 8 or pos + size > len(data):
            raise MalformedError("chunk size out of range")
        if ctype == 0x0001:                      # string pool
            strings, _ = _read_string_pool(data, pos)
        elif ctype == 0x0102:                    # start element
            name = struct.unpack_from("<I", data, pos + 20)[0]
            attr_count = struct.unpack_from("<H", data, pos + 28)[0]
            attrs = []
            ap = pos + 36
            for _ in range(attr_count):
                ns_i, name_i, raw_i = struct.unpack_from("<III", data, ap)
                dtype = data[ap + 15]
                value = struct.unpack_from("<I", data, ap + 16)[0]
                key = s(name_i)
                if ns_i != 0xFFFFFFFF:
                    key = "android:" + key
                attrs.append(f'{key}="{_fmt_value(dtype, value, raw_i, s)}"')
                ap += 20
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            lines.append("  " * indent + f"<{s(name)}{attr_str}>")
            indent += 1
        elif ctype == 0x0103:                    # end element
            indent -= 1
            name = struct.unpack_from("<I", data, pos + 20)[0]
            lines.append("  " * indent + f"</{s(name)}>")
        pos += size
    return "\n".join(lines)


def _fmt_value(dtype, data_val, raw_i, s):
    if dtype == 0x03:                            # string
        return s(raw_i)
    if dtype == 0x12:                            # boolean
        return "true" if data_val else "false"
    if dtype == 0x01:                            # reference
        return f"@0x{data_val:08x}"
    if dtype == 0x10:                            # int
        return str(data_val if data_val < 0x80000000 else data_val - (1 << 32))
    return f"0x{data_val:08x}"


# --- resources.arsc -------------------------------------------------------

def read_arsc(data):
    """Parse resources.arsc into {package_name: {type_name: {entry: value}}}.

    String values resolve to their text; references and other typed values are
    rendered the way _fmt_value renders them.
    """
    _need(data, 0, 12)
    if struct.unpack_from("<H", data, 0)[0] != 0x0002:
        raise MalformedError("not a resource table")
    (_t, header_size, _size, _pkg_count) = struct.unpack_from("<HHII", data, 0)
    value_pool, pos = _read_string_pool(data, header_size)

    result = {}
    while pos + 8 <= len(data):
        ctype, h_size, size = struct.unpack_from("<HHI", data, pos)
        if size < 8 or pos + size > len(data):
            raise MalformedError("chunk size out of range")
        if ctype == 0x0200:                      # package
            _parse_package(data, pos, size, value_pool, result)
        pos += size
    return result


def _parse_package(data, off, size, value_pool, result):
    pkg_id = struct.unpack_from("<I", data, off + 8)[0]
    name = data[off + 12:off + 12 + 256].decode("utf-16-le").split("\0", 1)[0]
    type_strings_off, _lt, key_strings_off, _lk = struct.unpack_from(
        "<IIII", data, off + 268)
    type_names, _ = _read_string_pool(data, off + type_strings_off)
    key_names, _ = _read_string_pool(data, off + key_strings_off)

    pkg = result.setdefault(name or f"0x{pkg_id:02x}", {})
    # Type-spec and type chunks follow the two string pools inside the package.
    _, pos = _read_string_pool(data, off + key_strings_off)
    end = min(off + size, len(data))
    while pos + 8 <= end:
        ctype, h_size, c_size = struct.unpack_from("<HHI", data, pos)
        if c_size < 8 or pos + c_size > end:
            raise MalformedError("package sub-chunk size out of range")
        if ctype == 0x0201:                      # type chunk (entries)
            _parse_type(data, pos, type_names, key_names, value_pool, pkg)
        pos += c_size


def _parse_type(data, off, type_names, key_names, value_pool, pkg):
    header_size = struct.unpack_from("<H", data, off + 2)[0]
    type_id = data[off + 8]
    entry_count, entries_start = struct.unpack_from("<II", data, off + 12)
    if entry_count > (len(data) - off) // 4:
        raise MalformedError("type chunk entry count exceeds file size")
    type_name = type_names[type_id - 1] if type_id - 1 < len(type_names) else f"type{type_id}"
    entries = pkg.setdefault(type_name, {})
    # The entry-offset array follows the fixed header + the config block, i.e.
    # it begins at header_size; entries themselves begin at entries_start.
    for i in range(entry_count):
        (eo,) = struct.unpack_from("<I", data, _need(data, off + header_size + 4 * i, 4))
        if eo == 0xFFFFFFFF:
            continue
        p = off + entries_start + eo
        _sz, _flags, key_i = struct.unpack_from("<HHI", data, p)
        _vsize, _r0, dtype = struct.unpack_from("<HBB", data, p + 8)
        (val,) = struct.unpack_from("<I", data, p + 12)
        key = key_names[key_i] if key_i < len(key_names) else f"key{key_i}"
        entries[key] = value_pool[val] if dtype == 0x03 and val < len(value_pool) \
            else _fmt_value(dtype, val, val, lambda i: "")


# --- DEX ------------------------------------------------------------------

def dex_summary(data):
    """Return a light summary of a classes.dex: sizes and class/method names.

    This reads the header and the id tables directly — enough to list what the
    file defines without a full parser.
    """
    _need(data, 0, 0x70)
    if data[:4] != b"dex\n":
        raise MalformedError("not a DEX file")
    string_ids_size, string_ids_off = struct.unpack_from("<II", data, 0x38)
    type_ids_size, type_ids_off = struct.unpack_from("<II", data, 0x40)
    field_ids_size, field_ids_off = struct.unpack_from("<II", data, 0x50)
    method_ids_size, method_ids_off = struct.unpack_from("<II", data, 0x58)
    class_defs_size, class_defs_off = struct.unpack_from("<II", data, 0x60)

    # No id table can hold more entries than the file has bytes for; a hostile
    # header claiming billions of entries must not spin a giant loop.
    limit = len(data)
    for count in (string_ids_size, type_ids_size, field_ids_size,
                  method_ids_size, class_defs_size):
        if count > limit:
            raise MalformedError("DEX id-table count exceeds file size")

    def read_string(idx):
        if not 0 <= idx < string_ids_size:
            raise MalformedError("DEX string index out of range")
        (p,) = struct.unpack_from("<I", data, _need(data, string_ids_off + 4 * idx, 4))
        # skip the ULEB128 UTF-16 length, then read MUTF-8 to the NUL byte
        while p < len(data) and data[p] & 0x80:
            p += 1
        p += 1
        end = data.find(0, p)
        if p > len(data) or end < 0:
            raise MalformedError("unterminated DEX string")
        return mutf8_decode(data[p:end])

    def type_name(idx):
        if not 0 <= idx < type_ids_size:
            raise MalformedError("DEX type index out of range")
        (sidx,) = struct.unpack_from("<I", data, _need(data, type_ids_off + 4 * idx, 4))
        return read_string(sidx)

    classes = []
    for i in range(class_defs_size):
        base = _need(data, class_defs_off + 32 * i, 4)
        (class_idx,) = struct.unpack_from("<I", data, base)
        classes.append(type_name(class_idx))

    methods = []
    for i in range(method_ids_size):
        cls_i, proto_i, name_i = struct.unpack_from(
            "<HHI", data, _need(data, method_ids_off + 8 * i, 8))
        methods.append(type_name(cls_i) + "->" + read_string(name_i))

    fields = []
    for i in range(field_ids_size):
        cls_i, type_i, name_i = struct.unpack_from(
            "<HHI", data, _need(data, field_ids_off + 8 * i, 8))
        fields.append(type_name(cls_i) + "->" + read_string(name_i))

    return {"classes": classes, "methods": methods, "fields": fields,
            "counts": {"strings": string_ids_size, "types": type_ids_size,
                       "methods": method_ids_size, "fields": field_ids_size,
                       "classes": class_defs_size}}
