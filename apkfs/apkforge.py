#!/usr/bin/env python3
"""apkforge — build a signed, installable APK from the command line.

Ties the whole toolkit together: it writes the binary manifest, a classes.dex
for an Activity that shows a line of text, a resources.arsc with your app label
and a generated launcher icon, packs them into a ZIP, and signs with APK
Signature Scheme v2+v3 — no Android SDK, no JDK.

Example:
    python3 tools/apkforge.py \\
        --package com.example.hello \\
        --label "Hello" \\
        --message "Built with apkforge." \\
        --icon-color 1E88E5 \\
        -o hello.apk
"""
import argparse
import pathlib

from apkfs import axml
from apkfs import arsc
from apkfs import apk
from apkfs import png
from apkfs import dalvik as dv
from apkfs.dex import DexBuilder, Method

PACKAGE_ID = 0x7F
ICON_PATH = "res/mipmap/ic_launcher.png"


def _build_dex(class_desc, message):
    """An Activity that sets a TextView to `message` on create."""
    super_desc = "Landroid/app/Activity;"
    dx = DexBuilder(class_desc, super_desc)
    ctor = dx.methodref(super_desc, "<init>", "V", [])
    super_oncreate = dx.methodref(super_desc, "onCreate", "V",
                                  ["Landroid/os/Bundle;"])
    tv_ctor = dx.methodref("Landroid/widget/TextView;", "<init>", "V",
                           ["Landroid/content/Context;"])
    tv_settext = dx.methodref("Landroid/widget/TextView;", "setText", "V",
                              ["Ljava/lang/CharSequence;"])
    set_content = dx.methodref(super_desc, "setContentView", "V",
                               ["Landroid/view/View;"])
    dx.str(message)
    dx.type("Landroid/widget/TextView;")
    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", ["Landroid/os/Bundle;"]),
                         0x1, 6, 2, 2, b"", direct=False))
    dx.freeze()
    mi = dx.method_index
    msg_idx = dx.string_index(message)
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


def package_files(package, label, icon_rgb, classes_dex, version_code=1,
                  version_name="1.0"):
    """Assemble the manifest, resources and icon around a classes.dex.
    Returns the {name: bytes} dict ready for apk.sign()."""
    activity = package + ".Main"
    resources = arsc.build(PACKAGE_ID, package, [label, ICON_PATH], [
        {"name": "string", "keys": ["app_name"],
         "entries": [(0, arsc.TYPE_STRING, 0)]},
        {"name": "mipmap", "keys": ["ic_launcher"],
         "entries": [(0, arsc.TYPE_STRING, 1)]},
    ])
    manifest = axml.manifest(
        package, activity, label=axml.Ref(arsc.res_id(PACKAGE_ID, 1, 0)),
        icon=axml.Ref(arsc.res_id(PACKAGE_ID, 2, 0)),
        version_code=version_code, version_name=version_name)
    return {
        "AndroidManifest.xml": manifest,
        "classes.dex": classes_dex,
        "resources.arsc": resources,
        ICON_PATH: png.solid_icon(rgb=icon_rgb),
    }


def build_apk(package, label, message, icon_rgb, version_code=1,
              version_name="1.0", signing_key=None):
    """Assemble and sign a complete one-screen APK. Returns the bytes.

    signing_key: an optional (key, cert) pair from apkfs.keys. Pass the same
    one every time so newer versions install over older ones; if omitted a
    throwaway key is generated (fine for a first try, not for updates).
    """
    class_desc = "L" + package.replace(".", "/") + "/Main;"
    files = package_files(package, label, icon_rgb,
                          _build_dex(class_desc, message),
                          version_code, version_name)
    if signing_key is None:
        key = apk.make_keypair()
        cert = apk.self_signed_cert(key)
    else:
        key, cert = signing_key
    return apk.sign(files, key, cert)


