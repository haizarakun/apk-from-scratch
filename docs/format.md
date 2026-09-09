# The APK format, region by region

This document explains what each part of a minimal APK is and why the code in
`apkfs/` writes the bytes it does. It is the companion to the source — read
them side by side.

## 1. The ZIP shell

An APK is a ZIP file. We store entries **uncompressed** (`STORED`, method 0).
Compression would save a few hundred bytes, but uncompressed keeps every
offset trivially predictable, which matters because the signature is computed
over byte ranges of the file.

A ZIP has three kinds of record:

- **Local file header + data**, one per entry, at the front.
- **Central directory**, one record per entry, near the end — a table of
  contents with the offset of each local header.
- **End of central directory (EOCD)**, the last record, which says where the
  central directory starts and how big it is.

A reader finds the EOCD by scanning backwards for its signature, reads the
central directory from the offset it names, and from there finds every entry.
That "offset the EOCD names" is the hook the v2 signature relies on.

## 2. The binary manifest (AXML)

`AndroidManifest.xml` inside an APK is **not** text. `aapt` compiles it into a
chunked binary format. `apkfs/axml.py` writes that format directly:

- **String pool chunk** — every string the document uses (tag names, attribute
  names, values), stored once and referenced by index. We use UTF-8 entries.
- **Resource map chunk** — for attributes that correspond to framework
  resources (`android:name`, `android:exported`, …), this maps the pool index
  to the attribute's `android.R.attr` resource ID. The attribute strings must
  come first in the pool, in the same order as this map.
- **Start/end namespace chunks** — declare `xmlns:android`.
- **Start/end element chunks** — the tree itself. Each start-element chunk
  carries its attributes inline: namespace, name, a raw string reference, and a
  typed value (string, int, or boolean).

Attribute values are typed. A string points back into the pool; an int or
boolean is stored directly as a 32-bit value with a type tag. Getting the type
tags right is what makes `android:exported="true"` read as a boolean rather
than the literal string "true".

## 3. The Dalvik executable (DEX)

`classes.dex` holds the compiled code. The runtime, ART, memory-maps it and
verifies it before running. `apkfs/dex.py` writes these sections:

- **Header** — magic (`dex\n035\0`), two checksums, sizes and offsets of every
  following section, and the offset of the map list.
- **`string_ids` / string data** — every string, sorted (ART binary-searches
  them). Each datum is a ULEB128 length followed by MUTF-8 bytes.
- **`type_ids`** — indices into the string table for every type descriptor
  (`Ln/A;`, `V`, `I`, `Landroid/os/Bundle;`).
- **`proto_ids`** — method prototypes: a shorty string, a return type, and an
  optional parameter `type_list`.
- **`method_ids`** — (class, prototype, name) triples, sorted.
- **`class_defs`** — one entry describing our class: its type, access flags,
  superclass, and a pointer to its class data.
- **Class data + code items** — the methods, each with a code item:
  register count, in/out argument counts, and the raw bytecode units.
- **Map list** — a table of every section present, with its type, count, and
  offset. ART uses this to validate the file's internal structure, so the
  counts and offsets must be exact and the entries ordered by offset.

Two checksums guard the file. The **SHA-1 signature** (bytes 0x0C–0x1F) covers
everything after it; the **Adler-32 checksum** (bytes 0x08–0x0B) covers
everything after *it*, including the just-written SHA-1. They must be written
in that order — signature first, then checksum over the result.

### Hand-assembled bytecode

The example assembles Dalvik instructions by hand. A few gotchas the code
encodes correctly:

- `this` is the **last** argument register, not register 0. A method with one
  incoming argument and `registers=1` finds `this` in `v0`; with extra locals,
  the argument registers are the high-numbered ones.
- `outs_size` (max outgoing arguments) must not exceed `registers_size`.
- An empty `field_ids` section must have offset 0, or the verifier rejects it.

## 4. The APK Signature Scheme v2

v2 signing inserts an **APK Signing Block** between the last local entry and
the central directory. The block is:

```
uint64  size of block (excluding this field)
(repeated) ID-value pairs: uint64 length, uint32 id, value bytes
uint64  size of block (again, must match)
16 bytes magic  "APK Sig Block 42"
```

Our one pair has ID `0x7109871a` (the v2 block). Its value is a list of
*signers*; each signer is:

```
len-prefixed signed data
len-prefixed signatures
len-prefixed public key
```

The **signed data** contains a list of digests, a list of certificates, and a
list of additional attributes. The **signature** is an ECDSA-with-SHA-256
signature over the signed-data bytes. The **digest** is computed over the file
in three regions:

