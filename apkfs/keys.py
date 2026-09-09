"""Signing key management — keep one key so your app can be updated.

Android identifies an app by its signing certificate. If you build version 2
with a *different* key than version 1, the phone refuses to install it over
the old one ("signatures do not match") and the user must uninstall first,
losing their data. So real app development needs one key you keep and reuse.

This module stores a P-256 private key together with its self-signed
certificate in a single PEM file. Create it once (`apkforge keygen`), keep it
safe, and pass it to every build (`apkforge --key mykey.pem`). The same file
can be stored as a GitHub Actions secret for browser-only builds.
"""
import datetime
import pathlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def generate(common_name="apk-from-scratch signer", years=30):
    """Create a fresh P-256 key and a self-signed certificate valid for
    `years`. Android only requires the certificate to be valid at install
    time, so long-lived self-signed certs are the norm for app signing."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365 * years))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def to_pem(key, cert):
    """Serialize key + certificate into one PEM blob (unencrypted)."""
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem + cert_pem


def from_pem(pem_bytes):
    """Load (key, cert) from a PEM blob written by to_pem()."""
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    cert = x509.load_pem_x509_certificate(pem_bytes)
    return key, cert


def save(path, key, cert):
    p = pathlib.Path(path)
    p.write_bytes(to_pem(key, cert))
    try:
        p.chmod(0o600)  # private key: owner-only where the OS supports it
    except OSError:
        pass
    return p


def load(path):
    return from_pem(pathlib.Path(path).read_bytes())


def fingerprint(cert):
    """SHA-256 fingerprint of the certificate, the identity Android checks."""
    return cert.fingerprint(hashes.SHA256()).hex(":")
