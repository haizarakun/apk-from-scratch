"""Binary AndroidManifest.xml (AXML) writer.

Android never reads the text form of AndroidManifest.xml. aapt compiles it
into a chunked binary format and the framework parses that. This module writes
that binary form directly from a tiny Python tree, so no aapt is needed.

Chunk layout produced:
    XML header
      string pool     (every string used by the document, UTF-8)
      resource map    (android:attr resource IDs, aligned with pool indices)
      start namespace (xmlns:android)
        start element / attributes ... end element
      end namespace
"""
import struct

ANDROID_NS = "http://schemas.android.com/apk/res/android"

# android.R.attr resource IDs (from frameworks/base/core/res/res/values/public.xml)
ATTR_IDS = {
    "theme": 0x01010000,
    "label": 0x01010001,
    "icon": 0x01010002,
    "name": 0x01010003,
    "exported": 0x01010010,
    "minSdkVersion": 0x0101020C,
    "versionCode": 0x0101021B,
    "versionName": 0x0101021C,
    "targetSdkVersion": 0x01010270,
}

TYPE_STRING = 0x03
TYPE_REFERENCE = 0x01
TYPE_INT_DEC = 0x10
TYPE_INT_BOOL = 0x12


class Ref:
    """A reference to a resource id, e.g. Ref(0x7f010000) for @string/app_name.
    Use as an attribute value so the manifest points into resources.arsc."""

    def __init__(self, res_id):
        self.res_id = res_id


class Element:
    """One XML element. attrs: {name: value}. Names prefixed with 'android:'
    use the android namespace; bare names (e.g. 'package') have no namespace."""

    def __init__(self, tag, attrs=None, children=()):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = list(children)


class _Pool:
    """String pool. Strings that carry a resource ID must come first, in the
    same order as the resource map, so we reserve them up front."""

    def __init__(self, attr_names):
        self.strings = list(attr_names)
        self.index = {s: i for i, s in enumerate(self.strings)}

    def get(self, s):
        if s not in self.index:
            self.index[s] = len(self.strings)
            self.strings.append(s)
        return self.index[s]

    def encode(self):
        data, offsets = b"", []
        for s in self.strings:
            b = s.encode("utf-8")
            offsets.append(len(data))
            # UTF-8 pool entry: <UTF-16 char count><byte count><bytes><NUL>.
            # Each length uses one byte when < 0x80, otherwise a two-byte form
            # with the high bit of the first byte set, so long strings (a long
            # package name, class, or versionName) encode correctly.
            char_count = sum(1 if ord(c) < 0x10000 else 2 for c in s)
            data += _pool_len(char_count) + _pool_len(len(b)) + b + b"\0"
        while len(data) % 4:
            data += b"\0"
        header_size = 28
        body = b"".join(struct.pack("<I", o) for o in offsets) + data
        header = struct.pack(
            "<HHIIIIII", 0x0001, header_size, header_size + len(body),
            len(self.strings), 0, 0x100, header_size + 4 * len(self.strings), 0,
        )
        return header + body


def _pool_len(n):
    """String-pool length prefix: one byte if < 0x80, else two bytes with the
    high bit of the first set (holding the upper 7 bits)."""
    if n < 0x80:
        return bytes([n])
    return bytes([(n >> 8) | 0x80, n & 0xFF])


def _walk(el, out):
    for k in el.attrs:
        if k.startswith("android:"):
            out.add(k.split(":", 1)[1])
    for c in el.children:
        _walk(c, out)


def _typed(value):
    if isinstance(value, Ref):
        return TYPE_REFERENCE, value.res_id & 0xFFFFFFFF
    if isinstance(value, bool):
        return TYPE_INT_BOOL, 0xFFFFFFFF if value else 0
    if isinstance(value, int):
        return TYPE_INT_DEC, value & 0xFFFFFFFF
    return TYPE_STRING, None


def _element(el, pool, ns_idx):
    attrs = b""
    for key, value in el.attrs.items():
        if key.startswith("android:"):
            ns, name = ns_idx, pool.get(key.split(":", 1)[1])
        else:
            ns, name = 0xFFFFFFFF, pool.get(key)
        kind, data = _typed(value)
        raw = 0xFFFFFFFF
        if kind == TYPE_STRING:
            raw = data = pool.get(value)
        attrs += struct.pack("<IIIHBBI", ns, name, raw, 8, 0, kind, data)
    name = pool.get(el.tag)
    n = len(el.attrs)
    start = struct.pack(
        "<HHIIIIIHHHHHH", 0x0102, 16, 36 + len(attrs), 0, 0xFFFFFFFF,
        0xFFFFFFFF, name, 20, 20, n, 0, 0, 0,
    ) + attrs
    body = b"".join(_element(c, pool, ns_idx) for c in el.children)
    end = struct.pack("<HHIIIII", 0x0103, 16, 24, 0, 0xFFFFFFFF, 0xFFFFFFFF, name)
    return start + body + end


def build(root):
    """Return the binary AXML bytes for an Element tree."""
    used = set()
    _walk(root, used)
    attr_names = sorted(used, key=lambda a: ATTR_IDS[a])
    pool = _Pool(attr_names)
    prefix, uri = pool.get("android"), pool.get(ANDROID_NS)

    res_map = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(attr_names))
    res_map += b"".join(struct.pack("<I", ATTR_IDS[a]) for a in attr_names)

    body = _element(root, pool, uri)  # fills the pool, so encode pool after
    ns_start = struct.pack("<HHIIIII", 0x0100, 16, 24, 0, 0xFFFFFFFF, prefix, uri)
    ns_end = struct.pack("<HHIIIII", 0x0101, 16, 24, 0, 0xFFFFFFFF, prefix, uri)

    content = pool.encode() + res_map + ns_start + body + ns_end
    return struct.pack("<HHI", 0x0003, 8, 8 + len(content)) + content


def manifest(package, activity, min_sdk=23, target_sdk=28,
             label=None, icon=None, version_code=None, version_name=None):
    """Build a launchable manifest.

    label/icon accept a Ref (e.g. Ref(0x7f010000)) resolving through
    resources.arsc, or a literal string. Omit them for the minimal, no-resource
    manifest. version_code/version_name set the manifest's version fields.
    """
    manifest_attrs = {"package": package}
    if version_code is not None:
        manifest_attrs["android:versionCode"] = version_code
    if version_name is not None:
        manifest_attrs["android:versionName"] = version_name

    app_attrs = {}
    if label is not None:
        app_attrs["android:label"] = label
    if icon is not None:
        app_attrs["android:icon"] = icon

    return build(Element("manifest", manifest_attrs, [
        Element("uses-sdk", {"android:minSdkVersion": min_sdk,
                             "android:targetSdkVersion": target_sdk}),
        Element("application", app_attrs, [
            Element("activity", {"android:name": activity, "android:exported": True}, [
                Element("intent-filter", {}, [
                    Element("action", {"android:name": "android.intent.action.MAIN"}),
                    Element("category", {"android:name": "android.intent.category.LAUNCHER"}),
                ]),
            ]),
        ]),
    ]))
