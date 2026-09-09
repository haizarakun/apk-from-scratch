#!/usr/bin/env python3
"""Build an app with a non-ASCII label and message — full Unicode, no SDK.

Android strings are Modified UTF-8 (MUTF-8) in DEX and UTF-8 in the resource
table, and their length prefixes count UTF-16 code units. The toolkit handles
all of that, so app names and on-screen text can be Japanese, emoji, or any
other script and still install and render correctly.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apkfs import axml
from apkfs import arsc
from apkfs import apk
from apkfs import png
from apkfs import dalvik as dv
from apkfs.dex import DexBuilder, Method

PACKAGE = "com.example.i18n"
ACTIVITY = "com.example.i18n.Main"
CLASS_DESC = "Lcom/example/i18n/Main;"
SUPER_DESC = "Landroid/app/Activity;"
PACKAGE_ID = 0x7F

# A label and message spanning scripts and an astral (emoji) character.
APP_LABEL = "スクラッチ製 \U0001f526"
MESSAGE = "こんにちは、世界！ — Hola — 你好 — \U0001f680 SDK 不要"
ICON_PATH = "res/mipmap/ic_launcher.png"


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
    dx.str(MESSAGE)
    dx.type("Landroid/widget/TextView;")
    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", ["Landroid/os/Bundle;"]),
                         0x1, 6, 2, 2, b"", direct=False))
    dx.freeze()
    mi = dx.method_index
    msg_idx = dx.string_index(MESSAGE)
    tv_idx = dx.type_index("Landroid/widget/TextView;")
    by_name = {m.name: m for m in dx._defined}
    by_name["<init>"].code = dv.invoke_direct([0], mi(ctor)) + dv.return_void()
    by_name["onCreate"].code = (
        dv.invoke_super([4, 5], mi(super_oncreate))
        + dv.new_instance(0, tv_idx)
        + dv.invoke_direct([0, 4], mi(tv_ctor))
        + dv.const_string(1, msg_idx)
        + dv.invoke_virtual([0, 1], mi(tv_settext))
        + dv.invoke_virtual([4, 0], mi(set_content))
        + dv.return_void()
    )
    return dx.build()


def build_resources():
    return arsc.build(PACKAGE_ID, PACKAGE, [APP_LABEL, ICON_PATH], [
        {"name": "string", "keys": ["app_name"],
         "entries": [(0, arsc.TYPE_STRING, 0)]},
        {"name": "mipmap", "keys": ["ic_launcher"],
         "entries": [(0, arsc.TYPE_STRING, 1)]},
    ])


def main():
    manifest = axml.manifest(
        PACKAGE, ACTIVITY, label=axml.Ref(arsc.res_id(PACKAGE_ID, 1, 0)),
        icon=axml.Ref(arsc.res_id(PACKAGE_ID, 2, 0)),
        version_code=1, version_name="1.0")
    files = {
        "AndroidManifest.xml": manifest,
        "classes.dex": build_dex(),
        "resources.arsc": build_resources(),
        ICON_PATH: png.solid_icon(rgb=(0xAB, 0x47, 0xBC)),
    }
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign(files, key, cert)
    out = pathlib.Path(__file__).with_name("i18n.apk")
    out.write_bytes(blob)
    print(f"wrote {out} ({len(blob)} bytes) — label {APP_LABEL!r}")


if __name__ == "__main__":
    main()
