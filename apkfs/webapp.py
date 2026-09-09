"""Turn a folder of HTML/CSS/JavaScript into a signed Android app.

This is the "no Android Studio" path for real apps. Instead of encoding every
feature as bytecode, the toolkit generates a small native host once — an
Activity holding a full-screen WebView — and your app is ordinary web code
bundled inside the APK under assets/. Forms, multiple screens, lists, images,
storage (localStorage), network (fetch), animation: anything a browser can do,
your app can do, and it installs like any other app.

Three hand-assembled classes make up the host (all generated with no SDK):

  Main   extends Activity      — creates the WebView (JavaScript + DOM
                                  storage on), loads assets/index.html, and
                                  exposes native helpers: toast, openUrl,
                                  share, copy. Back button walks web history.
  Client extends WebViewClient — intercepts navigations to app://<cmd>?v=...
                                  and runs the matching native helper; this
                                  is the JavaScript -> native bridge.
  Chrome extends WebChromeClient — makes alert() show as a toast, so plain
                                  web code behaves sensibly.

From JavaScript, include the generated apkfs-bridge.js and call:

    App.toast("hi")   App.open("https://...")   App.share("text")
    App.copy("text")  App.exit()

Everything else is just web development.
"""
import pathlib

from apkfs import apk
from apkfs import arsc
from apkfs import axml
from apkfs import dalvik as dv
from apkfs import png
from apkfs.dex import DexBuilder, Method

ACT = "Landroid/app/Activity;"
CTX = "Landroid/content/Context;"
VIEW = "Landroid/view/View;"
BUNDLE = "Landroid/os/Bundle;"
WEBVIEW = "Landroid/webkit/WebView;"
WEBSETTINGS = "Landroid/webkit/WebSettings;"
WEBVIEWCLIENT = "Landroid/webkit/WebViewClient;"
WEBCHROMECLIENT = "Landroid/webkit/WebChromeClient;"
JSRESULT = "Landroid/webkit/JsResult;"
INTENT = "Landroid/content/Intent;"
URI = "Landroid/net/Uri;"
TOAST = "Landroid/widget/Toast;"
CLIPBOARD = "Landroid/content/ClipboardManager;"
CLIPDATA = "Landroid/content/ClipData;"
OBJECT = "Ljava/lang/Object;"
STR = "Ljava/lang/String;"
CHARSEQ = "Ljava/lang/CharSequence;"

INDEX_URL = "file:///android_asset/index.html"
BRIDGE_SCHEME = "app"
BRIDGE_PARAM = "v"
INTERNET = "android.permission.INTERNET"
PACKAGE_ID = 0x7F
ICON_PATH = "res/mipmap/ic_launcher.png"

BRIDGE_JS = """\
// apkfs bridge: call native features from JavaScript.
// Navigating to app://<command>?v=<value> is intercepted by the native host.
(function () {
  function go(cmd, value) {
    var v = value == null ? "" : String(value);
    location.href = "app://" + cmd + "?v=" + encodeURIComponent(v);
  }
  window.App = {
    toast: function (text) { go("toast", text); },   // short popup message
    open:  function (url)  { go("open", url); },     // open in the browser
    share: function (text) { go("share", text); },   // system share sheet
    copy:  function (text) { go("copy", text); },    // copy to clipboard
    exit:  function ()     { go("exit", ""); }       // close the app
  };
})();
"""

COMMANDS = ("toast", "open", "share", "copy", "exit")


class WebAppError(ValueError):
    pass


