#!/usr/bin/env python3
"""Build an APK whose Activity shows text on screen — still no Android SDK.

Unlike the minimal example (which only rotates the screen), this one builds a
real view at runtime: it constructs a TextView, sets its text, and makes it the
Activity's content view. The bytecode is assembled by hand from the readable
encoders in tools/dalvik.py, which proves the toolkit can express ordinary app
logic — object allocation, constructor calls, string loads, virtual calls — not
just a single framework method.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apkfs import axml
from apkfs import apk
from apkfs import dalvik as dv
from apkfs.dex import DexBuilder, Method

PACKAGE = "h.t"
ACTIVITY = "h.t.Main"
CLASS_DESC = "Lh/t/Main;"
SUPER_DESC = "Landroid/app/Activity;"
MESSAGE = "Hello from scratch. No SDK, no aapt, no d8."


def build_dex():
    dx = DexBuilder(CLASS_DESC, SUPER_DESC)

    ctor = dx.methodref(SUPER_DESC, "<init>", "V", [])
    super_oncreate = dx.methodref(SUPER_DESC, "onCreate", "V",
                                  ["Landroid/os/Bundle;"])
    tv_ctor = dx.methodref("Landroid/widget/TextView;", "<init>", "V",
                           ["Landroid/content/Context;"])
    tv_settext = dx.methodref("Landroid/widget/TextView;", "setText", "V",
                              ["Ljava/lang/CharSequence;"])
    set_content = dx.methodref(SUPER_DESC, "setContentView", "V",
                               ["Landroid/view/View;"])
    msg = dx.str(MESSAGE)
    tv_type = dx.type("Landroid/widget/TextView;")

    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", ["Landroid/os/Bundle;"]),
                         0x1, 6, 2, 2, b""))
    dx.freeze()

    mi = dx.method_index

    # Operand indices must be read AFTER freeze(), since the pools are sorted.
    msg_idx = dx.string_index(MESSAGE)
    tv_idx = dx.type_index("Landroid/widget/TextView;")

    # <init>(): this is v0 (registers=1, ins=1).
    init = dv.invoke_direct([0], mi(ctor)) + dv.return_void()

    # onCreate(Bundle): registers=6, ins=2 -> this=v4, savedState=v5.
    # Locals: v0 = TextView, v1 = message string.
    oncreate = (
        dv.invoke_super([4, 5], mi(super_oncreate))        # super.onCreate(state)
        + dv.new_instance(0, tv_idx)
        + dv.invoke_direct([0, 4], mi(tv_ctor))            # new TextView(this)
        + dv.const_string(1, msg_idx)                      # v1 = MESSAGE
        + dv.invoke_virtual([0, 1], mi(tv_settext))        # tv.setText(v1)
        + dv.invoke_virtual([4, 0], mi(set_content))       # setContentView(tv)
        + dv.return_void()
    )

    by_name = {m.name: m for m in dx._defined}
    by_name["<init>"].code = init
    by_name["onCreate"].code = oncreate
    return dx.build()


def main():
    manifest = axml.manifest(PACKAGE, ACTIVITY, min_sdk=23, target_sdk=28)
    classes = build_dex()
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign(
        {"AndroidManifest.xml": manifest, "classes.dex": classes}, key, cert)
    out = pathlib.Path(__file__).with_name("hello_text.apk")
    out.write_bytes(blob)
    print(f"wrote {out} ({len(blob)} bytes)")
    print(f"  manifest: {len(manifest)} B   classes.dex: {len(classes)} B")


if __name__ == "__main__":
    main()
