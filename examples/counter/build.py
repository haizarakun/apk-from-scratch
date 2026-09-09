#!/usr/bin/env python3
"""Build an interactive app: a button that counts taps. Still no Android SDK.

This is the most capable example. The Activity *implements*
`View.OnClickListener`, holds an `int` counter field and a `Button` field, and
updates the button's text on every tap — an instance field read, an integer
add, an instance field write, a static call to `Integer.toString`, and a
virtual call, all hand-assembled. It exercises the DEX writer's support for
interfaces, instance fields, and virtual (dispatched) methods.

Logic, in Java terms:

    public class Main extends Activity implements View.OnClickListener {
        int count;
        Button btn;
        public void onCreate(Bundle b) {
            super.onCreate(b);
            btn = new Button(this);
            btn.setText("Tap me: 0");
            btn.setOnClickListener(this);
            setContentView(btn);
        }
        public void onClick(View v) {
            count = count + 1;
            btn.setText(Integer.toString(count));
        }
    }
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apkfs import axml
from apkfs import apk
from apkfs import dalvik as dv
from apkfs.dex import DexBuilder, Method

PACKAGE = "com.example.counter"
ACTIVITY = "com.example.counter.Main"
CLASS_DESC = "Lcom/example/counter/Main;"
SUPER_DESC = "Landroid/app/Activity;"
BUTTON = "Landroid/widget/Button;"
VIEW = "Landroid/view/View;"
LISTENER = "Landroid/view/View$OnClickListener;"
INITIAL = "Tap me: 0"


def build_dex():
    dx = DexBuilder(CLASS_DESC, SUPER_DESC)
    dx.add_interface(LISTENER)

    count = dx.add_instance_field("count", "I")
    btn = dx.add_instance_field("btn", BUTTON)

    ctor = dx.methodref(SUPER_DESC, "<init>", "V", [])
    super_oncreate = dx.methodref(SUPER_DESC, "onCreate", "V",
                                  ["Landroid/os/Bundle;"])
    btn_ctor = dx.methodref(BUTTON, "<init>", "V", ["Landroid/content/Context;"])
    set_text = dx.methodref(BUTTON, "setText", "V", ["Ljava/lang/CharSequence;"])
    set_listener = dx.methodref(BUTTON, "setOnClickListener", "V", [LISTENER])
    set_content = dx.methodref(SUPER_DESC, "setContentView", "V", [VIEW])
    int_to_str = dx.methodref("Ljava/lang/Integer;", "toString", "Ljava/lang/String;", ["I"])
    dx.str(INITIAL)

    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", ["Landroid/os/Bundle;"]),
                         0x1, 6, 2, 2, b"", direct=False))
    dx.add_method(Method("onClick", ("V", [VIEW]),
                         0x1, 5, 2, 1, b"", direct=False))
    dx.freeze()

    mi, fi = dx.method_index, dx.field_index
    initial_idx = dx.string_index(INITIAL)
    btn_type = dx.type_index(BUTTON)

    init = dv.invoke_direct([0], mi(ctor)) + dv.return_void()

    # onCreate: registers=6, ins=2 -> this=v4, state=v5; locals v0=Button, v1=str
    oncreate = (
        dv.invoke_super([4, 5], mi(super_oncreate))
        + dv.new_instance(0, btn_type)
        + dv.invoke_direct([0, 4], mi(btn_ctor))        # new Button(this)
        + dv.iput_object(0, 4, fi(btn))                 # this.btn = button
        + dv.const_string(1, initial_idx)
        + dv.invoke_virtual([0, 1], mi(set_text))       # btn.setText("Tap me: 0")
        + dv.invoke_virtual([0, 4], mi(set_listener))   # btn.setOnClickListener(this)
        + dv.invoke_virtual([4, 0], mi(set_content))    # setContentView(btn)
        + dv.return_void()
    )

    # onClick: registers=5, ins=2 -> this=v3, view=v4; locals v0=count, v1=str
    onclick = (
        dv.iget(0, 3, fi(count))                        # v0 = this.count
        + dv.add_int_lit8(0, 0, 1)                       # v0 = v0 + 1
        + dv.iput(0, 3, fi(count))                       # this.count = v0
        + dv.invoke_static([0], mi(int_to_str))          # Integer.toString(v0)
        + dv.move_result_object(1)                       # v1 = result
        + dv.iget_object(2, 3, fi(btn))                  # v2 = this.btn
        + dv.invoke_virtual([2, 1], mi(set_text))        # btn.setText(v1)
        + dv.return_void()
    )

    by_name = {m.name: m for m in dx._defined}
    by_name["<init>"].code = init
    by_name["onCreate"].code = oncreate
    by_name["onClick"].code = onclick
    return dx.build()


def main():
    manifest = axml.manifest(PACKAGE, ACTIVITY, min_sdk=23, target_sdk=28,
                             label="Counter", version_code=1, version_name="1.0")
    classes = build_dex()
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign(
        {"AndroidManifest.xml": manifest, "classes.dex": classes}, key, cert)
    out = pathlib.Path(__file__).with_name("counter.apk")
    out.write_bytes(blob)
    print(f"wrote {out} ({len(blob)} bytes)")
    print(f"  manifest: {len(manifest)} B   classes.dex: {len(classes)} B")


if __name__ == "__main__":
    main()
