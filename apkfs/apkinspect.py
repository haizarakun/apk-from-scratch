#!/usr/bin/env python3
"""apkinspect — read an APK back and print what's inside it.

The counterpart to apkforge: it opens an APK (its own output or any other),
lists the ZIP entries, decodes the binary manifest to XML, resolves the app
label and icon from resources.arsc, summarizes classes.dex, and verifies the
v2/v3 signature — using this project's own decoders, no Android SDK.

    python3 tools/apkinspect.py app.apk
"""
import argparse
import pathlib
import struct
import zlib

from apkfs import decode
from apkfs import verify


def read_zip_stored(data):
    """Return {name: bytes} from a ZIP, reading local headers directly so an
    APK Signing Block between entries and the central directory is ignored."""
    files = {}
    pos = 0
    max_decompressed = 256 * 1024 * 1024  # guard against zip bombs
    while pos + 30 <= len(data) and data[pos:pos + 4] == b"PK\x03\x04":
        (_, _, method, _, _, _, comp_size, _uncomp,
         name_len, extra_len) = struct.unpack_from("<HHHHHIIIHH", data, pos + 4)
        body_off = pos + 30 + name_len + extra_len
        if body_off + comp_size > len(data):
            raise ValueError("ZIP entry runs past end of file")
        name = data[pos + 30:pos + 30 + name_len].decode("utf-8", "replace")
        body = data[body_off:body_off + comp_size]
        if method == 8:
            body = zlib.decompressobj(-15).decompress(body, max_decompressed)
        elif method != 0:
            raise ValueError(f"unsupported ZIP compression method {method}")
        files[name] = body
        pos = body_off + comp_size
    return files


def inspect(path):
    data = pathlib.Path(path).read_bytes()
    files = read_zip_stored(data)
    lines = [f"APK: {path}  ({len(data)} bytes)", ""]

    lines.append("Entries:")
    for name, body in files.items():
        lines.append(f"  {name}  ({len(body)} bytes)")
    lines.append("")

    if "AndroidManifest.xml" in files:
        lines.append("Manifest:")
        for xl in decode.decode_axml(files["AndroidManifest.xml"]).splitlines():
            lines.append("  " + xl)
        lines.append("")

    if "resources.arsc" in files:
        lines.append("Resources:")
        table = decode.read_arsc(files["resources.arsc"])
        for pkg, types in table.items():
            lines.append(f"  package {pkg}")
            for tname, entries in types.items():
                for key, val in entries.items():
                    lines.append(f"    @{tname}/{key} = {val!r}")
        lines.append("")

    if "classes.dex" in files:
        s = decode.dex_summary(files["classes.dex"])
        lines.append("classes.dex:")
        lines.append(f"  counts: {s['counts']}")
        for c in s["classes"]:
            lines.append(f"  class {c}")
        own = [m for m in s["methods"] if any(
            m.startswith(c) for c in s["classes"])]
        for m in own:
            lines.append(f"    method {m}")
        lines.append("")

    lines.append("Signature:")
    try:
        result = verify.verify(data)
        lines.append(f"  schemes: {', '.join(result['schemes'])}")
        for scheme in result["schemes"]:
            lines.append(f"  {scheme}: verified, cert {result[scheme]['cert_subject']}")
    except Exception as e:  # noqa: BLE001 - report any verification failure
        lines.append(f"  NOT verified: {e}")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="Inspect an APK with no Android SDK.")
    p.add_argument("apk", help="path to the APK to inspect")
    args = p.parse_args(argv)
    print(inspect(args.apk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
