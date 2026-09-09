"""Build a real, interactive app from a plain JSON description — no code.

You describe the screen as a list of widgets; buttons can carry an action.
The builder turns that into hand-assembled Dalvik bytecode: a vertical
LinearLayout holding the widgets, and an onClick handler that dispatches on
the tapped view's id to run the action. Everything is still generated with no
Android SDK.

Spec (JSON):

    {
      "package": "com.yourname.myapp",     # app id (reverse-domain)
      "name": "My App",                    # launcher label
      "icon_color": "1E88E5",              # 6 hex digits
      "version_code": 1, "version_name": "1.0",
      "widgets": [
        {"type": "text",   "id": "title", "text": "Hello!"},
        {"type": "button", "text": "Change", "action":
            {"type": "set_text", "target": "title", "text": "Changed!"}},
        {"type": "button", "text": "Open site", "action":
            {"type": "open_url", "url": "https://example.com"}},
        {"type": "button", "text": "Say hi", "action":
            {"type": "toast", "text": "Hi there!"}}
      ]
    }

Widget types: "text", "button". Actions: "set_text" (change another widget's
text), "open_url" (open in the browser), "toast" (short popup message).
"""
from apkfs import apk
from apkfs import dalvik as dv
from apkfs.dex import DexBuilder, Method

# Android framework descriptors used by the generated class.
ACT = "Landroid/app/Activity;"
CTX = "Landroid/content/Context;"
VIEW = "Landroid/view/View;"
LISTENER = "Landroid/view/View$OnClickListener;"
LAYOUT = "Landroid/widget/LinearLayout;"
TEXTVIEW = "Landroid/widget/TextView;"
BUTTON = "Landroid/widget/Button;"
INTENT = "Landroid/content/Intent;"
URI = "Landroid/net/Uri;"
TOAST = "Landroid/widget/Toast;"
STR = "Ljava/lang/String;"
CHARSEQ = "Ljava/lang/CharSequence;"
BUNDLE = "Landroid/os/Bundle;"

ACTION_VIEW = "android.intent.action.VIEW"
FIRST_VIEW_ID = 0x1000          # generated widget ids: FIRST_VIEW_ID + index
VERTICAL = 1                    # LinearLayout.VERTICAL


class SpecError(ValueError):
    """The spec is missing something or names an unknown widget/action."""


def validate(spec):
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    pkg = spec.get("package")
    if not pkg or "." not in pkg:
        raise SpecError('"package" must be a reverse-domain id like com.me.app')
    widgets = spec.get("widgets")
    if not isinstance(widgets, list) or not widgets:
        raise SpecError('"widgets" must be a non-empty list')
    ids = {}
    for i, w in enumerate(widgets):
        wtype = w.get("type")
        if wtype not in ("text", "button"):
            raise SpecError(f'widget {i}: type must be "text" or "button"')
        if "text" not in w:
            raise SpecError(f'widget {i}: needs "text"')
        if "id" in w:
            if w["id"] in ids:
                raise SpecError(f'duplicate widget id "{w["id"]}"')
            ids[w["id"]] = i
    for i, w in enumerate(widgets):
        action = w.get("action")
        if action is None:
            continue
        if w["type"] != "button":
            raise SpecError(f'widget {i}: only buttons can have an action')
        atype = action.get("type")
        if atype == "set_text":
            if action.get("target") not in ids:
                raise SpecError(f'widget {i}: set_text target "{action.get("target")}" '
                                'is not a widget id')
            if "text" not in action:
                raise SpecError(f'widget {i}: set_text needs "text"')
        elif atype == "open_url":
            if not str(action.get("url", "")).startswith(("http://", "https://")):
                raise SpecError(f'widget {i}: open_url needs an http(s) url')
        elif atype == "toast":
            if "text" not in action:
                raise SpecError(f'widget {i}: toast needs "text"')
        else:
            raise SpecError(f'widget {i}: unknown action type "{atype}"')
    return ids