def build_dex(package):
    """Generate classes.dex for the WebView host: Main, Client, Chrome."""
    base = "L" + package.replace(".", "/") + "/"
    MAIN, CLIENT, CHROME = base + "Main;", base + "Client;", base + "Chrome;"

    dx = DexBuilder(MAIN, ACT)
    client = dx.add_class(CLIENT, WEBVIEWCLIENT)
    chrome = dx.add_class(CHROME, WEBCHROMECLIENT)

    f_web = dx.add_instance_field("web", WEBVIEW)
    f_client_act = client.add_instance_field("act", MAIN)
    f_chrome_act = chrome.add_instance_field("act", MAIN)

    m = {}
    # framework
    m["act_init"] = dx.methodref(ACT, "<init>", "V", [])
    m["on_create"] = dx.methodref(ACT, "onCreate", "V", [BUNDLE])
    m["on_back"] = dx.methodref(ACT, "onBackPressed", "V", [])
    m["set_content"] = dx.methodref(ACT, "setContentView", "V", [VIEW])
    m["start_activity"] = dx.methodref(ACT, "startActivity", "V", [INTENT])
    m["finish"] = dx.methodref(ACT, "finish", "V", [])
    m["get_service"] = dx.methodref(ACT, "getSystemService", OBJECT, [STR])
    m["wv_init"] = dx.methodref(WEBVIEW, "<init>", "V", [CTX])
    m["wv_settings"] = dx.methodref(WEBVIEW, "getSettings", WEBSETTINGS, [])
    m["wv_set_client"] = dx.methodref(WEBVIEW, "setWebViewClient", "V", [WEBVIEWCLIENT])
    m["wv_set_chrome"] = dx.methodref(WEBVIEW, "setWebChromeClient", "V", [WEBCHROMECLIENT])
    m["wv_load"] = dx.methodref(WEBVIEW, "loadUrl", "V", [STR])
    m["wv_can_back"] = dx.methodref(WEBVIEW, "canGoBack", "Z", [])
    m["wv_back"] = dx.methodref(WEBVIEW, "goBack", "V", [])
    m["ws_js"] = dx.methodref(WEBSETTINGS, "setJavaScriptEnabled", "V", ["Z"])
    m["ws_dom"] = dx.methodref(WEBSETTINGS, "setDomStorageEnabled", "V", ["Z"])
    m["ws_file"] = dx.methodref(WEBSETTINGS, "setAllowFileAccess", "V", ["Z"])
    m["ws_universal"] = dx.methodref(WEBSETTINGS, "setAllowUniversalAccessFromFileURLs", "V", ["Z"])
    m["wvc_init"] = dx.methodref(WEBVIEWCLIENT, "<init>", "V", [])
    m["wcc_init"] = dx.methodref(WEBCHROMECLIENT, "<init>", "V", [])
    m["js_confirm"] = dx.methodref(JSRESULT, "confirm", "V", [])
    m["uri_parse"] = dx.methodref(URI, "parse", URI, [STR])
    m["uri_scheme"] = dx.methodref(URI, "getScheme", STR, [])
    m["uri_host"] = dx.methodref(URI, "getHost", STR, [])
    m["uri_query"] = dx.methodref(URI, "getQueryParameter", STR, [STR])
    m["str_equals"] = dx.methodref(STR, "equals", "Z", [OBJECT])
    m["intent_init2"] = dx.methodref(INTENT, "<init>", "V", [STR, URI])
    m["intent_init1"] = dx.methodref(INTENT, "<init>", "V", [STR])
    m["intent_type"] = dx.methodref(INTENT, "setType", INTENT, [STR])
    m["intent_extra"] = dx.methodref(INTENT, "putExtra", INTENT, [STR, STR])
    m["toast_make"] = dx.methodref(TOAST, "makeText", TOAST, [CTX, CHARSEQ, "I"])
    m["toast_show"] = dx.methodref(TOAST, "show", "V", [])
    m["clip_new"] = dx.methodref(CLIPDATA, "newPlainText", CLIPDATA, [CHARSEQ, CHARSEQ])
    m["clip_set"] = dx.methodref(CLIPBOARD, "setPrimaryClip", "V", [CLIPDATA])
    # our own
    m["client_init"] = dx.methodref(CLIENT, "<init>", "V", [MAIN])
    m["chrome_init"] = dx.methodref(CHROME, "<init>", "V", [MAIN])
    m["main_toast"] = dx.methodref(MAIN, "toast", "V", [STR])
    m["main_open"] = dx.methodref(MAIN, "openUrl", "V", [STR])
    m["main_share"] = dx.methodref(MAIN, "share", "V", [STR])
    m["main_copy"] = dx.methodref(MAIN, "copy", "V", [STR])

    strings = [INDEX_URL, BRIDGE_SCHEME, BRIDGE_PARAM, "",
               "android.intent.action.VIEW", "android.intent.action.SEND",
               "text/plain", "android.intent.extra.TEXT", "clipboard", "text"]
    strings += list(COMMANDS)
    for s in strings:
        dx.str(s)
    for t in (WEBVIEW, INTENT, CLIENT, CHROME, CLIPBOARD):
        dx.type(t)

    # --- declare methods (code filled in after freeze) ---
    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", [BUNDLE]), 0x1, 8, 2, 2, b"", direct=False))
    dx.add_method(Method("onBackPressed", ("V", []), 0x1, 3, 1, 1, b"", direct=False))
    dx.add_method(Method("toast", ("V", [STR]), 0x1, 5, 2, 3, b"", direct=False))
    dx.add_method(Method("openUrl", ("V", [STR]), 0x1, 5, 2, 3, b"", direct=False))
    dx.add_method(Method("share", ("V", [STR]), 0x1, 5, 2, 3, b"", direct=False))
    dx.add_method(Method("copy", ("V", [STR]), 0x1, 5, 2, 2, b"", direct=False))
    client.add_method(Method("<init>", ("V", [MAIN]), 0x10001, 2, 2, 1, b""))
    client.add_method(Method("shouldOverrideUrlLoading", ("Z", [WEBVIEW, STR]),
                             0x1, 8, 3, 2, b"", direct=False))
    chrome.add_method(Method("<init>", ("V", [MAIN]), 0x10001, 2, 2, 1, b""))
    chrome.add_method(Method("onJsAlert", ("Z", [WEBVIEW, STR, STR, JSRESULT]),
                             0x1, 8, 5, 2, b"", direct=False))
    dx.freeze()
    mi, si, ti, fi = dx.method_index, dx.string_index, dx.type_index, dx.field_index

    def M(cls, name):
        return {mm.name: mm for mm in cls.methods}[name]

    # ---------------- Main ----------------
    M(dx.primary, "<init>").code = dv.invoke_direct([0], mi(m["act_init"])) + dv.return_void()

    # onCreate: registers=8, this=v6, bundle=v7; v0=web, v1=settings, v2=bool,
    # v3=string, v4=client/chrome
    a = dv.Assembler()
    a.emit(dv.invoke_super([6, 7], mi(m["on_create"])))
    a.emit(dv.new_instance(0, ti(WEBVIEW)))
    a.emit(dv.invoke_direct([0, 6], mi(m["wv_init"])))
    a.emit(dv.iput_object(0, 6, fi(f_web)))
    a.emit(dv.invoke_virtual([0], mi(m["wv_settings"])))
    a.emit(dv.move_result_object(1))
    a.emit(dv.const4(2, 1))
    for key in ("ws_js", "ws_dom", "ws_file", "ws_universal"):
        a.emit(dv.invoke_virtual([1, 2], mi(m[key])))
    a.emit(dv.new_instance(4, ti(CLIENT)))
    a.emit(dv.invoke_direct([4, 6], mi(m["client_init"])))
    a.emit(dv.invoke_virtual([0, 4], mi(m["wv_set_client"])))
    a.emit(dv.new_instance(4, ti(CHROME)))
    a.emit(dv.invoke_direct([4, 6], mi(m["chrome_init"])))
    a.emit(dv.invoke_virtual([0, 4], mi(m["wv_set_chrome"])))
    a.emit(dv.const_string(3, si(INDEX_URL)))
    a.emit(dv.invoke_virtual([0, 3], mi(m["wv_load"])))
    a.emit(dv.invoke_virtual([6, 0], mi(m["set_content"])))
    a.emit(dv.return_void())
    M(dx.primary, "onCreate").code = a.assemble()

    # onBackPressed: registers=3, this=v2; v0=web, v1=bool
    b = dv.Assembler()
    b.emit(dv.iget_object(0, 2, fi(f_web)))
    b.emit(dv.invoke_virtual([0], mi(m["wv_can_back"])))
    b.emit(dv.move_result(1))
    b.if_eqz(1, "super")
    b.emit(dv.invoke_virtual([0], mi(m["wv_back"])))
    b.emit(dv.return_void())
    b.label("super")
    b.emit(dv.invoke_super([2], mi(m["on_back"])))
    b.emit(dv.return_void())
    M(dx.primary, "onBackPressed").code = b.assemble()

    # toast(String): registers=5, this=v3, s=v4; v0=int, v1=toast
    M(dx.primary, "toast").code = (
        dv.const4(0, 0)
        + dv.invoke_static([3, 4, 0], mi(m["toast_make"]))
        + dv.move_result_object(1)
        + dv.invoke_virtual([1], mi(m["toast_show"]))
        + dv.return_void())

    # openUrl(String): this=v3, s=v4; v0=uri, v1=intent, v2=str
    M(dx.primary, "openUrl").code = (
        dv.invoke_static([4], mi(m["uri_parse"]))
        + dv.move_result_object(0)
        + dv.new_instance(1, ti(INTENT))
        + dv.const_string(2, si("android.intent.action.VIEW"))
        + dv.invoke_direct([1, 2, 0], mi(m["intent_init2"]))
        + dv.invoke_virtual([3, 1], mi(m["start_activity"]))
        + dv.return_void())

    # share(String): this=v3, s=v4; v1=intent, v2=str
    M(dx.primary, "share").code = (
        dv.new_instance(1, ti(INTENT))
        + dv.const_string(2, si("android.intent.action.SEND"))
        + dv.invoke_direct([1, 2], mi(m["intent_init1"]))
        + dv.const_string(2, si("text/plain"))
        + dv.invoke_virtual([1, 2], mi(m["intent_type"]))
        + dv.const_string(2, si("android.intent.extra.TEXT"))
        + dv.invoke_virtual([1, 2, 4], mi(m["intent_extra"]))
        + dv.invoke_virtual([3, 1], mi(m["start_activity"]))
        + dv.return_void())

    # copy(String): this=v3, s=v4; v0=str, v1=manager, v2=clip
    M(dx.primary, "copy").code = (
        dv.const_string(0, si("clipboard"))
        + dv.invoke_virtual([3, 0], mi(m["get_service"]))
        + dv.move_result_object(1)
        + dv.check_cast(1, ti(CLIPBOARD))
        + dv.const_string(0, si("text"))
        + dv.invoke_static([0, 4], mi(m["clip_new"]))
        + dv.move_result_object(2)
        + dv.invoke_virtual([1, 2], mi(m["clip_set"]))
        + dv.return_void())

    # ---------------- Client ----------------
    # <init>(Main): registers=2, this=v0, main=v1
    M(client, "<init>").code = (
        dv.invoke_direct([0], mi(m["wvc_init"]))
        + dv.iput_object(1, 0, fi(f_client_act))
        + dv.return_void())

    # shouldOverrideUrlLoading(WebView, String): registers=8, ins=3 ->
    # this=v5, web=v6, url=v7; v0=uri/int, v1=str, v2=str, v3=act, v4=value
    c = dv.Assembler()
    c.emit(dv.invoke_static([7], mi(m["uri_parse"])))
    c.emit(dv.move_result_object(0))
    c.emit(dv.invoke_virtual([0], mi(m["uri_scheme"])))
    c.emit(dv.move_result_object(1))
    c.emit(dv.const_string(2, si(BRIDGE_SCHEME)))
    c.emit(dv.invoke_virtual([2, 1], mi(m["str_equals"])))   # "app".equals(scheme)
    c.emit(dv.move_result(1))
    c.if_eqz(1, "not_ours")
    c.emit(dv.invoke_virtual([0], mi(m["uri_host"])))
    c.emit(dv.move_result_object(1))                          # v1 = command
    c.emit(dv.const_string(2, si(BRIDGE_PARAM)))
    c.emit(dv.invoke_virtual([0, 2], mi(m["uri_query"])))
    c.emit(dv.move_result_object(4))                          # v4 = value (may be null)
    c.if_nez(4, "have_value")
    c.emit(dv.const_string(4, si("")))
    c.label("have_value")
    c.emit(dv.iget_object(3, 5, fi(f_client_act)))
    for cmd in COMMANDS:
        c.emit(dv.const_string(2, si(cmd)))
        c.emit(dv.invoke_virtual([2, 1], mi(m["str_equals"])))
        c.emit(dv.move_result(0))
        c.if_eqz(0, f"skip_{cmd}")
        if cmd == "exit":
            c.emit(dv.invoke_virtual([3], mi(m["finish"])))
        else:
            c.emit(dv.invoke_virtual([3, 4], mi(m["main_" + cmd])))
        c.goto("handled")
        c.label(f"skip_{cmd}")
    c.label("handled")
    c.emit(dv.const4(0, 1))
    c.emit(dv.return_value(0))                                # true: consumed
    c.label("not_ours")
    c.emit(dv.const4(0, 0))
    c.emit(dv.return_value(0))                                # false: load it
    M(client, "shouldOverrideUrlLoading").code = c.assemble()

    # ---------------- Chrome ----------------
    M(chrome, "<init>").code = (
        dv.invoke_direct([0], mi(m["wcc_init"]))
        + dv.iput_object(1, 0, fi(f_chrome_act))
        + dv.return_void())

    # onJsAlert(WebView, String url, String message, JsResult): registers=8,
    # ins=5 -> this=v3, web=v4, url=v5, message=v6, result=v7; v0=act, v1=int
    M(chrome, "onJsAlert").code = (
        dv.iget_object(0, 3, fi(f_chrome_act))
        + dv.invoke_virtual([0, 6], mi(m["main_toast"]))
        + dv.invoke_virtual([7], mi(m["js_confirm"]))
        + dv.const4(1, 1)
        + dv.return_value(1))

    return dx.build()


