"""Dalvik Executable (classes.dex) writer.

Produces a single-class .dex that Android's runtime (ART) will load and run,
without javac, d8, or dx. You hand it a class name, a superclass, optional
interfaces, instance fields, and methods whose bodies are raw Dalvik bytecode;
it lays out every DEX section (string_ids, type_ids, proto_ids, field_ids,
method_ids, class_defs, type lists, code items, data), patches the two
checksums ART verifies, and returns the bytes.

One class per file, but that class can implement an interface and hold fields —
enough for an Activity that responds to clicks. Everything ART checks on load —
the SHA-1 signature, the Adler-32 checksum, the map list — is produced here.

DEX reference: https://source.android.com/docs/core/runtime/dex-format
"""
import struct
import hashlib
import zlib

NO_INDEX = 0xFFFFFFFF


def uleb128(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def mutf8_encode(s):
    """Encode a string as Modified UTF-8 (MUTF-8), the form DEX uses.

    MUTF-8 differs from UTF-8 in two ways: U+0000 is written as the two bytes
    C0 80 (so no interior NULs terminate the string), and characters outside
    the Basic Multilingual Plane are written as a UTF-16 surrogate pair, each
    surrogate in the 3-byte form (CESU-8) — not as a single 4-byte sequence.
    This makes emoji and other astral characters encode the way ART expects.
    """
    out = bytearray()
    for ch in s:
        cp = ord(ch)
        if cp == 0:
            out += b"\xc0\x80"
        elif cp < 0x80:
            out.append(cp)
        elif cp < 0x800:
            out.append(0xC0 | (cp >> 6))
            out.append(0x80 | (cp & 0x3F))
        elif cp < 0x10000:
            out += _three_byte(cp)
        else:
            v = cp - 0x10000
            out += _three_byte(0xD800 + (v >> 10))   # high surrogate
            out += _three_byte(0xDC00 + (v & 0x3FF))  # low surrogate
    return bytes(out)


def _three_byte(cp):
    return bytes((0xE0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3F),
                 0x80 | (cp & 0x3F)))


def utf16_length(s):
    """Number of UTF-16 code units in s — the count DEX stores before each
    string (astral characters count as two)."""
    return sum(1 if ord(ch) < 0x10000 else 2 for ch in s)


class Ref:
    """A descriptor-string reference, e.g. 'Landroid/app/Activity;'."""


class Method:
    """One method to emit.

    name:      method name, e.g. 'onCreate'
    proto:     (return_descriptor, [param_descriptors])
    access:    DEX access flags (0x10001 = public|static for a main, etc.)
    registers: total registers the code item declares
    ins:       incoming argument register count
    outs:      max outgoing argument count for any invoke
    code:      bytes of Dalvik bytecode (16-bit code units, little-endian)
    """

    def __init__(self, name, proto, access, registers, ins, outs, code,
                 direct=True, tries=()):
        self.name = name
        self.proto = proto
        self.access = access
        self.registers = registers
        self.ins = ins
        self.outs = outs
        self.code = code
        # Constructors, static and private methods are "direct"; overrides and
        # interface implementations must be "virtual" so ART dispatches them.
        self.direct = direct
        # Exception handling: a list of (start_unit, end_unit, handler_unit)
        # in 16-bit code units; end is exclusive. Each is a catch-all handler
        # (catches Throwable), which is what "keep the app alive on error"
        # needs. Typed catches are not needed by the toolkit's examples.
        self.tries = list(tries)


