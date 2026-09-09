"""Build a real, interactive app from a plain JSON description — no code.

You describe the screen as a list of widgets; any widget can carry an action
that runs when it is tapped. The builder turns that into hand-assembled Dalvik
bytecode: a scrolling vertical layout holding the widgets, an onClick handler
that dispatches on the tapped view's id, and — for network fetches — a
background thread with exception handling that posts the result back to the
UI. Everything is still generated with no Android SDK.

Spec (JSON):

    {
      "package": "com.yourname.myapp",     # app id (reverse-domain)
      "name": "My App",                    # launcher label
      "icon_color": "1E88E5",              # 6 hex digits
      "version_code": 1, "version_name": "1.0",
      "widgets": [
        {"type": "text",   "id": "title", "text": "Hello!"},
        {"type": "image",  "src_url": "https://example.com/pic.png"},
        {"type": "button", "text": "Change", "action":
            {"type": "set_text", "target": "title", "text": "Changed!"}},
        {"type": "button", "text": "Load news", "action":
            {"type": "fetch", "url": "https://example.com/api", "target": "title"}},
        {"type": "list", "items": [
            {"text": "Apple"},
            {"text": "GitHub", "action": {"type": "open_url", "url": "https://github.com"}}
        ]}
      ]
    }

Widgets: "text", "button", "image" (src / src_url / src_base64), "list"
(items, each with text and an optional action). Actions: "set_text",
"open_url", "toast", "fetch" (download text from an https URL on a background
thread and show it in the target widget; errors are shown, not crashed on).
"""
import base64
import pathlib
import urllib.request

from apkfs import apk
from apkfs import arsc
from apkfs import axml
from apkfs import dalvik as dv
from apkfs import png
from apkfs.dex import DexBuilder, Method

# Android framework descriptors used by the generated class.
ACT = "Landroid/app/Activity;"
CTX = "Landroid/content/Context;"
VIEW = "Landroid/view/View;"
VIEWGROUP_LP = "Landroid/view/ViewGroup$LayoutParams;"
LINEAR_LP = "Landroid/widget/LinearLayout$LayoutParams;"
LISTENER = "Landroid/view/View$OnClickListener;"
RUNNABLE = "Ljava/lang/Runnable;"
SCROLL = "Landroid/widget/ScrollView;"
LAYOUT = "Landroid/widget/LinearLayout;"
TEXTVIEW = "Landroid/widget/TextView;"
BUTTON = "Landroid/widget/Button;"
IMAGEVIEW = "Landroid/widget/ImageView;"
INTENT = "Landroid/content/Intent;"
URI = "Landroid/net/Uri;"
TOAST = "Landroid/widget/Toast;"
THREAD = "Ljava/lang/Thread;"
URL = "Ljava/net/URL;"
URLCONN = "Ljava/net/URLConnection;"
INPUTSTREAM = "Ljava/io/InputStream;"
SCANNER = "Ljava/util/Scanner;"
THROWABLE = "Ljava/lang/Throwable;"
STR = "Ljava/lang/String;"
CHARSEQ = "Ljava/lang/CharSequence;"
BUNDLE = "Landroid/os/Bundle;"

ACTION_VIEW = "android.intent.action.VIEW"
SCANNER_WHOLE_INPUT = "\\A"      # Scanner delimiter that reads the whole stream
FIRST_VIEW_ID = 0x1000            # generated view ids: FIRST_VIEW_ID + index
VERTICAL = 1                      # LinearLayout.VERTICAL
MATCH_PARENT, WRAP_CONTENT = -1, -2
PACKAGE_ID = 0x7F
ICON_PATH = "res/mipmap/ic_launcher.png"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
INTERNET = "android.permission.INTERNET"

WIDGET_TYPES = ("text", "button", "image", "list")
ACTION_TYPES = ("set_text", "open_url", "toast", "fetch")


class SpecError(ValueError):
    """The spec is missing something or names an unknown widget/action."""


