"""A small, readable Dalvik instruction encoder.

Each function returns the raw bytes (16-bit code units, little-endian) for one
instruction. Register numbers and pool indices are passed in; the caller gets
the method indices from a DexBuilder via method_index().

Only the instructions the examples need are here. Every encoder documents the
instruction's format (e.g. "35c" = five-register invoke) so the layout is
auditable against the Dalvik bytecode reference:
https://source.android.com/docs/core/runtime/dalvik-bytecode
"""
import struct


def _u16(x):
    return struct.pack("<H", x & 0xFFFF)


def _invoke_kind(op, regs, method_idx):
    """Format 35c: [op | A<<12][method_idx][G<<12 | regs C,D,E,F packed 4 bits].

    A is the argument count; the first four registers pack into the third code
    unit (low nibble first) and a fifth, if present, into byte B of the first
    unit. The examples use at most four, which keeps B zero."""
    a = len(regs)
    if a > 5:
        raise ValueError("invoke-kind takes at most 5 registers; use /range")
    r = (regs + [0, 0, 0, 0, 0])[:5]
    low = (r[3] & 0xF) << 12 | (r[2] & 0xF) << 8 | (r[1] & 0xF) << 4 | (r[0] & 0xF)
    return _u16(op | ((r[4] & 0xF) << 8) | (a << 12)) + _u16(method_idx) + _u16(low)


def invoke_direct(regs, method_idx):
    """invoke-direct {regs}, method — e.g. a constructor call."""
    return _invoke_kind(0x70, regs, method_idx)


def invoke_super(regs, method_idx):
    """invoke-super {regs}, method."""
    return _invoke_kind(0x6F, regs, method_idx)


def invoke_virtual(regs, method_idx):
    """invoke-virtual {regs}, method."""
    return _invoke_kind(0x6E, regs, method_idx)


def invoke_static(regs, method_idx):
    """invoke-static {regs}, method."""
    return _invoke_kind(0x71, regs, method_idx)


def iget(dest, obj, field_idx):
    """iget vA, vB, field@CCCC — read an int instance field (format 22c)."""
    return _u16(0x52 | ((obj & 0xF) << 12) | ((dest & 0xF) << 8)) + _u16(field_idx)


def iput(src, obj, field_idx):
    """iput vA, vB, field@CCCC — write an int instance field (format 22c)."""
    return _u16(0x59 | ((obj & 0xF) << 12) | ((src & 0xF) << 8)) + _u16(field_idx)


def iget_object(dest, obj, field_idx):
    """iget-object vA, vB, field@CCCC — read an object instance field."""
    return _u16(0x54 | ((obj & 0xF) << 12) | ((dest & 0xF) << 8)) + _u16(field_idx)


def iput_object(src, obj, field_idx):
    """iput-object vA, vB, field@CCCC — write an object instance field."""
    return _u16(0x5B | ((obj & 0xF) << 12) | ((src & 0xF) << 8)) + _u16(field_idx)


def add_int_lit8(dest, src, literal):
    """add-int/lit8 vAA, vBB, #+CC — add a small constant (format 22b)."""
    return _u16(0xD8 | ((dest & 0xFF) << 8)) + \
        _u16((src & 0xFF) | ((literal & 0xFF) << 8))


def add_int(dest, src1, src2):
    """add-int vAA, vBB, vCC — add two registers (format 23x)."""
    return _u16(0x90 | ((dest & 0xFF) << 8)) + \
        _u16((src1 & 0xFF) | ((src2 & 0xFF) << 8))


def const4(reg, value):
    """const/4 vA, #+B — load a 4-bit signed literal (format 11n)."""
    return _u16(0x12 | ((value & 0xF) << 12) | ((reg & 0xF) << 8))


def const16(reg, value):
    """const/16 vAA, #+BBBB — load a 16-bit signed literal (format 21s)."""
    return _u16(0x13 | ((reg & 0xFF) << 8)) + _u16(value)


def const_string(reg, string_idx):
    """const-string vAA, string@BBBB — load a string reference (format 21c)."""
    return _u16(0x1A | ((reg & 0xFF) << 8)) + _u16(string_idx)


def const32(reg, value):
    """const vAA, #+BBBBBBBB — load a full 32-bit literal (format 31i)."""
    v = value & 0xFFFFFFFF
    return _u16(0x14 | ((reg & 0xFF) << 8)) + _u16(v & 0xFFFF) + _u16(v >> 16)


def check_cast(reg, type_idx):
    """check-cast vAA, type@BBBB — assert/cast the object's type (format 21c)."""
    return _u16(0x1F | ((reg & 0xFF) << 8)) + _u16(type_idx)


