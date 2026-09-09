"""Independent APK v2/v3 signature verifier.

This does NOT reuse the signing code. It re-parses the APK from bytes, finds
the APK Signing Block, recomputes the three-region content digest the way a
verifier (Android's PackageManager) does, and checks both:

  1. the recomputed digest equals the digest stored in signed_data, and
  2. the ECDSA signature over signed_data validates against the embedded key.

INTEGRITY vs AUTHENTICITY. Those two checks prove the APK has not been altered
since it was signed by *whoever holds the embedded key* — integrity. They do
NOT, on their own, prove *who* signed it: an attacker can modify the APK, sign
it with their own fresh key, and it will still pass, because the key travels
inside the file. That is the same reason Android checks an update's signature
against the certificate already installed for the package. To get that
authenticity guarantee here, pass the certificate (or public key) you trust as
`expected_cert_der` / `expected_public_key`; verification then also requires
the embedded key to match it. Callers that omit it get integrity only.
"""
import hmac
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography import x509

APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
SIG_V2_BLOCK_ID = 0x7109871A
SIG_V3_BLOCK_ID = 0xF05368C0
SIG_ALGO_ECDSA_SHA256 = 0x0201


def _find_eocd(data):
    i = data.rfind(b"PK\x05\x06")
    if i < 0:
        raise ValueError("no EOCD")
    cd_size, cd_off = struct.unpack_from("<II", data, i + 12)
    return i, cd_size, cd_off


def _read_lp(buf, pos):
    """Read a uint32 length-prefixed blob at pos; return (blob, next_pos)."""
    (n,) = struct.unpack_from("<I", buf, pos)
    start = pos + 4
    return buf[start:start + n], start + n


def verify(data, expected_cert_der=None, expected_public_key=None):
    """Verify the APK's v2/v3 signatures over `data`.

    With neither `expected_cert_der` nor `expected_public_key`, this checks
    integrity only (see the module docstring). Pass one of them — the trusted
    signer's certificate DER, or its SubjectPublicKeyInfo DER — to also require
    the embedded key to match it, which is the authenticity check.
    Raises ValueError / an exception on any mismatch; returns a summary dict.
    """
    eocd_off, cd_size, cd_off = _find_eocd(data)

    # The signing block ends just before the central directory.
    magic = data[cd_off - 16:cd_off]
    if magic != APK_SIG_BLOCK_MAGIC:
        raise ValueError("APK Sig Block magic not found before central dir")
    (block_size_trailing,) = struct.unpack_from("<Q", data, cd_off - 24)
    block_start = cd_off - 8 - block_size_trailing
    (block_size_head,) = struct.unpack_from("<Q", data, block_start)
    if block_size_head != block_size_trailing:
        raise ValueError("signing block size fields disagree")

    # Walk the ID-value pairs, collecting every signing-scheme block present.
    pos = block_start + 8
    end = cd_off - 24
    blocks = {}
    while pos < end:
        (pair_len,) = struct.unpack_from("<Q", data, pos)
        (pair_id,) = struct.unpack_from("<I", data, pos + 8)
        blocks[pair_id] = data[pos + 12:pos + 8 + pair_len]
        pos += 8 + pair_len
    if SIG_V2_BLOCK_ID not in blocks and SIG_V3_BLOCK_ID not in blocks:
        raise ValueError("no v2 or v3 signing block")

    # Recompute the three-region digest once. The EOCD's central-dir offset is
    # treated as pointing at the start of the signing block during digesting.
    eocd = bytearray(data[eocd_off:])
    struct.pack_into("<I", eocd, 16, block_start)
    recomputed = _chunked_digest(
        data[:block_start] + data[cd_off:eocd_off] + bytes(eocd))

    schemes = {}
    for version, block_id in (("v2", SIG_V2_BLOCK_ID), ("v3", SIG_V3_BLOCK_ID)):
        if block_id not in blocks:
            continue
        # block = len-prefixed(signers); one signer each here.
        signers, _ = _read_lp(blocks[block_id], 0)
        signer, _ = _read_lp(signers, 0)
        signed_data, p = _read_lp(signer, 0)
        # The signer's trailing fields differ between v2 and v3, but the
        # signatures and public key are the last two length-prefixed blocks,
        # and the signed-data digest+cert layout matches at the front.
        if version == "v3":
            p += 8  # skip minSDK/maxSDK in the signer envelope
        signatures, p = _read_lp(signer, p)
        public_key, p = _read_lp(signer, p)

        digests, q = _read_lp(signed_data, 0)
        certs, q = _read_lp(signed_data, q)
        digest_entry, _ = _read_lp(digests, 0)
        (algo_id,) = struct.unpack_from("<I", digest_entry, 0)
        if algo_id != SIG_ALGO_ECDSA_SHA256:
            raise ValueError(f"{version}: unsupported signature algorithm "
                             f"0x{algo_id:04x}")
        stored_digest, _ = _read_lp(digest_entry, 4)
        if not hmac.compare_digest(recomputed, stored_digest):
            raise ValueError(f"{version}: content digest mismatch")

        sig_entry, _ = _read_lp(signatures, 0)
        (sig_algo,) = struct.unpack_from("<I", sig_entry, 0)
        if sig_algo != SIG_ALGO_ECDSA_SHA256:
            raise ValueError(f"{version}: unsupported signature algorithm "
                             f"0x{sig_algo:04x}")
        signature, _ = _read_lp(sig_entry, 4)
        load_der_public_key(public_key).verify(
            signature, signed_data, ec.ECDSA(hashes.SHA256()))

        cert_der, _ = _read_lp(certs, 0)
        cert = x509.load_der_x509_certificate(cert_der)
        from cryptography.hazmat.primitives import serialization as _s
        cert_pub = cert.public_key().public_bytes(
            _s.Encoding.DER, _s.PublicFormat.SubjectPublicKeyInfo)
        if not hmac.compare_digest(cert_pub, public_key):
            raise ValueError(f"{version}: certificate key mismatch")

        # Authenticity: if the caller pinned a trusted key/cert, the embedded
        # one must match it, or the signature is valid but from the wrong party.
        if expected_cert_der is not None and not hmac.compare_digest(
                cert_der, expected_cert_der):
            raise ValueError(f"{version}: certificate does not match the "
                             "expected (pinned) certificate")
        if expected_public_key is not None and not hmac.compare_digest(
                public_key, expected_public_key):
            raise ValueError(f"{version}: public key does not match the "
                             "expected (pinned) key")

        schemes[version] = {"algo_id": algo_id,
                            "cert_subject": cert.subject.rfc4514_string()}

    return {"digest_ok": True, "signature_ok": True,
            "authenticity_checked": expected_cert_der is not None
            or expected_public_key is not None,
            "schemes": sorted(schemes), **schemes}


def _chunked_digest(data):
    CHUNK = 1024 * 1024
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    import hashlib
    top = hashlib.sha256()
    top.update(b"\x5a" + struct.pack("<I", len(chunks)))
    for c in chunks:
        h = hashlib.sha256()
        h.update(b"\xa5" + struct.pack("<I", len(c)) + c)
        top.update(h.digest())
    return top.digest()


if __name__ == "__main__":
    import sys
    result = verify(open(sys.argv[1], "rb").read())
    print("OK", result)