# --------------------------------------------------------------------------
# Spec model: flatten widgets (list items become their own rows) so the
# bytecode generator sees one flat sequence of "views", each with an index,
# a kind, text, and optional action.

class _Row:
    __slots__ = ("kind", "text", "action", "image_index", "spec_id")

    def __init__(self, kind, text="", action=None, image_index=None,
                 spec_id=None):
        self.kind = kind
        self.text = text
        self.action = action
        self.image_index = image_index
        self.spec_id = spec_id


def _validate_action(where, action, ids):
    atype = action.get("type")
    if atype == "set_text":
        if action.get("target") not in ids:
            raise SpecError(f'{where}: set_text target "{action.get("target")}" '
                            'is not a widget id')
        if "text" not in action:
            raise SpecError(f"{where}: set_text needs \"text\"")
    elif atype == "open_url":
        if not str(action.get("url", "")).startswith(("http://", "https://")):
            raise SpecError(f"{where}: open_url needs an http(s) url")
    elif atype == "toast":
        if "text" not in action:
            raise SpecError(f"{where}: toast needs \"text\"")
    elif atype == "fetch":
        if not str(action.get("url", "")).startswith("https://"):
            raise SpecError(f"{where}: fetch needs an https:// url")
        if action.get("target") not in ids:
            raise SpecError(f'{where}: fetch target "{action.get("target")}" '
                            'is not a widget id')
    else:
        raise SpecError(f'{where}: unknown action type "{atype}"')


def flatten(spec):
    """Validate the spec and return (rows, id_to_row_index, images).

    images: list of (source_kind, value) in row order for image widgets.
    """
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    pkg = spec.get("package")
    if not pkg or "." not in pkg:
        raise SpecError('"package" must be a reverse-domain id like com.me.app')
    widgets = spec.get("widgets")
    if not isinstance(widgets, list) or not widgets:
        raise SpecError('"widgets" must be a non-empty list')

    rows, ids, images = [], {}, []
    for i, w in enumerate(widgets):
        where = f"widget {i}"
        wtype = w.get("type")
        if wtype not in WIDGET_TYPES:
            raise SpecError(f'{where}: type must be one of {WIDGET_TYPES}')
        if wtype == "list":
            items = w.get("items")
            if not isinstance(items, list) or not items:
                raise SpecError(f'{where}: list needs a non-empty "items"')
            for j, item in enumerate(items):
                if "text" not in item:
                    raise SpecError(f'{where} item {j}: needs "text"')
                row = _Row("text", str(item["text"]), item.get("action"),
                           spec_id=item.get("id"))
                _register_id(ids, row, len(rows), f"{where} item {j}")
                rows.append(row)
            continue
        if wtype == "image":
            src_keys = [k for k in ("src", "src_url", "src_base64") if k in w]
            if len(src_keys) != 1:
                raise SpecError(f'{where}: image needs exactly one of '
                                '"src", "src_url", "src_base64"')
            images.append((src_keys[0], w[src_keys[0]]))
            row = _Row("image", "", w.get("action"), image_index=len(images) - 1,
                       spec_id=w.get("id"))
        else:
            if "text" not in w:
                raise SpecError(f'{where}: needs "text"')
            row = _Row(wtype, str(w["text"]), w.get("action"),
                       spec_id=w.get("id"))
        _register_id(ids, row, len(rows), where)
        rows.append(row)

    for idx, row in enumerate(rows):
        if row.action is not None:
            _validate_action(f"row {idx}", row.action, ids)
            if row.action["type"] in ("set_text", "fetch"):
                target_row = rows[ids[row.action["target"]]]
                if target_row.kind == "image":
                    raise SpecError(f"row {idx}: target must be a text/button, "
                                    "not an image")
    return rows, ids, images


