# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
semantic versioning once it has a tagged release.

## [Unreleased]

### Security & correctness (audit fixes)
- **4-byte alignment (zipalign)**: stored entries — `resources.arsc` in
  particular — are now aligned, so installation is not rejected on Android 11+.
- **Verifier authenticity**: `verify()` gained `expected_cert_der` /
  `expected_public_key` pinning; without it, it documents that it checks
  integrity only. It now uses constant-time comparisons and rejects unsupported
  signature algorithms.
- **AXML string pool**: length prefixes use the 2-byte form for values ≥ 128,
  so long package names, class names, and `versionName` encode correctly.
- **DEX string order**: `string_ids` are sorted by UTF-16 code unit, correct
  for astral characters (emoji), so ART's binary search cannot miss them.
- **Reader hardening**: the decoders bound every read, cap counts and
  decompression, and raise `MalformedError` instead of hanging or crashing on
  malformed/hostile input.

### Web apps — the "no Android Studio" path
- **Multi-class DEX**: `DexBuilder.add_class()` defines any number of classes
  (each with its own super, interfaces, fields, methods); the primary-class
  API is unchanged.
- **WebView host** (`apkfs/webapp.py`): three hand-assembled classes — an
  Activity with a full-screen WebView (JavaScript, DOM storage, file access),
  a `WebViewClient` that turns `app://<cmd>?v=` navigations into native
  calls (toast, open, share, copy, exit), and a `WebChromeClient` that shows
  `alert()` as a toast. Back button walks web history. Your HTML/CSS/JS is
  bundled under `assets/` with a generated `apkfs-bridge.js`.
- `apkforge --web DIR` / `--html FILE`; the browser workflow accepts pasted
  HTML. Example: `examples/web_app/site` (notes app with storage, list,
  share, copy, fetch).
- New encoders: `return`, `return-object`.

### Lists, images, networking (no code)
- **App spec** grows `image` (from a file, an https URL, or base64; packed as a
  `drawable` resource and shown scaled to width), `list` (rows, each with an
  optional action), a **scrolling** root, and the **`fetch`** action: download
  text from an https URL on a background `Thread` and show it in a widget.
- **try/catch in the DEX writer** (`Method.tries`, catch-all handlers) so a
  failed fetch shows the error instead of crashing; `move-exception` encoder.
- `<uses-permission>` support in the manifest writer; INTERNET is added
  automatically when a spec uses `fetch`.

### Real apps without code
- **App spec** (`apkfs/appspec.py`): describe a screen in JSON — texts and
  buttons, each button with an action (`set_text`, `open_url`, `toast`) — and
  get a signed APK with a vertical layout and a real `onClick` dispatcher,
  all hand-assembled. `apkforge --spec app.json`. Example in
  `examples/spec_app/app.json`.
- **Signing keys** (`apkfs/keys.py`): `apkforge keygen` creates a P-256
  key + certificate PEM; `--key` signs with it so updates install over older
  versions (Android matches on the certificate). Fingerprint shown on creation.
- Browser flow: the "Make an APK" workflow accepts an app spec and signs with
  the `APK_SIGNING_KEY` secret; a "Create signing key" workflow makes the key
  (refuses to run on public repos so the key cannot leak via artifacts).
- New Dalvik encoders: `const` (32-bit), `check-cast`, `move-result`,
  `if-eq`/`if-ne`.

### Ease of use
- **Browser-only build**: a `workflow_dispatch` GitHub Action ("Make an APK
  (no coding)") lets anyone build an APK from a form and download it — no
  command line or local setup. A step-by-step Japanese guide is in
  `docs/EASY.ja.md`.
- **Interactive wizard**: running `apkforge` with no arguments asks a few plain
  questions and builds the APK, so no flags need to be remembered.

### Added
- Binary `AndroidManifest.xml` (AXML) writer with typed attributes and
  resource references (`apkfs/axml.py`).
- `classes.dex` writer supporting strings, types, protos, fields, methods,
  interfaces, instance fields, and both direct and virtual methods
  (`apkfs/dex.py`).
- Readable Dalvik instruction encoder (`apkfs/dalvik.py`): `invoke-*`,
  `const-string`, `new-instance`, `iget`/`iput`, `add-int`/`add-int/lit8`, and
  a label-based `Assembler` with `goto` and conditional branches that resolves
  offsets automatically (control flow — loops and `if`).
- `resources.arsc` writer with app label and launcher icon, plus a pure-Python
  PNG encoder for the icon (`apkfs/arsc.py`, `apkfs/png.py`).
- APK writer with **APK Signature Scheme v2 and v3** (EC P-256), and an
  independent cryptographic verifier (`apkfs/apk.py`, `apkfs/verify.py`).
- `apkforge` command-line tool to build a signed APK from flags
  (`apkfs/apkforge.py`).
- **Decoders** (`apkfs/decode.py`): binary manifest → XML, `resources.arsc` →
  resolved entries, and a `classes.dex` summary (classes, fields, methods).
- `apkinspect` command-line tool that reads an APK back and prints its entries,
  manifest, resources, DEX summary, and signature status (`apkfs/apkinspect.py`).
- Encode → decode round-trip tests for the manifest, resources, and DEX.
- **Full Unicode**: DEX strings use Modified UTF-8 (MUTF-8) with UTF-16 length
  prefixes, and resource strings count UTF-16 code units — so Japanese, emoji,
  and other scripts work in app labels and on-screen text (`examples/i18n`).
- **Installable package**: the modules live in the `apkfs` package with a
  `pyproject.toml`; `pip install` provides the `apkforge` and `apkinspect`
  console commands.
- Project docs: `SUPPORT.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and a
  Japanese-primary README with a partial English version (`README.md`, `README.en.md`).
- Examples: minimal orientation app, on-screen text, full app with icon and
  label, an interactive tap counter, and a loop that computes a value.
- Test suite validating output against androguard and the v2/v3 signatures,
  plus a tamper-detection test. GitHub Actions CI.
