# apk-from-scratch

> This is a partial English version. The primary, most complete documentation
> is in Japanese: **[日本語 (メイン)](README.md)**. Other languages are not supported.

Build a real, installable, **signed** Android APK with nothing but Python.

No Android SDK. No `aapt`. No `d8`/`dx`. No JDK. No `zipalign`. No `apksigner`.
Just the standard library and [`cryptography`](https://pypi.org/project/cryptography/)
for the signature math.

```bash
pip install apk-from-scratch
apkforge --package com.example.hello --label "Hello" \
    --message "Built from scratch." -o hello.apk
# wrote hello.apk (4945 bytes) — package com.example.hello
```

That APK carries a name and a launcher icon, runs an Activity, and passes a
cryptographic **APK Signature Scheme v2 + v3** check — the same check Android's
package installer runs before it will install an app.

---

## Why this exists

Every "hello world" Android tutorial hands you a toolchain — Gradle, the SDK,
half a gigabyte of build tools — and tells you to press a button. You never
see what an APK *is*.

An APK is not mysterious. It is a ZIP holding a handful of well-specified
binary formats:

- a **binary manifest** (`AndroidManifest.xml` compiled to AXML),
- **Dalvik bytecode** (`classes.dex`) the runtime loads and verifies,
- a **compiled resource table** (`resources.arsc`) that gives the app its name
  and icon,
- and a **signature** proving the file has not been tampered with.

This project **writes all of them by hand and reads them back**, from first
principles, so you can see every byte in both directions. It is small enough to
read in an afternoon and correct enough that the output installs — and an
encode → decode round-trip is a correctness check that needs no external tool.

## What it can build

| Capability | Module | Replaces |
|------------|--------|----------|
| Binary `AndroidManifest.xml` (typed attributes, resource references, version info) | `apkfs/axml.py` | `aapt` |
| `classes.dex` — strings, types, protos, **fields**, methods, **interfaces**, **direct & virtual** methods | `apkfs/dex.py` | `d8` / `dx` |
| Readable Dalvik instruction encoders + a label-based assembler for branches/loops | `apkfs/dalvik.py` | hand-written hex |
| `resources.arsc` with app **label** and **launcher icon** | `apkfs/arsc.py` | `aapt` |
| Pure-Python PNG encoder for the icon | `apkfs/png.py` | Pillow / an artist |
| ZIP packing + **APK Signature Scheme v2 and v3** (EC P-256) | `apkfs/apk.py` | `zipalign` + `apksigner` |
| Independent cryptographic signature verifier | `apkfs/verify.py` | `apksigner verify` |
| One-command APK builder | `apkfs/apkforge.py` | Gradle |
| **Decoders** — AXML → XML, `resources.arsc` → entries, DEX → classes/fields/methods | `apkfs/decode.py` | `apktool d` |
| One-command APK inspector | `apkfs/apkinspect.py` | `aapt dump` / `apktool` |

## Examples

| Example | What it demonstrates |
|---------|----------------------|
| [`examples/hello`](examples/hello/build.py) | The minimum: one Activity that locks orientation. No resources. |
| [`examples/hello_text`](examples/hello_text/build.py) | A `TextView` built and shown at runtime — object allocation, constructor, string load, virtual calls. |
| [`examples/icon_app`](examples/icon_app/build.py) | A full app with a `resources.arsc`: a launcher **name** and a generated **icon**, plus version info. |
| [`examples/counter`](examples/counter/build.py) | An **interactive** app: the Activity implements `View.OnClickListener`, keeps an `int` field, and updates a button's text on every tap. |
| [`examples/loop_sum`](examples/loop_sum/build.py) | **Control flow**: a real `for` loop (`if-ge` / `goto`) sums 1..10 and shows the result, with branch offsets resolved by a label-based assembler. |
| [`examples/i18n`](examples/i18n/build.py) | **Unicode**: a Japanese + emoji app label and message, encoded as MUTF-8 (DEX) and UTF-8 (resources) with correct UTF-16 length prefixes. |

## The APK, byte by byte

```
┌─────────────────────────────────────────┐
│ ZIP local file entries (stored)          │  ← AndroidManifest.xml, classes.dex,
│                                           │    resources.arsc, res/mipmap/ic.png
├─────────────────────────────────────────┤
│ APK Signing Block                         │  ← inserted by the signer
│   size │ v2 pair │ v3 pair │ size │ magic │
├─────────────────────────────────────────┤
│ ZIP central directory                     │
├─────────────────────────────────────────┤
│ End of central directory (EOCD)           │
└─────────────────────────────────────────┘
```

The signature covers a digest of the entries, the central directory, and the
EOCD — but not the signing block itself (it cannot sign over its own bytes).
The digest is computed with the EOCD's central-directory offset rewritten to
point at the signing block, which is the one detail that trips up most
hand-rolled signers. [`docs/format.md`](docs/format.md) walks through every
region in detail.

## Install

```bash
pip install apk-from-scratch          # from a checkout: pip install .
```

This installs the `apkfs` package and two commands, `apkforge` (build) and
`apkinspect` (read). The only runtime dependency is `cryptography`. Python 3.8+.

To hack on it, install editable with the test extras:

```bash
pip install -e ".[test]"              # adds androguard + pytest
```

## Run it

```bash
# Build a signed APK in one command:
apkforge --package com.example.app --label "My App" \
    --message "Hi" --icon-color 1E88E5 -o my.apk

# Read any APK back — manifest, resources, classes, signature:
apkinspect my.apk

# Install on a device or emulator:
adb install -r my.apk
```

Without installing, the same commands run as modules from a checkout
(`python3 -m apkfs.apkforge …`, `python3 -m apkfs.apkinspect …`), and each
worked example builds an APK directly:

```bash
python3 examples/counter/build.py     # or hello / hello_text / icon_app / loop_sum / i18n
python3 tests/test_build.py           # needs the [test] extras
```

## How it's tested

`tests/test_build.py` asserts the output is accepted by
[androguard](https://github.com/androguard/androguard) — an independent,
widely-used APK parser — and that the signatures verify:

- the manifest round-trips through a real AXML parser,
- the DEX disassembles to the expected classes, fields, interfaces, and
  bytecode,
- the package name, label, icon, and version read back correctly,
- both the v2 and v3 signatures parse **and cryptographically verify**,
- a tampered APK is **rejected** — a signer that accepts altered input is worse
  than none, and
- every format **round-trips**: encode → decode returns what went in (manifest,
  resources, DEX), proving the reader and writer agree without external tooling.

CI runs all of this on every push ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Scope

This is a teaching toolkit that produces genuinely installable apps. It covers
one class per DEX (with fields, one interface, and virtual methods), a single
default resource configuration, one signing certificate, and the subset of
Dalvik instructions the examples use. Natural extensions — multiple classes,
more instructions, denser icons, v4 signatures, permissions — are documented as
good first issues in [`CONTRIBUTING.md`](CONTRIBUTING.md). The foundations are
complete and verified.

## Community

- **Discord** (main support channel): <DISCORD_INVITE>
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to contribute, and good first issues.
- [SECURITY.md](SECURITY.md) — reporting a signing or verification vulnerability.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — expected conduct in project spaces.
- [CHANGELOG.md](CHANGELOG.md) — what has changed.

Support is primarily in Japanese. English questions are welcome on Discord but
answered on a best-effort basis; other languages are not supported.

## License

MIT. See [LICENSE](LICENSE).