class DexBuilder:
    """Collects strings/types/protos/methods, then serializes a .dex.

    Typical use:
        dx = DexBuilder("Lcom/example/Main;", "Ljava/lang/Object;")
        dx.add_method(Method(...))
        data = dx.build()
    """

    def __init__(self, class_desc, super_desc):
        self.class_desc = class_desc
        self.super_desc = super_desc
        self._strings = []
        self._string_idx = {}
        self._types = []
        self._type_idx = {}
        self._protos = []
        self._proto_idx = {}
        self._methods = []           # (class_desc, proto_key, name) tuples
        self._method_idx = {}
        self._defined = []           # Method objects for this class
        self._field_idx = {}         # (class, type, name) -> None until frozen
        self._instance_fields = []   # (field_key, access) defined by this class
        self._interfaces = []        # interface type descriptors this class adds
        self.str(class_desc)
        self.str(super_desc)
        self.type(class_desc)
        self.type(super_desc)

    def str(self, s):
        if s not in self._string_idx:
            self._string_idx[s] = len(self._strings)
            self._strings.append(s)
        return self._string_idx[s]

    def type(self, desc):
        self.str(desc)
        if desc not in self._type_idx:
            self._type_idx[desc] = len(self._types)
            self._types.append(desc)
        return self._type_idx[desc]

    def proto(self, ret, params):
        key = (ret, tuple(params))
        if key in self._proto_idx:
            return self._proto_idx[key]
        shorty = self._shorty(ret) + "".join(self._shorty(p) for p in params)
        self.str(shorty)
        self.type(ret)
        for p in params:
            self.type(p)
        self._proto_idx[key] = len(self._protos)
        self._protos.append((shorty, ret, list(params)))
        return self._proto_idx[key]

    def methodref(self, cls, name, ret, params):
        self.type(cls)
        self.proto(ret, params)
        self.str(name)
        key = (cls, (ret, tuple(params)), name)
        if key not in self._method_idx:
            self._method_idx[key] = None  # index assigned at build time
        return key

    def fieldref(self, cls, name, type_desc):
        """Register a field reference (class, type, name) and return its key.
        Use field_index(key) after freeze() for iget/iput operands."""
        self.type(cls)
        self.type(type_desc)
        self.str(name)
        key = (cls, type_desc, name)
        self._field_idx.setdefault(key, None)
        return key

    def add_instance_field(self, name, type_desc, access=0x2):
        """Declare an instance field on this class (access default: private).
        Returns the field key for iget/iput."""
        key = self.fieldref(self.class_desc, name, type_desc)
        self._instance_fields.append((key, access))
        return key

    def add_interface(self, desc):
        """Declare that this class implements the given interface descriptor."""
        self.type(desc)
        if desc not in self._interfaces:
            self._interfaces.append(desc)

    def add_method(self, method):
        self.methodref(self.class_desc, method.name, method.proto[0], method.proto[1])
        self._defined.append(method)

    def freeze(self):
        """Sort every pool into its final on-disk order and assign the method
        indices ART will see. Call this once after all strings, types, protos
        and method refs are registered and BEFORE generating bytecode, so the
        method indices baked into instructions match the method_ids table.
        Idempotent; build() calls it if you did not."""
        if getattr(self, "_frozen", False):
            return
        # DEX requires string_ids ordered by UTF-16 code-unit value so ART can
        # binary-search them. Sorting by the big-endian UTF-16 bytes gives that
        # order and, unlike a code-point sort, is correct for astral characters
        # (emoji), whose surrogate pairs compare above the BMP.
        self._strings.sort(key=lambda s: s.encode("utf-16-be"))
        self._string_idx = {s: i for i, s in enumerate(self._strings)}
        self._types.sort(key=lambda d: self._string_idx[d])
        self._type_idx = {d: i for i, d in enumerate(self._types)}
        self._proto_items = sorted(
            self._protos,
            key=lambda p: (self._type_idx[p[1]],
                           tuple(self._type_idx[x] for x in p[2])),
        )
        self._proto_idx = {(r, tuple(ps)): i
                           for i, (sh, r, ps) in enumerate(self._proto_items)}
        self._method_map, self._method_list = self._sorted_methodrefs()
        self._field_map, self._field_list = self._sorted_fieldrefs()
        self._frozen = True

    def _sorted_fieldrefs(self):
        def key(f):
            cls, type_desc, name = f
            return (self._type_idx[cls], self._string_idx[name],
                    self._type_idx[type_desc])
        refs = sorted(self._field_idx.keys(), key=key)
        return {f: i for i, f in enumerate(refs)}, refs

    def method_index(self, ref):
        """Final method index for a ref returned by methodref(). Valid only
        after freeze()."""
        self.freeze()
        return self._method_map[ref]

    def field_index(self, ref):
        """Final field index for a ref from fieldref()/add_instance_field().
        Valid only after freeze()."""
        self.freeze()
        return self._field_map[ref]

    def string_index(self, s):
        """Final string-pool index, valid after freeze(). Use this (not the
        value str() returned at registration) for const-string operands, since
        the pool is re-sorted when the builder freezes."""
        self.freeze()
        return self._string_idx[s]

    def type_index(self, desc):
        """Final type index, valid after freeze(). Use this for new-instance
        and other type operands."""
        self.freeze()
        return self._type_idx[desc]

    @staticmethod
    def _shorty(desc):
        if desc == "V":
            return "V"
        if desc in "ZBSCIJFD":
            return desc
        return "L"  # object / array

    def _sorted_methodrefs(self):
        def key(m):
            cls, (ret, params), name = m
            return (self._type_idx[cls], self._string_idx[name], self._proto_idx[(ret, params)])
        refs = sorted(self._method_idx.keys(), key=key)
        return {m: i for i, m in enumerate(refs)}, refs

    def build(self):
        # Freeze ordering (sorts pools, assigns method indices) if the caller
        # did not already. ART needs string_ids/type_ids sorted for its binary
        # search, and the method indices must match those baked into bytecode.
        self.freeze()
        proto_items = self._proto_items
        method_map, method_list = self._method_map, self._method_list

        HEADER = 0x70
        field_list = self._field_list
        n_str, n_type = len(self._strings), len(self._types)
        n_proto, n_meth = len(proto_items), len(method_list)
        n_field = len(field_list)

        # DEX section order: string, type, proto, field, method, class_def.
        off = HEADER
        string_ids_off = off; off += 4 * n_str
        type_ids_off = off; off += 4 * n_type
        proto_ids_off = off; off += 12 * n_proto
        field_ids_off = off if n_field else 0; off += 8 * n_field
        method_ids_off = off; off += 8 * n_meth
        class_defs_off = off; off += 32  # one class

        data_start = off
        data = bytearray()

        def data_off():
            return data_start + len(data)

        # --- string data ---
        string_data_offsets = []
        for s in self._strings:
            string_data_offsets.append(data_off())
            # DEX string_data_item: ULEB128 UTF-16 length, then MUTF-8 bytes,
            # then a NUL terminator.
            data += uleb128(utf16_length(s)) + mutf8_encode(s) + b"\0"

        # --- type lists: proto parameters and the class interface list ---
        # All type_list chunks must be contiguous here, because the map list
        # records one offset and count for the whole type_list section and a
        # reader walks them back-to-back from that offset.
        type_list_offsets = {}
        type_list_count = 0

        def write_type_list(type_descs):
            nonlocal type_list_count
            while len(data) % 4:
                data.append(0)
            off_here = data_off()
            data.extend(struct.pack("<I", len(type_descs)))
            for t in type_descs:
                data.extend(struct.pack("<H", self._type_idx[t]))
            # Each type_list is 4-aligned; an odd count needs 2 bytes of pad.
            if len(type_descs) % 2 == 1:
                data.extend(b"\0\0")
            type_list_count += 1
            return off_here

        for sh, ret, params in proto_items:
            key = tuple(params)
            if params and key not in type_list_offsets:
                type_list_offsets[key] = write_type_list(params)

        interfaces_off = 0
        if self._interfaces:
            interfaces_off = write_type_list(self._interfaces)

        # --- code items ---
        code_offsets = {}
        for m in self._defined:
            while len(data) % 4:
                data += b"\0"
            code_offsets[m.name] = data_off()
            insns = m.code
            assert len(insns) % 2 == 0
            # code_item: registers, ins, outs, tries_size, debug_info_off(0),
            # insns_size (code units), insns, then optional try/catch tables.
            data += struct.pack("<HHHHII", m.registers, m.ins, m.outs,
                                len(m.tries), 0, len(insns) // 2)
            data += insns
            if m.tries:
                # try_items must start 4-byte aligned: pad if insns_size is odd.
                if (len(insns) // 2) % 2 == 1:
                    data += b"\0\0"
                # Every try here uses its own catch-all handler. Build the
                # encoded_catch_handler_list first so try_items can point into
                # it (handler_off is a byte offset from the list's start).
                handler_list = bytearray(uleb128(len(m.tries)))
                handler_offsets = []
                for (_s, _e, handler_unit) in m.tries:
                    handler_offsets.append(len(handler_list))
                    # size = 0 (sleb128) -> no typed catches, catch-all follows
                    handler_list += b"\x00" + uleb128(handler_unit)
                for (start, end, _h), off in zip(m.tries, handler_offsets):
                    data += struct.pack("<IHH", start, end - start, off)
                data += handler_list

        # --- class_data: instance fields + direct methods ---
        class_data_off = data_off()
        cd = bytearray()
        direct = [m for m in self._defined if m.direct]
        virtual = [m for m in self._defined if not m.direct]
        cd += uleb128(0) + uleb128(len(self._instance_fields))  # static, instance
        cd += uleb128(len(direct)) + uleb128(len(virtual))      # direct, virtual
        # Encoded fields use index deltas over field ids sorted ascending.
        prev = 0
        for key, access in sorted(self._instance_fields,
                                  key=lambda kv: self._field_map[kv[0]]):
            idx = self._field_map[key]
            cd += uleb128(idx - prev) + uleb128(access)
            prev = idx

        def midx(m):
            return method_map[(self.class_desc,
                               (m.proto[0], tuple(m.proto[1])), m.name)]

        # Direct and virtual method lists are each delta-encoded from zero,
        # sorted by method index.
        for group in (direct, virtual):
            prev = 0
            for m in sorted(group, key=midx):
                idx = midx(m)
                cd += uleb128(idx - prev) + uleb128(m.access) \
                    + uleb128(code_offsets[m.name])
                prev = idx
        data += cd

        # --- map list ---
        while len(data) % 4:
            data += b"\0"
        map_off = data_off()

        def str_id_blob():
            return b"".join(struct.pack("<I", o) for o in string_data_offsets)

        # Build the map list. Every section present must appear exactly once
        # with its true element count, and entries must be ordered by offset.
        type_list_min = min(
            ([interfaces_off] if interfaces_off else [])
            + list(type_list_offsets.values()), default=0)
        entries = [
            (0x0000, 1, 0),                         # header_item
            (0x0001, n_str, string_ids_off),        # string_id_item
            (0x0002, n_type, type_ids_off),         # type_id_item
            (0x0003, n_proto, proto_ids_off),       # proto_id_item
            (0x0004, n_field, field_ids_off),       # field_id_item
            (0x0005, n_meth, method_ids_off),       # method_id_item
            (0x0006, 1, class_defs_off),            # class_def_item
            (0x2001, len(self._defined),            # code_item
             code_offsets[self._defined[0].name]),
            (0x1001, type_list_count, type_list_min),  # type_list
            (0x2002, n_str,                         # string_data_item
             string_data_offsets[0] if string_data_offsets else 0),
            (0x2000, 1, class_data_off),            # class_data_item
            (0x1000, 1, map_off),                   # map_list
        ]
        entries = [e for e in entries if e[1] > 0]
        entries.sort(key=lambda e: e[2])            # map must be offset-ordered
        map_blob = struct.pack("<I", len(entries))
        for t, size, o in entries:
            map_blob += struct.pack("<HHII", t, 0, size, o)
        data += map_blob

        # --- fixed-size sections (now that all data offsets are known) ---
        string_ids = str_id_blob()
        type_ids = b"".join(struct.pack("<I", self._string_idx[d]) for d in self._types)
        proto_ids = b""
        for sh, ret, params in proto_items:
            tl = type_list_offsets.get(tuple(params), 0)
            proto_ids += struct.pack("<III", self._string_idx[sh],
                                     self._type_idx[ret], tl)
        field_ids = b""
        for cls, type_desc, name in field_list:
            field_ids += struct.pack("<HHI", self._type_idx[cls],
                                     self._type_idx[type_desc],
                                     self._string_idx[name])
        method_ids = b""
        for cls, (ret, params), name in method_list:
            method_ids += struct.pack("<HHI", self._type_idx[cls],
                                      self._proto_idx[(ret, params)],
                                      self._string_idx[name])
        class_def = struct.pack(
            "<IIIIIIII",
            self._type_idx[self.class_desc], 0x1,  # class idx, access public
            self._type_idx[self.super_desc], interfaces_off,  # superclass, interfaces
            NO_INDEX, 0, class_data_off, 0,        # source, annotations, data, static
        )

        body = (string_ids + type_ids + proto_ids + field_ids + method_ids
                + class_def + bytes(data))
        file_size = HEADER + len(body)

        header = bytearray(HEADER)
        header[0:8] = b"dex\n035\0"
        struct.pack_into("<I", header, 0x20, file_size)
        struct.pack_into("<I", header, 0x24, HEADER)       # header_size
        struct.pack_into("<I", header, 0x28, 0x12345678)   # endian tag
        struct.pack_into("<II", header, 0x38, n_str, string_ids_off)
        struct.pack_into("<II", header, 0x40, n_type, type_ids_off)
        struct.pack_into("<II", header, 0x48, n_proto, proto_ids_off)
        struct.pack_into("<II", header, 0x50, n_field, field_ids_off)
        struct.pack_into("<II", header, 0x58, n_meth, method_ids_off)
        struct.pack_into("<II", header, 0x60, 1, class_defs_off)
        struct.pack_into("<II", header, 0x68, len(body) + (HEADER - data_start) + data_start - HEADER, data_start)
        # data_size / data_off: data region spans from data_start to EOF.
        struct.pack_into("<II", header, 0x68, file_size - data_start, data_start)
        struct.pack_into("<I", header, 0x34, map_off)      # map_off

        blob = bytes(header) + body
        # SHA-1 signature over everything after the signature field (0x20).
        sig = hashlib.sha1(blob[0x20:]).digest()
        blob = blob[:0x0C] + sig + blob[0x20:]
        # Adler-32 checksum over everything after the checksum field (0x0C).
        checksum = zlib.adler32(blob[0x0C:]) & 0xFFFFFFFF
        blob = blob[:8] + struct.pack("<I", checksum) + blob[0x0C:]
        return blob
