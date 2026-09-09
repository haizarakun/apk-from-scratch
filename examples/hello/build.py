#!/usr/bin/env python3
"""Build a minimal, launchable APK with no Android SDK.

This assembles the three pieces the toolkit provides — a binary manifest, a
classes.dex with one Activity, and a v2-signed ZIP — into hello.apk.

The Activity does the smallest visible thing: on create it sets the screen
orientation to landscape, which is observable on a real device and needs no
resources, no layout, and no R class.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from apkfs import axml
from apkfs import apk
from apkfs.dex import DexBuilder, Method

PACKAGE = "n"
ACTIVITY = "n.A"            # class n/A
CLASS_DESC = "Ln/A;"
SUPER_DESC = "Landroid/app/Activity;"


def build_dex():
    dx = DexBuilder(CLASS_DESC, SUPER_DESC)

    # Method refs used by the bytecode below.
    m_super_oncreate = dx.methodref(SUPER_DESC, "onCreate", "V",
                                    ["Landroid/os/Bundle;"])
    m_set_orient = dx.methodref(CLASS_DESC, "setRequestedOrientation", "V", ["I"])
    m_ctor = dx.methodref(SUPER_DESC, "<init>", "V", [])

    # The two methods this class defines must be registered before freezing,
    # so their refs exist in the table. We register them, freeze the ordering,
    # then emit bytecode against the final (frozen) method indices.
    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", ["Landroid/os/Bundle;"]),
                         0x1, 3, 2, 2, b""))
    dx.freeze()

    # <init>(): call Activity.<init>() and return.
    #   invoke-direct {p0}, Activity.<init>()V   (this = v0)
    #   return-void
    init_code = _invoke_direct(0, _idx(dx, m_ctor)) + _op("return-void")

    # onCreate(Bundle): super.onCreate(savedState); setRequestedOrientation(0)
    #   registers: v0=this(p0), v1=bundle(p1); const v2 = 0
    #   invoke-super {v0, v1}, onCreate(Bundle)V
    #   const/4 v2, 0
    #   invoke-virtual {v0, v2}, setRequestedOrientation(I)V
    #   return-void
    oncreate_code = (
        _invoke_super(0, 1, _idx(dx, m_super_oncreate))
        + _const4(2, 0)
        + _invoke_virtual(0, 2, _idx(dx, m_set_orient))
        + _op("return-void")
    )

    # Fill in the real bytecode now that indices are frozen.
    by_name = {m.name: m for m in dx._defined}
    by_name["<init>"].code = init_code
    by_name["onCreate"].code = oncreate_code
    return dx.build()


# --- tiny Dalvik instruction encoders (16-bit code units, little-endian) ---
import struct


def _u16(x):
    return struct.pack("<H", x & 0xFFFF)


def _op(name):
    return _u16(0x000E)  # return-void (op 0x0E, 00 high byte)


def _const4(reg, val):
    # const/4 vA, #+B : 0x12, B(4)|A(4)
    return _u16(0x12 | ((val & 0xF) << 12) | ((reg & 0xF) << 8))


def _invoke_direct(reg, method_idx):
    # invoke-direct {vReg} : 0x70, A=1 args, method, reg in low nibble
    return _u16(0x70 | (1 << 12)) + _u16(method_idx) + _u16(reg & 0xF)


def _invoke_super(r0, r1, method_idx):
    return _u16(0x6F | (2 << 12)) + _u16(method_idx) + _u16((r0 & 0xF) | ((r1 & 0xF) << 4))


def _invoke_virtual(r0, r1, method_idx):
    return _u16(0x6E | (2 << 12)) + _u16(method_idx) + _u16((r0 & 0xF) | ((r1 & 0xF) << 4))


def _idx(dx, ref):
    return dx.method_index(ref)


def main():
    manifest = axml.manifest(PACKAGE, ACTIVITY, min_sdk=23, target_sdk=28)
    classes = build_dex()
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign(
        {"AndroidManifest.xml": manifest, "classes.dex": classes}, key, cert)
    out = pathlib.Path(__file__).with_name("hello.apk")
    out.write_bytes(blob)
    print(f"wrote {out} ({len(blob)} bytes)")
    print(f"  manifest: {len(manifest)} B   classes.dex: {len(classes)} B")


if __name__ == "__main__":
    main()