def _register_id(ids, row, index, where):
    if row.spec_id is None:
        return
    if row.spec_id in ids:
        raise SpecError(f'{where}: duplicate widget id "{row.spec_id}"')
    ids[row.spec_id] = index


def validate(spec):
    """Validate a spec; returns the id -> row index map."""
    return flatten(spec)[1]


# --------------------------------------------------------------------------
# Images

def load_images(images, base_dir=None):
    """Resolve image sources to bytes. Returns a list of (file_name, bytes)."""
    out = []
    for n, (kind, value) in enumerate(images):
        if kind == "src":
            p = pathlib.Path(value)
            if base_dir is not None and not p.is_absolute():
                p = pathlib.Path(base_dir) / p
            data = p.read_bytes()
            ext = p.suffix.lower() or ".png"
        elif kind == "src_url":
            if not str(value).startswith("https://"):
                raise SpecError("image src_url must be https://")
            with urllib.request.urlopen(value, timeout=30) as r:
                data = r.read(MAX_IMAGE_BYTES + 1)
            ext = pathlib.Path(value.split("?")[0]).suffix.lower() or ".png"
        else:  # src_base64
            data = base64.b64decode(value)
            ext = ".png"
        if len(data) > MAX_IMAGE_BYTES:
            raise SpecError(f"image {n} is larger than {MAX_IMAGE_BYTES} bytes")
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"
        out.append((f"res/drawable/img{n}{ext}", data))
    return out


# --------------------------------------------------------------------------
# Bytecode