def collect_assets(web_dir):
    """Read every file under web_dir into {"assets/<relative path>": bytes}.
    index.html is required. The bridge script is added automatically."""
    root = pathlib.Path(web_dir)
    if not (root / "index.html").is_file():
        raise WebAppError(f"{root} has no index.html")
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            out["assets/" + rel] = p.read_bytes()
    out.setdefault("assets/apkfs-bridge.js", BRIDGE_JS.encode("utf-8"))
    return out


def build_files(package, label, icon_rgb, assets, version_code=1,
                version_name="1.0"):
    """Assemble every file of a web-app APK. Returns {name: bytes}."""
    resources = arsc.build(PACKAGE_ID, package, [label, ICON_PATH], [
        {"name": "string", "keys": ["app_name"],
         "entries": [(0, arsc.TYPE_STRING, 0)]},
        {"name": "mipmap", "keys": ["ic_launcher"],
         "entries": [(0, arsc.TYPE_STRING, 1)]},
    ])
    manifest = axml.manifest(
        package, package + ".Main",
        label=axml.Ref(arsc.res_id(PACKAGE_ID, 1, 0)),
        icon=axml.Ref(arsc.res_id(PACKAGE_ID, 2, 0)),
        version_code=version_code, version_name=version_name,
        permissions=[INTERNET])
    files = {
        "AndroidManifest.xml": manifest,
        "classes.dex": build_dex(package),
        "resources.arsc": resources,
        ICON_PATH: png.solid_icon(rgb=icon_rgb),
    }
    files.update(assets)
    return files


def build_from_dir(web_dir, package, label="My Web App", icon_rgb=(0x1E, 0x88, 0xE5),
                   version_code=1, version_name="1.0", signing_key=None):
    """Build and sign a web-app APK from a folder containing index.html."""
    files = build_files(package, label, icon_rgb, collect_assets(web_dir),
                        version_code, version_name)
    if signing_key is None:
        key = apk.make_keypair()
        cert = apk.self_signed_cert(key)
    else:
        key, cert = signing_key
    return apk.sign(files, key, cert)


def build_from_html(html, package, label="My Web App", icon_rgb=(0x1E, 0x88, 0xE5),
                    version_code=1, version_name="1.0", signing_key=None):
    """Build and sign a web-app APK from a single HTML string."""
    assets = {"assets/index.html": html.encode("utf-8"),
              "assets/apkfs-bridge.js": BRIDGE_JS.encode("utf-8")}
    files = build_files(package, label, icon_rgb, assets, version_code, version_name)
    if signing_key is None:
        key = apk.make_keypair()
        cert = apk.self_signed_cert(key)
    else:
        key, cert = signing_key
    return apk.sign(files, key, cert)
