#!/usr/bin/env python3
"""Build an app whose bytecode actually computes — a loop, by hand.

onCreate runs a real loop to sum 1..10 and displays the result, using the
label-based Assembler in tools/dalvik.py to resolve branch offsets. This shows
the DEX path is not limited to straight-line code: it has working control flow.

Logic, in Java terms:

    int sum = 0;
    for (int i = 1; i < 11; i++) sum += i;   // 55
    TextView tv = new TextView(this);
    tv.setText(Integer.toString(sum));
    setContentView(tv);
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apkfs import axml
from apkfs import apk
from apkfs import dalvik as dv
from apkfs.dex import DexBuilder, Method

PACKAGE = "com.example.loopsum"
ACTIVITY = "com.example.loopsum.Main"
CLASS_DESC = "Lcom/example/loopsum/Main;"
SUPER_DESC = "Landroid/app/Activity;"
LIMIT = 11  # sum i for i in 1..10


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
    int_to_str = dx.methodref("Ljava/lang/Integer;", "toString",
                              "Ljava/lang/String;", ["I"])
    dx.type("Landroid/widget/TextView;")

    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", ["Landroid/os/Bundle;"]),
                         0x1, 8, 2, 2, b"", direct=False))
    dx.freeze()

    mi = dx.method_index
    tv_idx = dx.type_index("Landroid/widget/TextView;")

    init = dv.invoke_direct([0], mi(ctor)) + dv.return_void()

    # registers=8, ins=2 -> this=v6, state=v7.
    # v0=sum, v1=i, v2=limit, v3=TextView, v4=string.
    a = dv.Assembler()
    a.emit(dv.invoke_super([6, 7], mi(super_oncreate)))
    a.emit(dv.const4(0, 0))            # sum = 0
    a.emit(dv.const4(1, 1))            # i = 1
    a.emit(dv.const16(2, LIMIT))       # limit = 11
    a.label("loop")
    a.if_ge(1, 2, "done")              # if i >= limit: break
    a.emit(dv.add_int(0, 0, 1))        # sum += i
    a.emit(dv.add_int_lit8(1, 1, 1))   # i += 1
    a.goto("loop")
    a.label("done")
    a.emit(dv.new_instance(3, tv_idx))
    a.emit(dv.invoke_direct([3, 6], mi(tv_ctor)))   # new TextView(this)
    a.emit(dv.invoke_static([0], mi(int_to_str)))   # Integer.toString(sum)
    a.emit(dv.move_result_object(4))
    a.emit(dv.invoke_virtual([3, 4], mi(tv_settext)))
    a.emit(dv.invoke_virtual([6, 3], mi(set_content)))
    a.emit(dv.return_void())

    by_name = {m.name: m for m in dx._defined}
    by_name["<init>"].code = init
    by_name["onCreate"].code = a.assemble()
    return dx.build()


def main():
    manifest = axml.manifest(PACKAGE, ACTIVITY, label="Loop Sum",
                             version_code=1, version_name="1.0")
    classes = build_dex()
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign(
        {"AndroidManifest.xml": manifest, "classes.dex": classes}, key, cert)
    out = pathlib.Path(__file__).with_name("loop_sum.apk")
    out.write_bytes(blob)
    print(f"wrote {out} ({len(blob)} bytes)")
    print(f"  manifest: {len(manifest)} B   classes.dex: {len(classes)} B")


if __name__ == "__main__":
    main()
