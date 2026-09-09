"""apk-from-scratch — build and read signed Android APKs in pure Python.

No Android SDK, aapt, d8, JDK, zipalign, or apksigner. The submodules each own
one binary format:

    axml    binary AndroidManifest.xml (AXML)
    dex     classes.dex (Dalvik executable)
    dalvik  readable Dalvik instruction encoders + a label-based assembler
    arsc    resources.arsc (compiled resource table)
    png     a tiny PNG encoder for the launcher icon
    apk     ZIP packing + APK Signature Scheme v2/v3 signing
    verify  independent cryptographic signature verifier
    decode  readers: AXML -> XML, arsc -> entries, dex -> summary

High-level entry points:

    apkfs.apkforge.build_apk(...)   build and sign a complete APK
    apkfs.apkinspect.inspect(path)  read an APK back into a text report
"""

__all__ = [
    "axml", "dex", "dalvik", "arsc", "png", "apk", "verify", "decode",
    "apkforge", "apkinspect",
]

__version__ = "0.1.0"