def _hex_color(s):
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError("color must be 6 hex digits, e.g. 1E88E5")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def run_wizard():
    """Ask a few plain questions and build an APK — no flags to remember.

    Runs when `apkforge` is started with no arguments in a terminal. Every
    prompt has a default shown in brackets; pressing Enter accepts it.
    """
    def ask(prompt, default):
        got = input(f"{prompt} [{default}]: ").strip()
        return got or default

    print("apkforge — let's build an APK. Press Enter to accept each default.\n")
    package = ask("App id (reverse-domain, e.g. com.yourname.hello)",
                  "com.example.hello")
    label = ask("App name (shown under the icon)", "My App")
    message = ask("Text the app shows on screen", "Hello from my app!")
    while True:
        color = ask("Icon color (6 hex digits)", "1E88E5")
        try:
            rgb = _hex_color(color)
            break
        except argparse.ArgumentTypeError as exc:
            print(f"  {exc}")
    out = ask("Save the APK as", "app.apk")

    blob = build_apk(package, label, message, rgb)
    pathlib.Path(out).write_bytes(blob)
    print(f"\nDone. Wrote {out} ({len(blob)} bytes).")
    print("Install it on a phone with:  adb install -r " + out)
    print("Or copy the .apk to your phone and open it (allow install from "
          "this source).")
    return 0


def _keygen(argv):
    """`apkforge keygen [-o key.pem]` — create a signing key to keep."""
    from apkfs import keys
    p = argparse.ArgumentParser(prog="apkforge keygen",
                                description="Create a signing key (PEM).")
    p.add_argument("-o", "--out", default="signing-key.pem")
    p.add_argument("--name", default="apk-from-scratch signer",
                   help="certificate common name")
    a = p.parse_args(argv)
    if pathlib.Path(a.out).exists():
        print(f"refusing to overwrite existing key: {a.out}")
        return 1
    key, cert = keys.generate(a.name)
    keys.save(a.out, key, cert)
    print(f"wrote {a.out}")
    print(f"certificate SHA-256: {keys.fingerprint(cert)}")
    print("Keep this file safe and private. Use it for every build "
          "(--key) so updates install over older versions.")
    return 0


def _load_signing_key(path):
    from apkfs import keys
    if path is None:
        return None
    return keys.load(path)


def main(argv=None):
    import sys
    raw = sys.argv[1:] if argv is None else list(argv)

    # `apkforge keygen ...` is a subcommand for key management.
    if raw[:1] == ["keygen"]:
        return _keygen(raw[1:])

    # No arguments at an interactive terminal -> friendly question-and-answer
    # wizard, so a first-time user needs no flags at all.
    if not raw and sys.stdin.isatty():
        return run_wizard()

    p = argparse.ArgumentParser(
        description="Build a signed Android APK with no Android SDK. "
                    "Run with no options for an interactive wizard; "
                    "`apkforge keygen` creates a reusable signing key.")
    p.add_argument("--package", help="application id, e.g. com.example.hello")
    p.add_argument("--label", default="From Scratch", help="app name")
    p.add_argument("--message", default="Built from scratch.",
                   help="text the app displays")
    p.add_argument("--icon-color", type=_hex_color, default="1E88E5",
                   help="icon color as 6 hex digits (default 1E88E5)")
    p.add_argument("--version-code", type=int, default=1)
    p.add_argument("--version-name", default="1.0")
    p.add_argument("--spec", help="JSON app spec (widgets + actions); "
                                  "overrides --package/--label/--message")
    p.add_argument("--key", help="signing key PEM from `apkforge keygen`; "
                                 "reuse it so updates install")
    p.add_argument("-o", "--out", default="app.apk", help="output APK path")
    args = p.parse_args(raw)

    signing = _load_signing_key(args.key)
    if args.spec:
        from apkfs import appspec
        import json
        spec = json.loads(pathlib.Path(args.spec).read_text(encoding="utf-8"))
        blob = appspec.build_from_spec(spec, signing_key=signing)
        pkg = spec.get("package", "?")
    else:
        if not args.package:
            p.error("--package is required (or use --spec)")
        blob = build_apk(args.package, args.label, args.message,
                         args.icon_color, args.version_code,
                         args.version_name, signing_key=signing)
        pkg = args.package
    pathlib.Path(args.out).write_bytes(blob)
    signed_with = args.key if args.key else "a throwaway key (use --key for updates)"
    print(f"wrote {args.out} ({len(blob)} bytes) — package {pkg}")
    print(f"signed with {signed_with}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
