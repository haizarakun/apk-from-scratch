# Security Policy

## Scope

This project builds and signs Android APKs. The security-relevant parts are
the signing implementation (`apkfs/apk.py`) and the verifier
(`apkfs/verify.py`). A bug there could, in principle, produce an APK that a
device accepts but that does not carry the guarantees an APK signature is
meant to provide, or a verifier that accepts a tampered file.

This is a teaching toolkit. It generates **self-signed debug certificates** and
is not intended for production release signing. Do not use its generated keys
to sign apps you publish.

### Integrity vs. authenticity in the verifier

`apkfs.verify.verify()` checks that an APK has not been altered since it was
signed by whoever holds the key embedded in the file (**integrity**). Because
the public key travels inside the APK, that check alone does **not** prove
*who* signed it: an attacker can tamper and re-sign with their own key and pass
integrity — exactly why Android checks an update against the certificate already
installed for the package. To get that **authenticity** guarantee, pin the
trusted certificate or public key:

```python
from apkfs import verify
verify.verify(apk_bytes, expected_cert_der=trusted_cert_der)  # rejects other keys
```

Verification uses a constant-time comparison for the digest, key, and pinned
certificate, and rejects any signature algorithm other than the one it
implements (ECDSA-with-SHA-256).

## Reporting a vulnerability

If you find a security issue — especially one where the verifier accepts a
tampered APK, or the signer produces an incorrectly-signed one — please report
it privately rather than opening a public issue:

- Use GitHub's **private vulnerability reporting** ("Report a vulnerability" on
  the Security tab), or
- contact the maintainer directly through the address on their GitHub profile.

Please include a reproduction (a script and/or a sample APK) and the expected
versus actual behavior. We aim to acknowledge reports within a week.

## Reader safety

The readers (`apkfs.decode`, `apkfs.apkinspect`) parse untrusted APKs. They
bound every read against the file size, cap element counts and decompression,
and raise `apkfs.decode.MalformedError` (a `ValueError`) on bad input rather
than crashing or looping. If you find an input that makes a reader hang, spin,
or raise an unexpected exception type, please report it.

## Non-issues

- The toolkit intentionally uses a single self-signed certificate with no key
  rotation. That is a scope choice, not a vulnerability.
- Generated APK entries are stored uncompressed (and 4-byte aligned, like
  `zipalign`), which is by design for clarity, not a defect.