1. the ZIP entries (start of file up to the signing block),
2. the central directory,
3. the EOCD — **with its central-directory-offset field rewritten to point at
   the start of the signing block.**

That rewrite (step 3) is the subtle part. After the signing block is inserted,
the real central directory moves later in the file, so the EOCD written to disk
records the *real* offset. But the digest is computed as if the offset still
pointed at the block's start. The verifier does the same rewrite before
checking, so the two agree. `apkfs/apk.py` digests with the block-start offset
and writes the file with the real offset, which is why the signature validates.

The digest itself is chunked: the data is split into 1 MiB chunks, each hashed
with a `0xa5` prefix, and the chunk hashes are hashed together with a `0x5a`
count header. For a small APK there is a single chunk, but the framing is
required even then.

### Why EC P-256

BoringSSL (Android's TLS/crypto library) does not ship the P-192 curve, and
some builds are picky about smaller curves. P-256 is universally supported and
produces compact (~70–72 byte DER) signatures, so it is the safe default for a
self-signed debug key.

### v3, alongside v2

Scheme v3 is a near-superset of v2 that additionally records the SDK range a
signer applies to, which is the hook Android uses for key rotation. The
signing block can hold both a v2 pair (ID `0x7109871a`) and a v3 pair
(ID `0xf05368c0`); newer platforms prefer v3 and older ones fall back to v2.
The content digest is identical for both — only the signed-data envelope
differs (v3 inserts `minSDK`/`maxSDK` both inside the signed data and in the
signer) — so `apkfs/apk.py` computes the digest once and emits both pairs. This
toolkit uses a single certificate with no rotation, the simplest valid v3.

## 5. The resource table (resources.arsc)

An app can run without resources, but it has no name and no launcher icon: the
manifest's `android:label` and `android:icon` must be *references*
(`@string/app_name`, `@mipmap/ic_launcher`), and those resolve through
`resources.arsc`. `apkfs/arsc.py` writes a minimal but real table:

- A **global value string pool** holding the label text and the icon's file
  path inside the APK.
- A **package** chunk (id `0x7f`, the conventional app package) containing:
  - a **type string pool** naming the resource types (`string`, `mipmap`),
  - a **key string pool** naming the entries (`app_name`, `ic_launcher`),
  - for each type, a **type-spec** chunk and a **type** chunk. The type chunk
    holds, for one default configuration, an entry per resource: a
    `ResTable_entry` (its key) followed by a `Res_value` (its type and data).

A string resource's value is a `Res_value` of type `STRING` whose data is an
index into the global value pool. The icon's `mipmap` entry is also a `STRING`
whose value is the path `res/mipmap/ic_launcher.png`; at install time Android
reads the PNG at that path. Resource IDs are composed as `0xPPTTEEEE` —
package, type, entry — so `@string/app_name` is `0x7f010000` and
`@mipmap/ic_launcher` is `0x7f020000`, and those are the values the manifest's
reference-typed attributes carry.

The icon itself is a plain PNG, written by `apkfs/png.py` with nothing but
`zlib` and `struct`: an RGBA bitmap with one `IHDR`/`IDAT`/`IEND` chunk stream.

## 6. DEX, beyond one method

The DEX writer supports what an interactive app needs:

- **Instance fields** — a `field_ids` section and encoded fields in the class
  data, read and written with `iget`/`iput` (and the `-object` variants).
- **Interfaces** — the class's `interfaces_off` points at a `type_list` of
  interface descriptors, so a class can declare `implements
  View.OnClickListener`.
- **Direct vs virtual methods** — constructors and private/static methods are
  *direct*; overrides and interface implementations are *virtual*, placed in
  the class data's virtual-method list so ART dispatches them. The tap-counter
  example relies on this for its `onClick`.

All of `string_ids`, `type_ids`, and `method_ids` are sorted so ART's binary
searches succeed, and because sorting happens at `freeze()` time, bytecode
operands (string/type/field/method indices) are read back with the
`*_index()` accessors *after* freezing — never from the value returned when the
item was first registered.

## 7. Reading it back

`apkfs/decode.py` reverses the formats above: it parses a string pool, decodes
a binary manifest to XML, walks a `resources.arsc` into `{package: {type:
{entry: value}}}`, and reads a DEX header and id tables into a class/field/
method summary. `apkfs/apkinspect.py` ties these to a minimal ZIP reader (one
that steps over the signing block) and the signature verifier to print a full
report for any APK.

Having both directions is not just convenient — it is a test. The suite feeds
an encoder's output straight into the matching decoder and checks the result
equals the input. A format you can round-trip is one the writer and reader
agree on, independently of any external tool.
