"""Turn a folder of HTML/CSS/JavaScript into a signed Android app.

This is the "no Android Studio" path for real apps. Instead of encoding every
feature as bytecode, the toolkit generates a small native host once — an
Activity holding a full-screen WebView — and your app is ordinary web code
bundled inside the APK under assets/. Forms, multiple screens, lists, images,
storage (localStorage), network (fetch), animation: anything a browser can do,
your app can do, and it installs like any other app.

The host also opens the doors a plain WebView keeps shut, so the *web
standard* device APIs work from your JavaScript:

  camera / microphone   navigator.mediaDevices.getUserMedia(...)
  photos / take photo   <input type="file" accept="image/*" capture>
  location              navigator.geolocation.getCurrentPosition(...)
  vibration             navigator.vibrate(200)
  notifications         App.notify("title", "text")   (local; shown by the OS)

Three hand-assembled classes make up the host (all generated with no SDK):

  Main   extends Activity      — creates the WebView (JavaScript, DOM storage,
                                  file access, geolocation on), asks for the
                                  runtime permissions the app declares, loads
                                  assets/index.html, and exposes native
                                  helpers: toast, openUrl, share, copy, notify.
                                  Back button walks web history; file-chooser
                                  results are handed back to the page.
  Client extends WebViewClient — intercepts navigations to app://<cmd>?v=...
                                  and runs the matching native helper; this
                                  is the JavaScript -> native bridge.
  Chrome extends WebChromeClient — makes alert() a toast, grants camera/mic
                                  and geolocation prompts, and opens the
                                  system file chooser for <input type=file>.

From JavaScript, include the generated apkfs-bridge.js and call:

    App.toast("hi")   App.open("https://...")   App.share("text")
    App.copy("text")  App.notify("title", "text")  App.exit()

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
PERMREQ = "Landroid/webkit/PermissionRequest;"
GEO_CALLBACK = "Landroid/webkit/GeolocationPermissions$Callback;"
VALUE_CALLBACK = "Landroid/webkit/ValueCallback;"
FILE_PARAMS = "Landroid/webkit/WebChromeClient$FileChooserParams;"
INTENT = "Landroid/content/Intent;"
URI = "Landroid/net/Uri;"
URI_ARRAY = "[Landroid/net/Uri;"
TOAST = "Landroid/widget/Toast;"
CLIPBOARD = "Landroid/content/ClipboardManager;"
CLIPDATA = "Landroid/content/ClipData;"
NOTIF_MGR = "Landroid/app/NotificationManager;"
NOTIF_CHANNEL = "Landroid/app/NotificationChannel;"
NOTIF_BUILDER = "Landroid/app/Notification$Builder;"
NOTIFICATION = "Landroid/app/Notification;"
BUILD_VERSION = "Landroid/os/Build$VERSION;"
OBJECT = "Ljava/lang/Object;"
STR = "Ljava/lang/String;"
STR_ARRAY = "[Ljava/lang/String;"
CHARSEQ = "Ljava/lang/CharSequence;"

INDEX_URL = "file:///android_asset/index.html"
BRIDGE_SCHEME = "app"
BRIDGE_PARAM = "v"
BRIDGE_TITLE_PARAM = "t"
PACKAGE_ID = 0x7F
ICON_PATH = "res/mipmap/ic_launcher.png"
ICON_RES_ID = 0x7F020000              # @mipmap/ic_launcher, used as notification icon
NOTIF_CHANNEL_ID = "app"
NOTIF_IMPORTANCE_DEFAULT = 3
NOTIF_REQUEST_CODE = 1
FILE_CHOOSER_REQUEST = 1
PERMISSION_REQUEST = 1
API_OREO = 26

# Friendly permission names -> Android permissions. "internet" is always on.
PERMISSIONS = {
    "internet": ["android.permission.INTERNET"],
    "camera": ["android.permission.CAMERA"],
    "mic": ["android.permission.RECORD_AUDIO"],
    "location": ["android.permission.ACCESS_FINE_LOCATION",
                 "android.permission.ACCESS_COARSE_LOCATION"],
    "vibrate": ["android.permission.VIBRATE"],
    "notify": [],   # local notifications need no permission below API 33
}
# Permissions Android makes the user approve at runtime (API 23+).
RUNTIME_PERMISSIONS = {
    "android.permission.CAMERA", "android.permission.RECORD_AUDIO",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
}

BRIDGE_JS = """\
// apkfs bridge: call native features from JavaScript.
// Navigating to app://<command>?v=<value> is intercepted by the native host.
(function () {
  function go(cmd, value, title) {
    var v = value == null ? "" : String(value);
    var t = title == null ? "" : String(title);
    location.href = "app://" + cmd + "?v=" + encodeURIComponent(v) +
                    "&t=" + encodeURIComponent(t);
  }
  window.App = {
    toast:  function (text)        { go("toast", text); },      // short popup
    open:   function (url)         { go("open", url); },        // in the browser
    share:  function (text)        { go("share", text); },      // share sheet
    copy:   function (text)        { go("copy", text); },       // clipboard
    notify: function (title, text) { go("notify", text, title); }, // OS notification
    exit:   function ()            { go("exit", ""); }          // close the app
  };
  // Device features use the web standard APIs directly; the host grants them:
  //   navigator.mediaDevices.getUserMedia({video:true})   camera (needs "camera")
  //   navigator.geolocation.getCurrentPosition(cb)        location (needs "location")
  //   navigator.vibrate(200)                              vibration (needs "vibrate")
  //   <input type="file" accept="image/*" capture>        photo / take a photo
})();
"""

COMMANDS = ("toast", "open", "share", "copy", "notify", "exit")


class WebAppError(ValueError):
    pass


def resolve_permissions(names):
    """Map friendly names (camera, mic, location, vibrate, notify) to Android
    permission strings. Returns (all_permissions, runtime_permissions)."""
    perms = list(PERMISSIONS["internet"])
    for n in names or ():
        if n not in PERMISSIONS:
            raise WebAppError(f'unknown permission "{n}"; choose from '
                              f'{", ".join(k for k in PERMISSIONS if k != "internet")}')
        for p in PERMISSIONS[n]:
            if p not in perms:
                perms.append(p)
    runtime = [p for p in perms if p in RUNTIME_PERMISSIONS]
    return perms, runtime


def build_dex(package, runtime_permissions=()):
    """Generate classes.dex for the WebView host: Main, Client, Chrome."""
    base = "L" + package.replace(".", "/") + "/"
    MAIN, CLIENT, CHROME = base + "Main;", base + "Client;", base + "Chrome;"
    runtime_permissions = list(runtime_permissions)

    dx = DexBuilder(MAIN, ACT)
    client = dx.add_class(CLIENT, WEBVIEWCLIENT)
    chrome = dx.add_class(CHROME, WEBCHROMECLIENT)

    f_web = dx.add_instance_field("web", WEBVIEW)
    f_file_cb = dx.add_instance_field("fileCb", VALUE_CALLBACK)
    f_client_act = client.add_instance_field("act", MAIN)
    f_chrome_act = chrome.add_instance_field("act", MAIN)
    f_sdk_int = dx.fieldref(BUILD_VERSION, "SDK_INT", "I")

    m = {}
    # Activity
    m["act_init"] = dx.methodref(ACT, "<init>", "V", [])
    m["on_create"] = dx.methodref(ACT, "onCreate", "V", [BUNDLE])
    m["on_back"] = dx.methodref(ACT, "onBackPressed", "V", [])
    m["on_result"] = dx.methodref(ACT, "onActivityResult", "V", ["I", "I", INTENT])
    m["set_content"] = dx.methodref(ACT, "setContentView", "V", [VIEW])
    m["start_activity"] = dx.methodref(ACT, "startActivity", "V", [INTENT])
    m["start_for_result"] = dx.methodref(ACT, "startActivityForResult", "V", [INTENT, "I"])
    m["request_perms"] = dx.methodref(ACT, "requestPermissions", "V", [STR_ARRAY, "I"])
    m["finish"] = dx.methodref(ACT, "finish", "V", [])
    m["get_service"] = dx.methodref(ACT, "getSystemService", OBJECT, [STR])
    # WebView + settings
    m["wv_init"] = dx.methodref(WEBVIEW, "<init>", "V", [CTX])
    m["wv_settings"] = dx.methodref(WEBVIEW, "getSettings", WEBSETTINGS, [])
    m["wv_set_client"] = dx.methodref(WEBVIEW, "setWebViewClient", "V", [WEBVIEWCLIENT])
    m["wv_set_chrome"] = dx.methodref(WEBVIEW, "setWebChromeClient", "V", [WEBCHROMECLIENT])
    m["wv_load"] = dx.methodref(WEBVIEW, "loadUrl", "V", [STR])
    m["wv_can_back"] = dx.methodref(WEBVIEW, "canGoBack", "Z", [])
    m["wv_back"] = dx.methodref(WEBVIEW, "goBack", "V", [])
    for key, name in (("ws_js", "setJavaScriptEnabled"),
                      ("ws_dom", "setDomStorageEnabled"),
                      ("ws_file", "setAllowFileAccess"),
                      ("ws_universal", "setAllowUniversalAccessFromFileURLs"),
                      ("ws_geo", "setGeolocationEnabled")):
        m[key] = dx.methodref(WEBSETTINGS, name, "V", ["Z"])
    m["ws_media"] = dx.methodref(WEBSETTINGS, "setMediaPlaybackRequiresUserGesture", "V", ["Z"])
    # clients and callbacks
    m["wvc_init"] = dx.methodref(WEBVIEWCLIENT, "<init>", "V", [])
    m["wcc_init"] = dx.methodref(WEBCHROMECLIENT, "<init>", "V", [])
    m["js_confirm"] = dx.methodref(JSRESULT, "confirm", "V", [])
    m["perm_resources"] = dx.methodref(PERMREQ, "getResources", STR_ARRAY, [])
    m["perm_grant"] = dx.methodref(PERMREQ, "grant", "V", [STR_ARRAY])
    m["geo_invoke"] = dx.methodref(GEO_CALLBACK, "invoke", "V", [STR, "Z", "Z"])
    m["params_intent"] = dx.methodref(FILE_PARAMS, "createIntent", INTENT, [])
    m["params_parse"] = dx.methodref(FILE_PARAMS, "parseResult", URI_ARRAY, ["I", INTENT])
    m["cb_receive"] = dx.methodref(VALUE_CALLBACK, "onReceiveValue", "V", [OBJECT])
    # misc framework
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
    m["chan_init"] = dx.methodref(NOTIF_CHANNEL, "<init>", "V", [STR, CHARSEQ, "I"])
    m["nm_channel"] = dx.methodref(NOTIF_MGR, "createNotificationChannel", "V", [NOTIF_CHANNEL])
    m["nm_notify"] = dx.methodref(NOTIF_MGR, "notify", "V", ["I", NOTIFICATION])
    m["nb_init"] = dx.methodref(NOTIF_BUILDER, "<init>", "V", [CTX, STR])
    m["nb_title"] = dx.methodref(NOTIF_BUILDER, "setContentTitle", NOTIF_BUILDER, [CHARSEQ])
    m["nb_text"] = dx.methodref(NOTIF_BUILDER, "setContentText", NOTIF_BUILDER, [CHARSEQ])
    m["nb_icon"] = dx.methodref(NOTIF_BUILDER, "setSmallIcon", NOTIF_BUILDER, ["I"])
    m["nb_build"] = dx.methodref(NOTIF_BUILDER, "build", NOTIFICATION, [])
    # our own
    m["client_init"] = dx.methodref(CLIENT, "<init>", "V", [MAIN])
    m["chrome_init"] = dx.methodref(CHROME, "<init>", "V", [MAIN])
    m["main_toast"] = dx.methodref(MAIN, "toast", "V", [STR])
    m["main_open"] = dx.methodref(MAIN, "openUrl", "V", [STR])
    m["main_share"] = dx.methodref(MAIN, "share", "V", [STR])
    m["main_copy"] = dx.methodref(MAIN, "copy", "V", [STR])
    m["main_notify"] = dx.methodref(MAIN, "notify", "V", [STR, STR])

    strings = [INDEX_URL, BRIDGE_SCHEME, BRIDGE_PARAM, BRIDGE_TITLE_PARAM, "",
               "android.intent.action.VIEW", "android.intent.action.SEND",
               "text/plain", "android.intent.extra.TEXT", "clipboard", "text",
               "notification", NOTIF_CHANNEL_ID] + list(COMMANDS) + runtime_permissions
    for s in strings:
        dx.str(s)
    for t in (WEBVIEW, INTENT, CLIENT, CHROME, CLIPBOARD, STR_ARRAY,
              NOTIF_MGR, NOTIF_CHANNEL, NOTIF_BUILDER):
        dx.type(t)

    # --- declare methods (code filled in after freeze) ---
    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", [BUNDLE]), 0x1, 8, 2, 3, b"", direct=False))
    dx.add_method(Method("onBackPressed", ("V", []), 0x1, 3, 1, 1, b"", direct=False))
    dx.add_method(Method("onActivityResult", ("V", ["I", "I", INTENT]), 0x1, 8, 4, 4, b"", direct=False))
    dx.add_method(Method("toast", ("V", [STR]), 0x1, 5, 2, 3, b"", direct=False))
    dx.add_method(Method("openUrl", ("V", [STR]), 0x1, 5, 2, 3, b"", direct=False))
    dx.add_method(Method("share", ("V", [STR]), 0x1, 5, 2, 3, b"", direct=False))
    dx.add_method(Method("copy", ("V", [STR]), 0x1, 5, 2, 2, b"", direct=False))
    dx.add_method(Method("notify", ("V", [STR, STR]), 0x1, 8, 3, 4, b"", direct=False))
    client.add_method(Method("<init>", ("V", [MAIN]), 0x10001, 2, 2, 1, b""))
    client.add_method(Method("shouldOverrideUrlLoading", ("Z", [WEBVIEW, STR]),
                             0x1, 8, 3, 3, b"", direct=False))
    chrome.add_method(Method("<init>", ("V", [MAIN]), 0x10001, 2, 2, 1, b""))
    chrome.add_method(Method("onJsAlert", ("Z", [WEBVIEW, STR, STR, JSRESULT]),
                             0x1, 8, 5, 2, b"", direct=False))
    chrome.add_method(Method("onPermissionRequest", ("V", [PERMREQ]),
                             0x1, 3, 2, 2, b"", direct=False))
    chrome.add_method(Method("onGeolocationPermissionsShowPrompt", ("V", [STR, GEO_CALLBACK]),
                             0x1, 5, 3, 4, b"", direct=False))
    chrome.add_method(Method("onShowFileChooser", ("Z", [WEBVIEW, VALUE_CALLBACK, FILE_PARAMS]),
                             0x1, 8, 4, 3, b"", direct=False))
    dx.freeze()
    mi, si, ti, fi = dx.method_index, dx.string_index, dx.type_index, dx.field_index

    def M(cls, name):
        return {mm.name: mm for mm in cls.methods}[name]

    # ---------------- Main ----------------
    M(dx.primary, "<init>").code = dv.invoke_direct([0], mi(m["act_init"])) + dv.return_void()

    # onCreate: registers=8, this=v6, bundle=v7; v0=web, v1=settings, v2=int,
    # v3=string/array, v4=client/chrome, v5=string
    a = dv.Assembler()
    a.emit(dv.invoke_super([6, 7], mi(m["on_create"])))
    if runtime_permissions:
        # requestPermissions(new String[]{...}, PERMISSION_REQUEST)
        a.emit(dv.const4(2, len(runtime_permissions)))
        a.emit(dv.new_array(3, 2, ti(STR_ARRAY)))
        for i, perm in enumerate(runtime_permissions):
            a.emit(dv.const4(2, i))
            a.emit(dv.const_string(5, si(perm)))
            a.emit(dv.aput_object(5, 3, 2))
        a.emit(dv.const4(2, PERMISSION_REQUEST))
        a.emit(dv.invoke_virtual([6, 3, 2], mi(m["request_perms"])))
    a.emit(dv.new_instance(0, ti(WEBVIEW)))
    a.emit(dv.invoke_direct([0, 6], mi(m["wv_init"])))
    a.emit(dv.iput_object(0, 6, fi(f_web)))
    a.emit(dv.invoke_virtual([0], mi(m["wv_settings"])))
    a.emit(dv.move_result_object(1))
    a.emit(dv.const4(2, 1))
    for key in ("ws_js", "ws_dom", "ws_file", "ws_universal", "ws_geo"):
        a.emit(dv.invoke_virtual([1, 2], mi(m[key])))
    a.emit(dv.const4(2, 0))
    a.emit(dv.invoke_virtual([1, 2], mi(m["ws_media"])))   # autoplay camera preview
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

    # onActivityResult(req, res, data): registers=8, ins=4 -> this=v4,
    # req=v5, res=v6, data=v7; v0=callback, v1=uris, v2=null
    r = dv.Assembler()
    r.emit(dv.invoke_super([4, 5, 6, 7], mi(m["on_result"])))
    r.emit(dv.iget_object(0, 4, fi(f_file_cb)))
    r.if_eqz(0, "done")
    r.emit(dv.invoke_static([6, 7], mi(m["params_parse"])))   # Uri[] or null
    r.emit(dv.move_result_object(1))
    r.emit(dv.invoke_interface([0, 1], mi(m["cb_receive"])))  # hand to the page
    r.emit(dv.const4(2, 0))
    r.emit(dv.iput_object(2, 4, fi(f_file_cb)))                # fileCb = null
    r.label("done")
    r.emit(dv.return_void())
    M(dx.primary, "onActivityResult").code = r.assemble()

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

    # notify(title, text): registers=8, ins=3 -> this=v5, title=v6, text=v7;
    # v0=int/str, v1=manager, v2=channel/builder, v3=str/notification, v4=int
    # Notification channels exist from API 26; older devices get a toast.
    n = dv.Assembler()
    n.emit(dv.sget(0, fi(f_sdk_int)))
    n.emit(dv.const16(1, API_OREO))
    n.if_lt(0, 1, "fallback")
    n.emit(dv.const_string(0, si("notification")))
    n.emit(dv.invoke_virtual([5, 0], mi(m["get_service"])))
    n.emit(dv.move_result_object(1))
    n.emit(dv.check_cast(1, ti(NOTIF_MGR)))
    n.emit(dv.new_instance(2, ti(NOTIF_CHANNEL)))
    n.emit(dv.const_string(3, si(NOTIF_CHANNEL_ID)))
    n.emit(dv.const4(4, NOTIF_IMPORTANCE_DEFAULT))
    n.emit(dv.invoke_direct([2, 3, 3, 4], mi(m["chan_init"])))     # (id, name, importance)
    n.emit(dv.invoke_virtual([1, 2], mi(m["nm_channel"])))
    n.emit(dv.new_instance(2, ti(NOTIF_BUILDER)))
    n.emit(dv.invoke_direct([2, 5, 3], mi(m["nb_init"])))          # Builder(ctx, channel)
    n.emit(dv.invoke_virtual([2, 6], mi(m["nb_title"])))
    n.emit(dv.invoke_virtual([2, 7], mi(m["nb_text"])))
    n.emit(dv.const32(4, ICON_RES_ID))
    n.emit(dv.invoke_virtual([2, 4], mi(m["nb_icon"])))
    n.emit(dv.invoke_virtual([2], mi(m["nb_build"])))
    n.emit(dv.move_result_object(3))
    n.emit(dv.const4(4, NOTIF_REQUEST_CODE))
    n.emit(dv.invoke_virtual([1, 4, 3], mi(m["nm_notify"])))
    n.emit(dv.return_void())
    n.label("fallback")
    n.emit(dv.invoke_virtual([5, 7], mi(m["main_toast"])))
    n.emit(dv.return_void())
    M(dx.primary, "notify").code = n.assemble()

    # ---------------- Client ----------------
    M(client, "<init>").code = (
        dv.invoke_direct([0], mi(m["wvc_init"]))
        + dv.iput_object(1, 0, fi(f_client_act))
        + dv.return_void())

    # shouldOverrideUrlLoading(WebView, String): registers=8, ins=3 ->
    # this=v5, web=v6, url=v7; v0=uri, v1=command, v2=scratch, v3=act, v4=value
    c = dv.Assembler()
    c.emit(dv.invoke_static([7], mi(m["uri_parse"])))
    c.emit(dv.move_result_object(0))
    c.emit(dv.invoke_virtual([0], mi(m["uri_scheme"])))
    c.emit(dv.move_result_object(1))
    c.emit(dv.const_string(2, si(BRIDGE_SCHEME)))
    c.emit(dv.invoke_virtual([2, 1], mi(m["str_equals"])))   # "app".equals(scheme)
    c.emit(dv.move_result(2))
    c.if_eqz(2, "not_ours")
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
        c.emit(dv.move_result(2))
        c.if_eqz(2, f"skip_{cmd}")
        if cmd == "exit":
            c.emit(dv.invoke_virtual([3], mi(m["finish"])))
        elif cmd == "notify":
            c.emit(dv.const_string(2, si(BRIDGE_TITLE_PARAM)))
            c.emit(dv.invoke_virtual([0, 2], mi(m["uri_query"])))
            c.emit(dv.move_result_object(2))                  # v2 = title (may be null)
            c.if_nez(2, "have_title")
            c.emit(dv.const_string(2, si("")))
            c.label("have_title")
            c.emit(dv.invoke_virtual([3, 2, 4], mi(m["main_notify"])))
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

    # onJsAlert(WebView, url, message, JsResult): registers=8, ins=5 ->
    # this=v3, web=v4, url=v5, message=v6, result=v7; v0=act, v1=int
    M(chrome, "onJsAlert").code = (
        dv.iget_object(0, 3, fi(f_chrome_act))
        + dv.invoke_virtual([0, 6], mi(m["main_toast"]))
        + dv.invoke_virtual([7], mi(m["js_confirm"]))
        + dv.const4(1, 1)
        + dv.return_value(1))

    # onPermissionRequest(PermissionRequest): registers=3, ins=2 -> this=v1,
    # request=v2; v0=resources. Grants camera/mic to the page (the OS-level
    # runtime permission was requested in onCreate).
    M(chrome, "onPermissionRequest").code = (
        dv.invoke_virtual([2], mi(m["perm_resources"]))
        + dv.move_result_object(0)
        + dv.invoke_virtual([2, 0], mi(m["perm_grant"]))
        + dv.return_void())

    # onGeolocationPermissionsShowPrompt(origin, callback): registers=5,
    # ins=3 -> this=v2, origin=v3, callback=v4; v0=true, v1=false
    M(chrome, "onGeolocationPermissionsShowPrompt").code = (
        dv.const4(0, 1)
        + dv.const4(1, 0)
        + dv.invoke_interface([4, 3, 0, 1], mi(m["geo_invoke"]))   # allow, don't retain
        + dv.return_void())

    # onShowFileChooser(WebView, ValueCallback, FileChooserParams): registers=8,
    # ins=4 -> this=v4, web=v5, callback=v6, params=v7; v0=act, v1=intent, v2=int
    M(chrome, "onShowFileChooser").code = (
        dv.iget_object(0, 4, fi(f_chrome_act))
        + dv.iput_object(6, 0, fi(f_file_cb))                     # remember callback
        + dv.invoke_virtual([7], mi(m["params_intent"]))
        + dv.move_result_object(1)
        + dv.const4(2, FILE_CHOOSER_REQUEST)
        + dv.invoke_virtual([0, 1, 2], mi(m["start_for_result"]))
        + dv.const4(2, 1)
        + dv.return_value(2))

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
                version_name="1.0", permissions=(), icon_png=None,
                min_sdk=23, target_sdk=28):
    """Assemble every file of a web-app APK. Returns {name: bytes}.
    permissions: friendly names (camera, mic, location, vibrate, notify)."""
    all_perms, runtime = resolve_permissions(permissions)
    resources = arsc.build(PACKAGE_ID, package, [label, ICON_PATH], [
        {"name": "string", "keys": ["app_name"],
         "entries": [(0, arsc.TYPE_STRING, 0)]},
        {"name": "mipmap", "keys": ["ic_launcher"],
         "entries": [(0, arsc.TYPE_STRING, 1)]},
    ])
    manifest = axml.manifest(
        package, package + ".Main", min_sdk=min_sdk, target_sdk=target_sdk,
        label=axml.Ref(arsc.res_id(PACKAGE_ID, 1, 0)),
        icon=axml.Ref(arsc.res_id(PACKAGE_ID, 2, 0)),
        version_code=version_code, version_name=version_name,
        permissions=all_perms)
    from apkfs.apkforge import icon_bytes
    files = {
        "AndroidManifest.xml": manifest,
        "classes.dex": build_dex(package, runtime),
        "resources.arsc": resources,
        ICON_PATH: icon_bytes(icon_rgb, icon_png),
    }
    files.update(assets)
    return files


def _sign(files, signing_key):
    if signing_key is None:
        key = apk.make_keypair()
        cert = apk.self_signed_cert(key)
    else:
        key, cert = signing_key
    return apk.sign(files, key, cert)


def build_from_dir(web_dir, package, label="My Web App", icon_rgb=(0x1E, 0x88, 0xE5),
                   version_code=1, version_name="1.0", signing_key=None,
                   permissions=(), icon_png=None, min_sdk=23, target_sdk=28):
    """Build and sign a web-app APK from a folder containing index.html."""
    files = build_files(package, label, icon_rgb, collect_assets(web_dir),
                        version_code, version_name, permissions, icon_png,
                        min_sdk, target_sdk)
    return _sign(files, signing_key)


def build_from_html(html, package, label="My Web App", icon_rgb=(0x1E, 0x88, 0xE5),
                    version_code=1, version_name="1.0", signing_key=None,
                    permissions=(), icon_png=None, min_sdk=23, target_sdk=28):
    """Build and sign a web-app APK from a single HTML string."""
    assets = {"assets/index.html": html.encode("utf-8"),
              "assets/apkfs-bridge.js": BRIDGE_JS.encode("utf-8")}
    files = build_files(package, label, icon_rgb, assets, version_code,
                        version_name, permissions, icon_png, min_sdk, target_sdk)
    return _sign(files, signing_key)
