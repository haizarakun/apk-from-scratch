"""APK writer and v2 signer, pure Python.

An APK is a ZIP file plus an APK Signature Scheme v2 block inserted just
before the ZIP central directory. This module builds the ZIP (stored, no
compression, so offsets stay simple), computes the v2 signature over the
three ZIP regions the scheme defines, and inserts the signing block — with no
apksigner, no zipalign, no JDK.

v2 signing reference: https://source.android.com/docs/security/features/apksigning/v2
"""
import struct
import zlib
import hashlib

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
)
from cryptography import x509
from cryptography.x509.oid import NameOID
import datetime

APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
SIG_V2_BLOCK_ID = 0x7109871A
SIG_V3_BLOCK_ID = 0xF05368C0
# SIGNATURE_ALGORITHM_ECDSA_WITH_SHA256
SIG_ALGO_ECDSA_SHA256 = 0x0201

# v3 signer declares the SDK range it applies to. 0 .. INT32_MAX covers all.
V3_MIN_SDK = 0
V3_MAX_SDK = 0x7FFFFFFF


ALIGNMENT = 4  # zipalign's default: stored entry data on a 4-byte boundary


def _zip_stored(files):
    """Build a STORED (uncompressed), 4-byte-aligned ZIP. files: {name: bytes}.

    Every entry is stored uncompressed and its file data is padded to a 4-byte
    boundary, exactly as `zipalign -f 4` would. Alignment matters because
    Android memory-maps uncompressed entries in place: from Android 11 an
    installation is rejected if `resources.arsc` is stored but unaligned, and
    mmap of other stored entries needs 4-byte alignment too. The padding goes
    in the local header's extra field so the data offset lands on the boundary.

    Returns (local_bytes, central_bytes)."""
    local, central = bytearray(), bytearray()
    for name, body in files.items():
        nb = name.encode("utf-8")
        crc = zlib.crc32(body) & 0xFFFFFFFF
        offset = len(local)
        # Data begins after the 30-byte local header, the name, and the extra
        # field; choose an extra-field length that 4-byte-aligns it.
        header_end = offset + 30 + len(nb)
        pad = (-header_end) % ALIGNMENT
        extra = b"\0" * pad
        local += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
                             crc, len(body), len(body), len(nb), len(extra))
        local += nb + extra + body
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0,
                               0, 0, crc, len(body), len(body), len(nb), 0, 0,
                               0, 0, 0, offset)
        central += nb
    return local, central


def _eocd(cd_offset, cd_size, count):
    return struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, count, count,
                       cd_size, cd_offset, 0)


def make_keypair():
    """Generate a fresh P-256 signing key (BoringSSL has no P-192)."""
    return ec.generate_private_key(ec.SECP256R1())


def self_signed_cert(key, cn="APK from scratch"):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365 * 30))
        .sign(key, hashes.SHA256())
    )


def _chunked_digest(data):
    """APK v2 content digest: split into 1 MiB chunks, SHA-256 each with a
    0xa5 prefix, then SHA-256 the concatenation with a 0x5a count header."""
    CHUNK = 1024 * 1024
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    top = hashlib.sha256()
    top.update(b"\x5a" + struct.pack("<I", len(chunks)))
    for c in chunks:
        h = hashlib.sha256()
        h.update(b"\xa5" + struct.pack("<I", len(c)) + c)
        top.update(h.digest())
    return top.digest()


def _len_prefixed(b):
    return struct.pack("<I", len(b)) + b


def _digests_and_certs(digest, cert):
    """The digests and certificates sequences shared by v2 and v3 signed data.
    Each is a length-prefixed sequence of length-prefixed elements."""
    digest_entry = _len_prefixed(
        struct.pack("<I", SIG_ALGO_ECDSA_SHA256) + _len_prefixed(digest))
    digests = _len_prefixed(digest_entry)
    certs = _len_prefixed(_len_prefixed(
        cert.public_bytes(serialization.Encoding.DER)))
    return digests, certs


def _sign_signed_data(signed_data, key):
    """Sign the signed-data payload (its bytes without the outer length
    prefix) and return the signatures sequence."""
    der_sig = key.sign(signed_data[4:], ec.ECDSA(hashes.SHA256()))
    sig_entry = _len_prefixed(
        struct.pack("<I", SIG_ALGO_ECDSA_SHA256) + _len_prefixed(der_sig))
    return _len_prefixed(sig_entry)


def _public_key_block(cert):
    return _len_prefixed(cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo))


def _v2_pair(digest, key, cert):
    """The ID-value pair for the v2 scheme.

    signer = signed_data || signatures || public_key, where
    signed_data = digests || certificates || additional-attributes.
    """
    digests, certs = _digests_and_certs(digest, cert)
    signed_data = _len_prefixed(digests + certs + _len_prefixed(b""))
    signatures = _sign_signed_data(signed_data, key)
    signer = _len_prefixed(signed_data + signatures + _public_key_block(cert))
    return SIG_V2_BLOCK_ID, _len_prefixed(signer)  # len-prefixed signer list


def _v3_pair(digest, key, cert):
    """The ID-value pair for the v3 scheme.

    v3 differs from v2 by adding the applicable SDK range both inside the
    signed data (so it is protected) and in the signer envelope:
      signed_data = digests || certs || minSDK || maxSDK || attributes
      signer      = signed_data || minSDK || maxSDK || signatures || pubkey
    """
    digests, certs = _digests_and_certs(digest, cert)
    sdk = struct.pack("<II", V3_MIN_SDK, V3_MAX_SDK)
    signed_data = _len_prefixed(digests + certs + sdk + _len_prefixed(b""))
    signatures = _sign_signed_data(signed_data, key)
    signer = _len_prefixed(
        signed_data + sdk + signatures + _public_key_block(cert))
    return SIG_V3_BLOCK_ID, _len_prefixed(signer)


def sign(files, key, cert, schemes=(2, 3)):
    """Build and sign an APK from {name: bytes}, returning the APK bytes.

    schemes selects which APK Signature Scheme blocks to embed; v2 and v3 are
    supported and both are emitted by default. The content digest is identical
    for both schemes — only the signed-data envelope differs — so it is
    computed once.
    """
    local, central = _zip_stored(files)
    block_start = len(local)

    # The scheme digests three regions: the ZIP entries, the central directory,
    # and the EOCD with its central-directory offset rewritten to point at the
    # start of the signing block. That digested offset is fixed (independent of
    # the block's eventual length), so there is no circular dependency: we
    # digest once, build the block, then write the real EOCD offset.
    def eocd_with_offset(cd_offset):
        return bytes(_eocd(cd_offset, len(central), len(files)))

    digest = _chunked_digest(
        bytes(local) + bytes(central) + eocd_with_offset(block_start))

    builders = {2: _v2_pair, 3: _v3_pair}
    pairs = []
    for s in schemes:
        if s not in builders:
            raise ValueError(f"unsupported scheme v{s}")
        pair_id, value = builders[s](digest, key, cert)
        pairs.append(struct.pack("<Q", len(value) + 4)
                     + struct.pack("<I", pair_id) + value)

    body = b"".join(pairs)
    block_len = len(body) + 8 + 16  # trailing size (8) + magic (16)
    block = (struct.pack("<Q", block_len) + body
             + struct.pack("<Q", block_len) + APK_SIG_BLOCK_MAGIC)

    final_eocd = eocd_with_offset(block_start + len(block))
    return bytes(local) + block + bytes(central) + final_eocd


def sign_v2(files, key, cert):
    """Backwards-compatible helper: sign with the v2 scheme only."""
    return sign(files, key, cert, schemes=(2,))
