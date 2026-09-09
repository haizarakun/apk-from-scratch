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