def build_dex(spec):
    """Generate classes.dex for the spec's single-screen app."""
    rows, ids, images = flatten(spec)
    package = spec["package"]
    class_desc = "L" + package.replace(".", "/") + "/Main;"
    uses_fetch = any(r.action and r.action["type"] == "fetch" for r in rows)
    has_images = bool(images)

    dx = DexBuilder(class_desc, ACT)
    dx.add_interface(LISTENER)
    if uses_fetch:
        dx.add_interface(RUNNABLE)
        f_mode = dx.add_instance_field("mode", "I")
        f_url = dx.add_instance_field("url", STR)
        f_result = dx.add_instance_field("result", STR)
        f_target = dx.add_instance_field("target", "I")

    # --- method references ---
    m = {}
    m["act_init"] = dx.methodref(ACT, "<init>", "V", [])
    m["on_create"] = dx.methodref(ACT, "onCreate", "V", [BUNDLE])
    m["set_content"] = dx.methodref(ACT, "setContentView", "V", [VIEW])
    m["find_view"] = dx.methodref(ACT, "findViewById", VIEW, ["I"])
    m["start_activity"] = dx.methodref(ACT, "startActivity", "V", [INTENT])
    m["scroll_init"] = dx.methodref(SCROLL, "<init>", "V", [CTX])
    m["scroll_add"] = dx.methodref(SCROLL, "addView", "V", [VIEW])
    m["layout_init"] = dx.methodref(LAYOUT, "<init>", "V", [CTX])
    m["set_orientation"] = dx.methodref(LAYOUT, "setOrientation", "V", ["I"])
    m["add_view"] = dx.methodref(LAYOUT, "addView", "V", [VIEW])
    m["tv_init"] = dx.methodref(TEXTVIEW, "<init>", "V", [CTX])
    m["tv_set_text"] = dx.methodref(TEXTVIEW, "setText", "V", [CHARSEQ])
    m["tv_set_id"] = dx.methodref(TEXTVIEW, "setId", "V", ["I"])
    m["tv_set_listener"] = dx.methodref(TEXTVIEW, "setOnClickListener", "V", [LISTENER])
    m["btn_init"] = dx.methodref(BUTTON, "<init>", "V", [CTX])
    m["btn_set_text"] = dx.methodref(BUTTON, "setText", "V", [CHARSEQ])
    m["btn_set_id"] = dx.methodref(BUTTON, "setId", "V", ["I"])
    m["btn_set_listener"] = dx.methodref(BUTTON, "setOnClickListener", "V", [LISTENER])
    m["get_id"] = dx.methodref(VIEW, "getId", "I", [])
    m["intent_init"] = dx.methodref(INTENT, "<init>", "V", [STR, URI])
    m["uri_parse"] = dx.methodref(URI, "parse", URI, [STR])
    m["toast_make"] = dx.methodref(TOAST, "makeText", TOAST, [CTX, CHARSEQ, "I"])
    m["toast_show"] = dx.methodref(TOAST, "show", "V", [])
    if has_images:
        m["img_init"] = dx.methodref(IMAGEVIEW, "<init>", "V", [CTX])
        m["img_set_res"] = dx.methodref(IMAGEVIEW, "setImageResource", "V", ["I"])
        m["img_adjust"] = dx.methodref(IMAGEVIEW, "setAdjustViewBounds", "V", ["Z"])
        m["img_set_id"] = dx.methodref(IMAGEVIEW, "setId", "V", ["I"])
        m["img_set_listener"] = dx.methodref(IMAGEVIEW, "setOnClickListener", "V", [LISTENER])
        m["lp_init"] = dx.methodref(LINEAR_LP, "<init>", "V", ["I", "I"])
        m["add_view_lp"] = dx.methodref(LAYOUT, "addView", "V", [VIEW, VIEWGROUP_LP])
    if uses_fetch:
        m["thread_init"] = dx.methodref(THREAD, "<init>", "V", [RUNNABLE])
        m["thread_start"] = dx.methodref(THREAD, "start", "V", [])
        m["url_init"] = dx.methodref(URL, "<init>", "V", [STR])
        m["url_open"] = dx.methodref(URL, "openConnection", URLCONN, [])
        m["conn_stream"] = dx.methodref(URLCONN, "getInputStream", INPUTSTREAM, [])
        m["scanner_init"] = dx.methodref(SCANNER, "<init>", "V", [INPUTSTREAM])
        m["scanner_delim"] = dx.methodref(SCANNER, "useDelimiter", SCANNER, [STR])
        m["scanner_has"] = dx.methodref(SCANNER, "hasNext", "Z", [])
        m["scanner_next"] = dx.methodref(SCANNER, "next", STR, [])
        m["throwable_str"] = dx.methodref(THROWABLE, "toString", STR, [])
        m["view_post"] = dx.methodref(VIEW, "post", "Z", [RUNNABLE])

    # --- strings and types used as operands ---
    for r in rows:
        if r.text:
            dx.str(r.text)
        if r.action:
            for k in ("text", "url"):
                if k in r.action:
                    dx.str(r.action[k])
    dx.str(ACTION_VIEW)
    dx.str("")
    if uses_fetch:
        dx.str(SCANNER_WHOLE_INPUT)
    for t in (SCROLL, LAYOUT, TEXTVIEW, BUTTON, INTENT):
        dx.type(t)
    if has_images:
        dx.type(IMAGEVIEW)
        dx.type(LINEAR_LP)
    if uses_fetch:
        for t in (THREAD, URL, SCANNER):
            dx.type(t)

    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", [BUNDLE]), 0x1, 8, 2, 3, b"",
                         direct=False))
    dx.add_method(Method("onClick", ("V", [VIEW]), 0x1, 8, 2, 3, b"",
                         direct=False))
    if uses_fetch:
        dx.add_method(Method("run", ("V", []), 0x1, 8, 1, 2, b"",
                             direct=False))
    dx.freeze()

    mi, si, ti, fi = dx.method_index, dx.string_index, dx.type_index, dx.field_index

    def view_id(index):
        return FIRST_VIEW_ID + index

    def drawable_res_id(image_index):
        # arsc types: 1 = string, 2 = mipmap, 3 = drawable
        return arsc.res_id(PACKAGE_ID, 3, image_index)

    # <init>(): this = v0.
    init = dv.invoke_direct([0], mi(m["act_init"])) + dv.return_void()

    # onCreate(Bundle): registers=8, ins=2 -> this=v6, state=v7.
    #   v0 = layout, v1 = current view, v2 = string, v3 = int, v4 = scroll,
    #   v5 = layout params
    a = dv.Assembler()
    a.emit(dv.invoke_super([6, 7], mi(m["on_create"])))
    a.emit(dv.new_instance(4, ti(SCROLL)))
    a.emit(dv.invoke_direct([4, 6], mi(m["scroll_init"])))
    a.emit(dv.new_instance(0, ti(LAYOUT)))
    a.emit(dv.invoke_direct([0, 6], mi(m["layout_init"])))
    a.emit(dv.const4(3, VERTICAL))
    a.emit(dv.invoke_virtual([0, 3], mi(m["set_orientation"])))
    for i, r in enumerate(rows):
        if r.kind == "image":
            a.emit(dv.new_instance(1, ti(IMAGEVIEW)))
            a.emit(dv.invoke_direct([1, 6], mi(m["img_init"])))
            a.emit(dv.const32(3, drawable_res_id(r.image_index)))
            a.emit(dv.invoke_virtual([1, 3], mi(m["img_set_res"])))
            a.emit(dv.const4(3, 1))
            a.emit(dv.invoke_virtual([1, 3], mi(m["img_adjust"])))   # scale to width
            a.emit(dv.const32(3, view_id(i)))
            a.emit(dv.invoke_virtual([1, 3], mi(m["img_set_id"])))
            if r.action:
                a.emit(dv.invoke_virtual([1, 6], mi(m["img_set_listener"])))
            # addView(view, new LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            a.emit(dv.new_instance(5, ti(LINEAR_LP)))
            a.emit(dv.const4(2, MATCH_PARENT))
            a.emit(dv.const4(3, WRAP_CONTENT))
            a.emit(dv.invoke_direct([5, 2, 3], mi(m["lp_init"])))
            a.emit(dv.invoke_virtual([0, 1, 5], mi(m["add_view_lp"])))
            continue
        is_button = r.kind == "button"
        p = "btn" if is_button else "tv"
        a.emit(dv.new_instance(1, ti(BUTTON if is_button else TEXTVIEW)))
        a.emit(dv.invoke_direct([1, 6], mi(m[p + "_init"])))
        a.emit(dv.const_string(2, si(r.text)))
        a.emit(dv.invoke_virtual([1, 2], mi(m[p + "_set_text"])))
        a.emit(dv.const32(3, view_id(i)))
        a.emit(dv.invoke_virtual([1, 3], mi(m[p + "_set_id"])))
        if r.action:
            a.emit(dv.invoke_virtual([1, 6], mi(m[p + "_set_listener"])))
        a.emit(dv.invoke_virtual([0, 1], mi(m["add_view"])))
    a.emit(dv.invoke_virtual([4, 0], mi(m["scroll_add"])))     # scroll.addView(layout)
    a.emit(dv.invoke_virtual([6, 4], mi(m["set_content"])))    # setContentView(scroll)
    a.emit(dv.return_void())
    on_create = a.assemble()

    # onClick(View): registers=8, ins=2 -> this=v6, view=v7.
    #   v0 = tapped id, v1 = id / int, v2 = string, v3 = object, v4 = int/Uri
    b = dv.Assembler()
    b.emit(dv.invoke_virtual([7], mi(m["get_id"])))
    b.emit(dv.move_result(0))
    for i, r in enumerate(rows):
        action = r.action
        if not action:
            continue
        skip = f"next_{i}"
        b.emit(dv.const32(1, view_id(i)))
        b.if_ne(0, 1, skip)
        atype = action["type"]
        if atype == "set_text":
            b.emit(dv.const32(1, view_id(ids[action["target"]])))
            b.emit(dv.invoke_virtual([6, 1], mi(m["find_view"])))
            b.emit(dv.move_result_object(3))
            b.emit(dv.check_cast(3, ti(TEXTVIEW)))
            b.emit(dv.const_string(2, si(action["text"])))
            b.emit(dv.invoke_virtual([3, 2], mi(m["tv_set_text"])))
        elif atype == "open_url":
            b.emit(dv.const_string(2, si(action["url"])))
            b.emit(dv.invoke_static([2], mi(m["uri_parse"])))
            b.emit(dv.move_result_object(4))
            b.emit(dv.new_instance(3, ti(INTENT)))
            b.emit(dv.const_string(2, si(ACTION_VIEW)))
            b.emit(dv.invoke_direct([3, 2, 4], mi(m["intent_init"])))
            b.emit(dv.invoke_virtual([6, 3], mi(m["start_activity"])))
        elif atype == "toast":
            b.emit(dv.const_string(2, si(action["text"])))
            b.emit(dv.const4(4, 0))                       # Toast.LENGTH_SHORT
            b.emit(dv.invoke_static([6, 2, 4], mi(m["toast_make"])))
            b.emit(dv.move_result_object(3))
            b.emit(dv.invoke_virtual([3], mi(m["toast_show"])))
        elif atype == "fetch":
            # Remember what to fetch and where to show it, then start a
            # background thread running this object's run() in mode 0.
            b.emit(dv.const_string(2, si(action["url"])))
            b.emit(dv.iput_object(2, 6, fi(f_url)))
            b.emit(dv.const32(1, view_id(ids[action["target"]])))
            b.emit(dv.iput(1, 6, fi(f_target)))
            b.emit(dv.const4(1, 0))
            b.emit(dv.iput(1, 6, fi(f_mode)))
            b.emit(dv.new_instance(3, ti(THREAD)))
            b.emit(dv.invoke_direct([3, 6], mi(m["thread_init"])))
            b.emit(dv.invoke_virtual([3], mi(m["thread_start"])))
        b.emit(dv.return_void())
        b.label(skip)
    b.emit(dv.return_void())
    on_click = b.assemble()

    tries = []
    run_code = b""
    if uses_fetch:
        # run(): registers=8, ins=1 -> this=v7. Mode 0 runs on the background
        # thread and downloads; it then posts itself (mode 1) to the UI thread,
        # where it writes the result into the target TextView.
        #   v0 = int/flag/exception, v1 = string, v2..v5 = objects
        c = dv.Assembler()
        c.emit(dv.iget(0, 7, fi(f_mode)))
        c.if_nez(0, "apply")
        c.label("try_start")
        c.emit(dv.iget_object(1, 7, fi(f_url)))
        c.emit(dv.new_instance(2, ti(URL)))
        c.emit(dv.invoke_direct([2, 1], mi(m["url_init"])))
        c.emit(dv.invoke_virtual([2], mi(m["url_open"])))
        c.emit(dv.move_result_object(3))
        c.emit(dv.invoke_virtual([3], mi(m["conn_stream"])))
        c.emit(dv.move_result_object(4))
        c.emit(dv.new_instance(5, ti(SCANNER)))
        c.emit(dv.invoke_direct([5, 4], mi(m["scanner_init"])))
        c.emit(dv.const_string(1, si(SCANNER_WHOLE_INPUT)))
        c.emit(dv.invoke_virtual([5, 1], mi(m["scanner_delim"])))
        c.emit(dv.move_result_object(5))
        c.emit(dv.invoke_virtual([5], mi(m["scanner_has"])))
        c.emit(dv.move_result(0))
        c.if_eqz(0, "empty")
        c.emit(dv.invoke_virtual([5], mi(m["scanner_next"])))
        c.emit(dv.move_result_object(1))
        c.goto("got")
        c.label("empty")
        c.emit(dv.const_string(1, si("")))
        c.label("got")
        c.emit(dv.iput_object(1, 7, fi(f_result)))
        c.label("try_end")
        c.goto("post")
        c.label("handler")
        c.emit(dv.move_exception(0))
        c.emit(dv.invoke_virtual([0], mi(m["throwable_str"])))
        c.emit(dv.move_result_object(1))
        c.emit(dv.iput_object(1, 7, fi(f_result)))
        c.label("post")
        c.emit(dv.const4(0, 1))
        c.emit(dv.iput(0, 7, fi(f_mode)))
        c.emit(dv.iget(1, 7, fi(f_target)))
        c.emit(dv.invoke_virtual([7, 1], mi(m["find_view"])))
        c.emit(dv.move_result_object(2))
        c.emit(dv.invoke_virtual([2, 7], mi(m["view_post"])))   # back to UI thread
        c.emit(dv.return_void())
        c.label("apply")
        c.emit(dv.iget(1, 7, fi(f_target)))
        c.emit(dv.invoke_virtual([7, 1], mi(m["find_view"])))
        c.emit(dv.move_result_object(2))
        c.emit(dv.check_cast(2, ti(TEXTVIEW)))
        c.emit(dv.iget_object(3, 7, fi(f_result)))
        c.emit(dv.invoke_virtual([2, 3], mi(m["tv_set_text"])))
        c.emit(dv.return_void())
        run_code = c.assemble()
        P = c.positions
        tries = [(P["try_start"], P["try_end"], P["handler"])]

    by_name = {mm.name: mm for mm in dx._defined}
    by_name["<init>"].code = init
    by_name["onCreate"].code = on_create
    by_name["onClick"].code = on_click
    if uses_fetch:
        by_name["run"].code = run_code
        by_name["run"].tries = tries
    return dx.build()