def build_dex(spec):
    """Generate classes.dex for the spec's single-screen app."""
    ids = validate(spec)
    widgets = spec["widgets"]
    package = spec["package"]
    class_desc = "L" + package.replace(".", "/") + "/Main;"

    dx = DexBuilder(class_desc, ACT)
    dx.add_interface(LISTENER)

    # --- method references ---
    m_act_init = dx.methodref(ACT, "<init>", "V", [])
    m_on_create = dx.methodref(ACT, "onCreate", "V", [BUNDLE])
    m_set_content = dx.methodref(ACT, "setContentView", "V", [VIEW])
    m_find_view = dx.methodref(ACT, "findViewById", VIEW, ["I"])
    m_start_activity = dx.methodref(ACT, "startActivity", "V", [INTENT])
    m_layout_init = dx.methodref(LAYOUT, "<init>", "V", [CTX])
    m_set_orientation = dx.methodref(LAYOUT, "setOrientation", "V", ["I"])
    m_add_view = dx.methodref(LAYOUT, "addView", "V", [VIEW])
    m_tv_init = dx.methodref(TEXTVIEW, "<init>", "V", [CTX])
    m_tv_set_text = dx.methodref(TEXTVIEW, "setText", "V", [CHARSEQ])
    m_tv_set_id = dx.methodref(TEXTVIEW, "setId", "V", ["I"])
    m_btn_init = dx.methodref(BUTTON, "<init>", "V", [CTX])
    m_btn_set_text = dx.methodref(BUTTON, "setText", "V", [CHARSEQ])
    m_btn_set_id = dx.methodref(BUTTON, "setId", "V", ["I"])
    m_btn_set_listener = dx.methodref(BUTTON, "setOnClickListener", "V", [LISTENER])
    m_get_id = dx.methodref(VIEW, "getId", "I", [])
    m_intent_init = dx.methodref(INTENT, "<init>", "V", [STR, URI])
    m_uri_parse = dx.methodref(URI, "parse", URI, [STR])
    m_toast_make = dx.methodref(TOAST, "makeText", TOAST, [CTX, CHARSEQ, "I"])
    m_toast_show = dx.methodref(TOAST, "show", "V", [])

    # --- strings and types used as operands ---
    for w in widgets:
        dx.str(w["text"])
        a = w.get("action")
        if a:
            for k in ("text", "url"):
                if k in a:
                    dx.str(a[k])
    dx.str(ACTION_VIEW)
    for t in (LAYOUT, TEXTVIEW, BUTTON, INTENT):
        dx.type(t)

    dx.add_method(Method("<init>", ("V", []), 0x10001, 1, 1, 1, b""))
    dx.add_method(Method("onCreate", ("V", [BUNDLE]), 0x1, 8, 2, 2, b"",
                         direct=False))
    dx.add_method(Method("onClick", ("V", [VIEW]), 0x1, 8, 2, 3, b"",
                         direct=False))
    dx.freeze()

    mi, si, ti = dx.method_index, dx.string_index, dx.type_index

    def view_id(index):
        return FIRST_VIEW_ID + index

    # <init>(): this = v0.
    init = dv.invoke_direct([0], mi(m_act_init)) + dv.return_void()

    # onCreate(Bundle): registers=8, ins=2 -> this=v6, state=v7.
    #   v0 = layout, v1 = current widget, v2 = string, v3 = int
    a = dv.Assembler()
    a.emit(dv.invoke_super([6, 7], mi(m_on_create)))
    a.emit(dv.new_instance(0, ti(LAYOUT)))
    a.emit(dv.invoke_direct([0, 6], mi(m_layout_init)))
    a.emit(dv.const4(3, VERTICAL))
    a.emit(dv.invoke_virtual([0, 3], mi(m_set_orientation)))
    for i, w in enumerate(widgets):
        is_button = w["type"] == "button"
        a.emit(dv.new_instance(1, ti(BUTTON if is_button else TEXTVIEW)))
        a.emit(dv.invoke_direct([1, 6], mi(m_btn_init if is_button else m_tv_init)))
        a.emit(dv.const_string(2, si(w["text"])))
        a.emit(dv.invoke_virtual([1, 2], mi(m_btn_set_text if is_button else m_tv_set_text)))
        a.emit(dv.const32(3, view_id(i)))
        a.emit(dv.invoke_virtual([1, 3], mi(m_btn_set_id if is_button else m_tv_set_id)))
        if is_button and w.get("action"):
            a.emit(dv.invoke_virtual([1, 6], mi(m_btn_set_listener)))
        a.emit(dv.invoke_virtual([0, 1], mi(m_add_view)))
    a.emit(dv.invoke_virtual([6, 0], mi(m_set_content)))
    a.emit(dv.return_void())
    on_create = a.assemble()

    # onClick(View): registers=8, ins=2 -> this=v6, view=v7.
    #   v0 = tapped id, v1 = id to compare, v2 = string, v3 = object,
    #   v4 = int/Uri
    b = dv.Assembler()
    b.emit(dv.invoke_virtual([7], mi(m_get_id)))
    b.emit(dv.move_result(0))
    for i, w in enumerate(widgets):
        action = w.get("action")
        if not action:
            continue
        skip = f"next_{i}"
        b.emit(dv.const32(1, view_id(i)))
        b.if_ne(0, 1, skip)
        atype = action["type"]
        if atype == "set_text":
            b.emit(dv.const32(1, view_id(ids[action["target"]])))
            b.emit(dv.invoke_virtual([6, 1], mi(m_find_view)))
            b.emit(dv.move_result_object(3))
            b.emit(dv.check_cast(3, ti(TEXTVIEW)))
            b.emit(dv.const_string(2, si(action["text"])))
            b.emit(dv.invoke_virtual([3, 2], mi(m_tv_set_text)))
        elif atype == "open_url":
            b.emit(dv.const_string(2, si(action["url"])))
            b.emit(dv.invoke_static([2], mi(m_uri_parse)))
            b.emit(dv.move_result_object(4))
            b.emit(dv.new_instance(3, ti(INTENT)))
            b.emit(dv.const_string(2, si(ACTION_VIEW)))
            b.emit(dv.invoke_direct([3, 2, 4], mi(m_intent_init)))
            b.emit(dv.invoke_virtual([6, 3], mi(m_start_activity)))
        elif atype == "toast":
            b.emit(dv.const_string(2, si(action["text"])))
            b.emit(dv.const4(4, 0))                       # Toast.LENGTH_SHORT
            b.emit(dv.invoke_static([6, 2, 4], mi(m_toast_make)))
            b.emit(dv.move_result_object(3))
            b.emit(dv.invoke_virtual([3], mi(m_toast_show)))
        b.emit(dv.return_void())
        b.label(skip)
    b.emit(dv.return_void())
    on_click = b.assemble()

    by_name = {m.name: m for m in dx._defined}
    by_name["<init>"].code = init
    by_name["onCreate"].code = on_create
    by_name["onClick"].code = on_click
    return dx.build()


def build_from_spec(spec, signing_key=None):
    """Build and sign a complete APK from a spec dict. Returns the bytes."""
    from apkfs import apkforge
    validate(spec)
    color = spec.get("icon_color", "1E88E5")
    rgb = apkforge._hex_color(color)
    files = apkforge.package_files(
        spec["package"], spec.get("name", "My App"), rgb, build_dex(spec),
        int(spec.get("version_code", 1)), str(spec.get("version_name", "1.0")))
    if signing_key is None:
        key = apk.make_keypair()
        cert = apk.self_signed_cert(key)
    else:
        key, cert = signing_key
    return apk.sign(files, key, cert)
