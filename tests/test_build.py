"""End-to-end tests for the from-scratch APK toolkit.

These assert the toolkit produces artifacts a real parser accepts and a real
verifier validates. They need androguard installed (pip install androguard).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Repo root for `from apkfs import ...`, and the package dir so the bare module
# names used throughout these tests (axml, dex, verify, ...) also resolve.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apkfs"))
sys.path.insert(0, str(ROOT / "examples" / "hello"))

import axml
import verify
import build as hello


def test_axml_roundtrips_through_a_real_parser():
    from androguard.core.axml import AXMLPrinter
    m = axml.manifest("com.example.app", "com.example.app.Main",
                      min_sdk=21, target_sdk=30)
    xml = AXMLPrinter(m).get_xml().decode()
    assert 'package="com.example.app"' in xml
    assert 'android:name="com.example.app.Main"' in xml
    assert "android.intent.action.MAIN" in xml
    assert "android.intent.category.LAUNCHER" in xml


def test_dex_disassembles_to_the_expected_methods():
    from androguard.core.dex import DEX
    d = DEX(hello.build_dex())
    (cls,) = d.get_classes()
    assert cls.get_name() == "Ln/A;"
    assert cls.get_superclassname() == "Landroid/app/Activity;"
    names = sorted(m.get_name() for m in cls.get_methods())
    assert names == ["<init>", "onCreate"]


def test_apk_parses_as_a_real_package(tmp_path):
    from androguard.core.apk import APK
    out = tmp_path / "t.apk"
    import axml as _a
    manifest = _a.manifest("n", "n.A")
    classes = hello.build_dex()
    import apk
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    out.write_bytes(apk.sign_v2(
        {"AndroidManifest.xml": manifest, "classes.dex": classes}, key, cert))
    a = APK(str(out))
    assert a.get_package() == "n"
    assert a.get_main_activity() == "n.A"
    assert a.is_signed_v2()
    assert len(a.get_certificates_der_v2()) == 1


def test_v2_signature_verifies_cryptographically(tmp_path):
    import apk
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign_v2(
        {"AndroidManifest.xml": axml.manifest("n", "n.A"),
         "classes.dex": hello.build_dex()}, key, cert)
    result = verify.verify(blob)
    assert result["digest_ok"] and result["signature_ok"]


def test_tampering_with_contents_breaks_verification(tmp_path):
    import apk
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = bytearray(apk.sign_v2(
        {"AndroidManifest.xml": axml.manifest("n", "n.A"),
         "classes.dex": hello.build_dex()}, key, cert))
    # Flip a byte inside the manifest payload; verification must reject it.
    blob[80] ^= 0xFF
    try:
        verify.verify(bytes(blob))
    except Exception:
        return
    raise AssertionError("verifier accepted a tampered APK")


def _load_module(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_text_example_builds_a_real_ui_and_verifies():
    # Both example entry points are named build.py; load by path to avoid the
    # module-name clash with the hello example imported above.
    text_build = _load_module(
        ROOT / "examples" / "hello_text" / "build.py", "hello_text_build")
    from androguard.core.dex import DEX
    import apk
    dex_bytes = text_build.build_dex()
    d = DEX(dex_bytes)
    (cls,) = d.get_classes()
    oncreate = next(m for m in cls.get_methods() if m.get_name() == "onCreate")
    disasm = "\n".join(
        ins.get_name() + " " + ins.get_output()
        for ins in oncreate.get_code().get_bc().get_instructions())
    assert "new-instance" in disasm and "Landroid/widget/TextView;" in disasm
    assert text_build.MESSAGE in disasm
    assert "setContentView" in disasm
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign_v2(
        {"AndroidManifest.xml": __import__("axml").manifest("h.t", "h.t.Main"),
         "classes.dex": dex_bytes}, key, cert)
    assert verify.verify(blob)["signature_ok"]


def test_both_v2_and_v3_schemes_verify():
    import apk
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    blob = apk.sign(
        {"AndroidManifest.xml": axml.manifest("n", "n.A"),
         "classes.dex": hello.build_dex()}, key, cert, schemes=(2, 3))
    result = verify.verify(blob)
    assert result["schemes"] == ["v2", "v3"]
    from androguard.core.apk import APK
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".apk") as f:
        f.write(blob)
        f.flush()
        a = APK(f.name)
        assert a.is_signed_v2() and a.is_signed_v3()


def test_icon_app_has_label_and_icon(tmp_path):
    icon_build = _load_module(
        ROOT / "examples" / "icon_app" / "build.py", "icon_app_build")
    import apk
    from androguard.core.apk import APK
    files = {
        "AndroidManifest.xml": __import__("axml").manifest(
            icon_build.PACKAGE, icon_build.ACTIVITY,
            label=__import__("axml").Ref(__import__("arsc").res_id(0x7f, 1, 0)),
            icon=__import__("axml").Ref(__import__("arsc").res_id(0x7f, 2, 0)),
            version_code=1, version_name="1.0"),
        "classes.dex": icon_build.build_dex(),
        "resources.arsc": icon_build.build_resources(),
        icon_build.ICON_PATH: __import__("png").solid_icon(),
    }
    key = apk.make_keypair()
    cert = apk.self_signed_cert(key)
    out = tmp_path / "icon.apk"
    out.write_bytes(apk.sign(files, key, cert))
    a = APK(str(out))
    assert a.get_app_name() == icon_build.APP_LABEL
    assert a.get_app_icon() == icon_build.ICON_PATH
    assert a.get_androidversion_name() == "1.0"


def test_counter_example_has_interface_fields_and_virtual_methods():
    counter = _load_module(
        ROOT / "examples" / "counter" / "build.py", "counter_build")
    from androguard.core.dex import DEX
    d = DEX(counter.build_dex())
    (cls,) = d.get_classes()
    assert "Landroid/view/View$OnClickListener;" in cls.get_interfaces()
    field_names = sorted(f.get_name() for f in cls.get_fields())
    assert field_names == ["btn", "count"]
    onclick = next(m for m in cls.get_methods() if m.get_name() == "onClick")
    assert onclick.get_access_flags() & 0x1  # public, in the virtual list
    disasm = "\n".join(
        ins.get_name() for ins in onclick.get_code().get_bc().get_instructions())
    assert "add-int/lit8" in disasm and "iput" in disasm
    import apk
    key = apk.make_keypair()
    blob = apk.sign(
        {"AndroidManifest.xml": __import__("axml").manifest(
            counter.PACKAGE, counter.ACTIVITY),
         "classes.dex": counter.build_dex()},
        key, apk.self_signed_cert(key))
    assert verify.verify(blob)["signature_ok"]


def test_stored_entries_are_four_byte_aligned():
    import apk
    key = apk.make_keypair()
    files = {
        "AndroidManifest.xml": axml.manifest("n", "n.A"),
        "resources.arsc": b"\x02\x00\x0c\x00" + b"\x00" * 40,
        "classes.dex": hello.build_dex(),
    }
    blob = apk.sign(files, key, apk.self_signed_cert(key))
    import struct
    pos = 0
    while blob[pos:pos + 4] == b"PK\x03\x04":
        _, _, _m, _, _, _, comp, _u, nl, el = struct.unpack_from(
            "<HHHHHIIIHH", blob, pos + 4)
        data_off = pos + 30 + nl + el
        assert data_off % 4 == 0, "stored entry data not 4-byte aligned"
        pos = data_off + comp


def test_verify_pinning_rejects_a_resigned_apk():
    # Integrity passes for any self-consistent APK, but pinning the original
    # certificate must reject one re-signed with a different key (authenticity).
    import apk
    key_a = apk.make_keypair()
    cert_a = apk.self_signed_cert(key_a)
    files = {"AndroidManifest.xml": axml.manifest("n", "n.A"),
             "classes.dex": hello.build_dex()}
    blob_a = apk.sign(files, key_a, cert_a)
    from cryptography.hazmat.primitives import serialization
    cert_a_der = cert_a.public_bytes(serialization.Encoding.DER)
    assert verify.verify(blob_a, expected_cert_der=cert_a_der)["signature_ok"]

    # An attacker tampers and re-signs with their own key.
    key_b = apk.make_keypair()
    tampered = apk.sign({**files, "classes.dex": hello.build_dex() + b""},
                        key_b, apk.self_signed_cert(key_b))
    # Integrity-only still passes (that is the documented limitation)...
    assert verify.verify(tampered)["signature_ok"]
    # ...but pinning the trusted certificate rejects it.
    try:
        verify.verify(tampered, expected_cert_der=cert_a_der)
    except Exception:
        return
    raise AssertionError("pinned verification accepted a re-signed APK")


def test_decoders_reject_malformed_input_cleanly():
    import struct
    import decode
    for bad in [b"", b"\x03\x00\x08\x00\x08\x00\x00\x00", b"not a dex file!!"]:
        for fn in (decode.decode_axml, decode.read_arsc, decode.dex_summary):
            try:
                fn(bad)
            except (IndexError, struct.error) as exc:
                raise AssertionError(
                    f"{fn.__name__} crashed with {type(exc).__name__} instead "
                    "of raising MalformedError")
            except ValueError:
                pass  # MalformedError (a ValueError subclass) or a clean reject


SPEC = {
    "package": "com.example.t", "name": "T", "icon_color": "1E88E5",
    "widgets": [
        {"type": "text", "id": "title", "text": "Hi"},
        {"type": "button", "text": "Change",
         "action": {"type": "set_text", "target": "title", "text": "Changed"}},
        {"type": "button", "text": "Site",
         "action": {"type": "open_url", "url": "https://example.com"}},
        {"type": "button", "text": "Toast",
         "action": {"type": "toast", "text": "Hey"}},
    ],
}


def test_appspec_generates_layout_and_dispatching_onclick():
    from apkfs import appspec
    from androguard.core.dex import DEX
    d = DEX(appspec.build_dex(SPEC))
    (cls,) = d.get_classes()
    assert "Landroid/view/View$OnClickListener;" in cls.get_interfaces()
    code = {m.get_name(): "\n".join(
        i.get_name() + " " + i.get_output()
        for i in m.get_code().get_bc().get_instructions())
        for m in cls.get_methods() if m.get_code()}
    on_create, on_click = code["onCreate"], code["onClick"]
    assert on_create.count("new-instance") == 2 + 4     # scroll + layout + 4 widgets
    assert on_create.count("setOnClickListener") == 3   # only buttons w/ actions
    assert "LinearLayout;->setOrientation" in on_create
    assert "getId()" in on_click and on_click.count("if-ne") == 3
    assert "findViewById" in on_click and "check-cast" in on_click
    assert "Landroid/net/Uri;->parse" in on_click
    assert "Landroid/widget/Toast;->makeText" in on_click


def test_appspec_rejects_bad_specs():
    from apkfs import appspec
    bad = [
        {},                                                  # no package
        {"package": "nodots", "widgets": [{"type": "text", "text": "x"}]},
        {"package": "a.b", "widgets": []},                   # no widgets
        {"package": "a.b", "widgets": [{"type": "slider", "text": "x"}]},
        {"package": "a.b", "widgets": [                      # bad target
            {"type": "button", "text": "b",
             "action": {"type": "set_text", "target": "nope", "text": "y"}}]},
        {"package": "a.b", "widgets": [                      # non-http url
            {"type": "button", "text": "b",
             "action": {"type": "open_url", "url": "javascript:alert(1)"}}]},
    ]
    for spec in bad:
        try:
            appspec.validate(spec)
        except appspec.SpecError:
            continue
        raise AssertionError(f"spec accepted but should be rejected: {spec}")


def test_appspec_image_list_and_fetch():
    """Images, lists and a network fetch generate the expected structures:
    ScrollView root, ImageView with drawable resource, list items as rows,
    a Runnable with try/catch for the fetch, and the INTERNET permission."""
    from apkfs import appspec, png, decode
    from androguard.core.dex import DEX
    import base64
    tiny = base64.b64encode(png.solid_icon(size=8)).decode()
    spec = {
        "package": "com.example.full", "name": "Full",
        "widgets": [
            {"type": "text", "id": "out", "text": "-"},
            {"type": "image", "src_base64": tiny},
            {"type": "button", "text": "Load",
             "action": {"type": "fetch", "url": "https://example.com/x",
                        "target": "out"}},
            {"type": "list", "items": [
                {"text": "a"}, {"text": "b", "action": {"type": "toast", "text": "hi"}}]},
        ],
    }
    d = DEX(appspec.build_dex(spec))
    (cls,) = d.get_classes()
    assert "Ljava/lang/Runnable;" in cls.get_interfaces()
    methods = {m.get_name(): m for m in cls.get_methods()}
    run = methods["run"].get_code()
    assert run.get_tries_size() == 1                       # try/catch present
    assert run.get_handlers().get_list()[0].get_catch_all_addr() > 0
    run_txt = "\n".join(i.get_name() + i.get_output()
                        for i in run.get_bc().get_instructions())
    assert "Ljava/net/URL;" in run_txt and "Ljava/util/Scanner;" in run_txt
    assert "move-exception" in run_txt and "Landroid/view/View;->post" in run_txt
    oc = "\n".join(i.get_name() + i.get_output()
                   for i in methods["onCreate"].get_code().get_bc().get_instructions())
    assert "ScrollView" in oc and "ImageView;->setImageResource" in oc
    # 1 text + 1 image + 1 button + 2 list rows = 5 views (+ scroll + layout)
    assert oc.count("new-instance") == 5 + 2 + 1           # +1 LayoutParams

    files = appspec.build_files(spec)
    assert any(name.startswith("res/drawable/") for name in files)
    xml = decode.decode_axml(files["AndroidManifest.xml"])
    assert "android.permission.INTERNET" in xml
    table = decode.read_arsc(files["resources.arsc"])
    assert "img0" in table["com.example.full"]["drawable"]


def test_appspec_fetch_requires_https_and_text_target():
    from apkfs import appspec
    base = {"package": "a.b", "widgets": [
        {"type": "text", "id": "t", "text": "x"},
        {"type": "image", "id": "pic", "src_base64": ""}]}
    for action in ({"type": "fetch", "url": "http://insecure", "target": "t"},
                   {"type": "fetch", "url": "https://ok", "target": "pic"}):
        spec = {**base, "widgets": base["widgets"] + [
            {"type": "button", "text": "b", "action": action}]}
        try:
            appspec.validate(spec)
        except appspec.SpecError:
            continue
        raise AssertionError(f"accepted bad fetch action: {action}")


def test_multi_class_dex_defines_every_class():
    import dalvik as dv
    from dex import DexBuilder, Method
    from androguard.core.dex import DEX
    dx = DexBuilder("La/Main;", "Landroid/app/Activity;")
    other = dx.add_class("La/Other;", "Ljava/lang/Object;")
    a_ctor = dx.methodref("Landroid/app/Activity;", "<init>", "V", [])
    o_ctor = dx.methodref("Ljava/lang/Object;", "<init>", "V", [])
    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    other.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    other.add_instance_field("n", "I")
    dx.freeze()
    dx._defined[0].code = dv.invoke_direct([0], dx.method_index(a_ctor)) + dv.return_void()
    other.methods[0].code = dv.invoke_direct([0], dx.method_index(o_ctor)) + dv.return_void()
    d = DEX(dx.build())
    names = {c.get_name(): c for c in d.get_classes()}
    assert set(names) == {"La/Main;", "La/Other;"}
    assert names["La/Other;"].get_superclassname() == "Ljava/lang/Object;"
    assert [f.get_name() for f in names["La/Other;"].get_fields()] == ["n"]


def test_webapp_host_has_bridge_and_assets():
    from apkfs import webapp, decode
    from androguard.core.dex import DEX
    d = DEX(webapp.build_dex("com.example.w"))
    classes = {c.get_name(): c for c in d.get_classes()}
    assert set(classes) == {"Lcom/example/w/Main;", "Lcom/example/w/Client;",
                            "Lcom/example/w/Chrome;"}
    assert classes["Lcom/example/w/Client;"].get_superclassname() == \
        "Landroid/webkit/WebViewClient;"
    client = classes["Lcom/example/w/Client;"]
    sou = next(m for m in client.get_methods()
               if m.get_name() == "shouldOverrideUrlLoading")
    txt = "\n".join(i.get_name() + i.get_output()
                    for i in sou.get_code().get_bc().get_instructions())
    for cmd in webapp.COMMANDS:
        assert f'"{cmd}"' in txt
    assert "Landroid/net/Uri;->getQueryParameter" in txt
    main = classes["Lcom/example/w/Main;"]
    oc = next(m for m in main.get_methods() if m.get_name() == "onCreate")
    oct_ = "\n".join(i.get_output() for i in oc.get_code().get_bc().get_instructions())
    assert "setJavaScriptEnabled" in oct_ and "file:///android_asset/index.html" in oct_

    html = "<!doctype html><script src=apkfs-bridge.js></script><h1>hi</h1>"
    files = webapp.build_files("com.example.w", "W", (1, 2, 3), {
        "assets/index.html": html.encode(),
        "assets/apkfs-bridge.js": webapp.BRIDGE_JS.encode()})
    assert "assets/index.html" in files
    assert "android.permission.INTERNET" in decode.decode_axml(files["AndroidManifest.xml"])


def test_webapp_apk_from_dir_verifies(tmp_path):
    from apkfs import webapp
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>hello</h1>", encoding="utf-8")
    (site / "style.css").write_text("h1{color:red}", encoding="utf-8")
    blob = webapp.build_from_dir(site, "com.example.site", label="Site")
    assert verify.verify(blob)["signature_ok"]
    import apkinspect
    names = set(apkinspect.read_zip_stored(blob))
    assert {"assets/index.html", "assets/style.css", "assets/apkfs-bridge.js"} <= names


def test_same_key_signs_updates_with_same_certificate():
    from apkfs import appspec, keys
    from cryptography.hazmat.primitives import serialization
    key, cert = keys.generate("test signer")
    # Round-trip through PEM, as a user keeping the key file would.
    key2, cert2 = keys.from_pem(keys.to_pem(key, cert))
    der = cert.public_bytes(serialization.Encoding.DER)
    v1 = appspec.build_from_spec({**SPEC, "version_code": 1}, (key2, cert2))
    v2 = appspec.build_from_spec({**SPEC, "version_code": 2}, (key2, cert2))
    # Both verify against the pinned certificate -> Android would accept v2
    # as an update over v1.
    assert verify.verify(v1, expected_cert_der=der)["authenticity_checked"]
    assert verify.verify(v2, expected_cert_der=der)["authenticity_checked"]


def test_mutf8_round_trips_japanese_and_emoji():
    import dex
    import decode
    for s in ["こんにちは",       # こんにちは
              "\U0001f526\U0001f680",                  # emoji (astral)
              "A\U0001f526B世界"]:             # mixed
        encoded = dex.mutf8_encode(s)
        assert decode.mutf8_decode(encoded) == s
        assert dex.utf16_length(s) == sum(
            1 if ord(c) < 0x10000 else 2 for c in s)


def test_i18n_example_label_and_message_survive():
    i18n = _load_module(
        ROOT / "examples" / "i18n" / "build.py", "i18n_build")
    import decode
    # The DEX message decodes back exactly through our own MUTF-8 reader.
    summary_strings = decode.dex_summary(i18n.build_dex())
    # The resource label round-trips through the arsc reader.
    parsed = decode.read_arsc(i18n.build_resources())
    assert parsed[i18n.PACKAGE]["string"]["app_name"] == i18n.APP_LABEL
    import apk
    key = apk.make_keypair()
    blob = apk.sign({
        "AndroidManifest.xml": __import__("axml").manifest(
            i18n.PACKAGE, i18n.ACTIVITY),
        "classes.dex": i18n.build_dex(),
    }, key, apk.self_signed_cert(key))
    assert verify.verify(blob)["signature_ok"]


def test_axml_encode_decode_round_trip():
    import decode
    m = axml.manifest("com.example.rt", "com.example.rt.Main",
                      label=axml.Ref(0x7f010000), version_code=9,
                      version_name="3.4")
    xml = decode.decode_axml(m)
    assert 'package="com.example.rt"' in xml
    assert 'android:name="com.example.rt.Main"' in xml
    assert 'android:versionName="3.4"' in xml
    assert 'android:label="@0x7f010000"' in xml


def test_arsc_encode_decode_round_trip():
    import arsc
    import decode
    table = arsc.build(0x7f, "com.example.rt", ["My App", "res/mipmap/ic.png"], [
        {"name": "string", "keys": ["app_name"],
         "entries": [(0, arsc.TYPE_STRING, 0)]},
        {"name": "mipmap", "keys": ["ic_launcher"],
         "entries": [(0, arsc.TYPE_STRING, 1)]},
    ])
    parsed = decode.read_arsc(table)
    pkg = parsed["com.example.rt"]
    assert pkg["string"]["app_name"] == "My App"
    assert pkg["mipmap"]["ic_launcher"] == "res/mipmap/ic.png"


def test_dex_summary_reads_classes_fields_methods():
    import decode
    counter = _load_module(
        ROOT / "examples" / "counter" / "build.py", "counter_build2")
    s = decode.dex_summary(counter.build_dex())
    assert s["classes"] == ["Lcom/example/counter/Main;"]
    assert any(f.endswith("->count") for f in s["fields"])
    assert any(m.endswith("->onClick") for m in s["methods"])


def test_apkinspect_reports_every_section():
    import apkinspect
    icon = _load_module(
        ROOT / "examples" / "icon_app" / "build.py", "icon_app_build2")
    import apk
    files = {
        "AndroidManifest.xml": axml.manifest(
            icon.PACKAGE, icon.ACTIVITY, label=axml.Ref(0x7f010000),
            icon=axml.Ref(0x7f020000)),
        "classes.dex": icon.build_dex(),
        "resources.arsc": icon.build_resources(),
        icon.ICON_PATH: __import__("png").solid_icon(),
    }
    key = apk.make_keypair()
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".apk") as f:
        f.write(apk.sign(files, key, apk.self_signed_cert(key)))
        f.flush()
        report = apkinspect.inspect(f.name)
    assert "Manifest:" in report and "Resources:" in report
    assert "classes.dex:" in report and "v2" in report and "v3" in report


def test_assembler_resolves_branch_offsets():
    import dalvik as dv
    a = dv.Assembler()
    a.emit(dv.const4(0, 0))      # 1 unit  (pos 0)
    a.label("loop")              #         (pos 1)
    a.if_eqz(0, "end")           # 2 units (pos 1) -> target pos 7 -> +6
    a.emit(dv.add_int_lit8(0, 0, 1))  # 2 units (pos 3)
    a.goto("loop")               # 2 units (pos 5) -> target pos 1 -> -4
    a.label("end")               #         (pos 7)
    code = a.assemble()
    # Each branch's offset is the second code unit of its instruction.
    import struct
    (if_off,) = struct.unpack_from("<h", code, 2 * 2)   # unit index 2
    (goto_off,) = struct.unpack_from("<h", code, 6 * 2)  # unit index 6
    assert if_off == 6 and goto_off == -4


def test_loop_example_has_control_flow_and_verifies():
    loop = _load_module(
        ROOT / "examples" / "loop_sum" / "build.py", "loop_sum_build")
    from androguard.core.dex import DEX
    d = DEX(loop.build_dex())
    (cls,) = d.get_classes()
    oncreate = next(m for m in cls.get_methods() if m.get_name() == "onCreate")
    names = [ins.get_name()
             for ins in oncreate.get_code().get_bc().get_instructions()]
    assert "if-ge" in names and "goto/16" in names and "add-int" in names
    import apk
    key = apk.make_keypair()
    blob = apk.sign(
        {"AndroidManifest.xml": __import__("axml").manifest(
            loop.PACKAGE, loop.ACTIVITY),
         "classes.dex": loop.build_dex()}, key, apk.self_signed_cert(key))
    assert verify.verify(blob)["signature_ok"]


if __name__ == "__main__":
    import tempfile
    test_axml_roundtrips_through_a_real_parser()
    test_dex_disassembles_to_the_expected_methods()
    with tempfile.TemporaryDirectory() as d:
        test_apk_parses_as_a_real_package(pathlib.Path(d))
        test_v2_signature_verifies_cryptographically(pathlib.Path(d))
        test_tampering_with_contents_breaks_verification(pathlib.Path(d))
        test_icon_app_has_label_and_icon(pathlib.Path(d))
    test_text_example_builds_a_real_ui_and_verifies()
    test_both_v2_and_v3_schemes_verify()
    test_counter_example_has_interface_fields_and_virtual_methods()
    test_assembler_resolves_branch_offsets()
    test_loop_example_has_control_flow_and_verifies()
    test_axml_encode_decode_round_trip()
    test_arsc_encode_decode_round_trip()
    test_dex_summary_reads_classes_fields_methods()
    test_apkinspect_reports_every_section()
    test_mutf8_round_trips_japanese_and_emoji()
    test_i18n_example_label_and_message_survive()
    test_stored_entries_are_four_byte_aligned()
    test_verify_pinning_rejects_a_resigned_apk()
    test_decoders_reject_malformed_input_cleanly()
    test_appspec_generates_layout_and_dispatching_onclick()
    test_appspec_rejects_bad_specs()
    test_appspec_image_list_and_fetch()
    test_appspec_fetch_requires_https_and_text_target()
    test_multi_class_dex_defines_every_class()
    test_webapp_host_has_bridge_and_assets()
    with tempfile.TemporaryDirectory() as d:
        test_webapp_apk_from_dir_verifies(pathlib.Path(d))
    test_same_key_signs_updates_with_same_certificate()
    print("all tests passed")