# --------------------------------------------------------------------------
# Whole APK

def build_files(spec, base_dir=None):
    """Assemble every file of the APK for a spec. Returns {name: bytes}."""
    rows, ids, images = flatten(spec)
    package = spec["package"]
    label = spec.get("name", "My App")
    from apkfs import apkforge
    rgb = apkforge._hex_color(spec.get("icon_color", "1E88E5"))

    image_files = load_images(images, base_dir)
    value_strings = [label, ICON_PATH] + [path for path, _ in image_files]
    types = [
        {"name": "string", "keys": ["app_name"],
         "entries": [(0, arsc.TYPE_STRING, 0)]},
        {"name": "mipmap", "keys": ["ic_launcher"],
         "entries": [(0, arsc.TYPE_STRING, 1)]},
    ]
    if image_files:
        types.append({
            "name": "drawable",
            "keys": [f"img{n}" for n in range(len(image_files))],
            "entries": [(n, arsc.TYPE_STRING, 2 + n)
                        for n in range(len(image_files))],
        })
    resources = arsc.build(PACKAGE_ID, package, value_strings, types)

    uses_fetch = any(r.action and r.action["type"] == "fetch" for r in rows)
    manifest = axml.manifest(
        package, package + ".Main",
        label=axml.Ref(arsc.res_id(PACKAGE_ID, 1, 0)),
        icon=axml.Ref(arsc.res_id(PACKAGE_ID, 2, 0)),
        version_code=int(spec.get("version_code", 1)),
        version_name=str(spec.get("version_name", "1.0")),
        permissions=[INTERNET] if uses_fetch else [])

    files = {
        "AndroidManifest.xml": manifest,
        "classes.dex": build_dex(spec),
        "resources.arsc": resources,
        ICON_PATH: png.solid_icon(rgb=rgb),
    }
    for path, data in image_files:
        files[path] = data
    return files


def build_from_spec(spec, signing_key=None, base_dir=None):
    """Build and sign a complete APK from a spec dict. Returns the bytes."""
    files = build_files(spec, base_dir)
    if signing_key is None:
        key = apk.make_keypair()
        cert = apk.self_signed_cert(key)
    else:
        key, cert = signing_key
    return apk.sign(files, key, cert)