def new_instance(reg, type_idx):
    """new-instance vAA, type@BBBB — allocate an object (format 21c)."""
    return _u16(0x22 | ((reg & 0xFF) << 8)) + _u16(type_idx)


def return_void():
    """return-void (format 10x)."""
    return _u16(0x0E)


def move_exception(reg):
    """move-exception vAA — first instruction of a catch handler: take the
    thrown object (format 11x)."""
    return _u16(0x0D | ((reg & 0xFF) << 8))


def move_result(reg):
    """move-result vAA — capture the int/boolean an invoke returned."""
    return _u16(0x0A | ((reg & 0xFF) << 8))


def move_result_object(reg):
    """move-result-object vAA — capture the object an invoke returned."""
    return _u16(0x0C | ((reg & 0xFF) << 8))


# --- control flow ---------------------------------------------------------
#
# Branch instructions encode their target as a signed offset in code units,
# relative to the start of the branching instruction. Computing those offsets
# by hand is error-prone, so the Assembler below lets you emit named labels and
# branch to them; it resolves the offsets in a second pass.

class Assembler:
    """Collects instructions and labels, then resolves branch offsets.

    Usage:
        a = Assembler()
        a.emit(dv.const4(0, 0))        # any fixed-size instruction bytes
        a.label("loop")
        a.if_eqz(1, "done")            # branch to a label
        ...
        a.goto("loop")
        a.label("done")
        a.emit(dv.return_void())
        code = a.assemble()

    Offsets are measured in 16-bit code units, as Dalvik requires.
    """

    def __init__(self):
        self._items = []  # ("raw", bytes) | ("label", name) | ("branch", spec)

    def emit(self, raw):
        self._items.append(("raw", raw))
        return self

    def label(self, name):
        self._items.append(("label", name))
        return self

    def goto(self, target):
        # goto/16 (format 20t): always 2 code units, 16-bit signed offset.
        def enc(off):
            return _u16(0x0029) + _u16(off & 0xFFFF)
        self._items.append(("branch", (2, enc, target)))
        return self

    def if_eqz(self, reg, target):
        """Branch to target if vReg == 0 (format 21t, 2 code units)."""
        self._items.append(("branch", (2, _ifz_enc(0x38, reg), target)))
        return self

    def if_nez(self, reg, target):
        """Branch to target if vReg != 0 (format 21t, 2 code units)."""
        self._items.append(("branch", (2, _ifz_enc(0x39, reg), target)))
        return self

    def if_ge(self, rega, regb, target):
        """Branch to target if vA >= vB (format 22t, 2 code units)."""
        self._items.append(("branch", (2, _ifcmp_enc(0x35, rega, regb), target)))
        return self

    def if_lt(self, rega, regb, target):
        """Branch to target if vA < vB (format 22t, 2 code units)."""
        self._items.append(("branch", (2, _ifcmp_enc(0x34, rega, regb), target)))
        return self

    def if_eq(self, rega, regb, target):
        """Branch to target if vA == vB (format 22t, 2 code units)."""
        self._items.append(("branch", (2, _ifcmp_enc(0x32, rega, regb), target)))
        return self

    def if_ne(self, rega, regb, target):
        """Branch to target if vA != vB (format 22t, 2 code units)."""
        self._items.append(("branch", (2, _ifcmp_enc(0x33, rega, regb), target)))
        return self

    def assemble(self):
        # First pass: assign each item a position in code units.
        pos = 0
        positions = {}
        layout = []
        for kind, val in self._items:
            if kind == "label":
                positions[val] = pos
                continue
            size = len(val) // 2 if kind == "raw" else val[0]
            layout.append((pos, kind, val))
            pos += size
        # Keep label -> code-unit positions so callers can build try/catch
        # ranges (Method.tries) from the same labels they branch to.
        self.positions = dict(positions)
        # Second pass: emit, resolving branch offsets relative to the branch.
        out = bytearray()
        for at, kind, val in layout:
            if kind == "raw":
                out += val
            else:
                size, enc, target = val
                if target not in positions:
                    raise KeyError(f"undefined label: {target}")
                out += enc(positions[target] - at)
        return bytes(out)


def _ifz_enc(op, reg):
    def enc(off):
        return _u16(op | ((reg & 0xFF) << 8)) + _u16(off & 0xFFFF)
    return enc


def _ifcmp_enc(op, rega, regb):
    def enc(off):
        return _u16(op | ((regb & 0xF) << 12) | ((rega & 0xF) << 8)) \
            + _u16(off & 0xFFFF)
    return enc
