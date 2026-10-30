"""Test-only Ed25519 signer (RFC 8032, 5.1.6) built on the app's verifier, so tests can make signed manifests."""
import hashlib

from subtitle_app import ed25519


def _encode(point) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, ed25519.P - 2, ed25519.P)
    x, y = x * inverse % ed25519.P, y * inverse % ed25519.P
    return (y | (x & 1) << 255).to_bytes(32, "little")


def _expand(secret: bytes):
    digest = hashlib.sha512(secret).digest()
    scalar = int.from_bytes(digest[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    return scalar, digest[32:]


def public_key(secret: bytes) -> bytes:
    return _encode(ed25519._multiply(_expand(secret)[0], ed25519.BASE))


def sign(secret: bytes, message: bytes) -> bytes:
    scalar, prefix = _expand(secret)
    public = _encode(ed25519._multiply(scalar, ed25519.BASE))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % ed25519.L
    encoded_r = _encode(ed25519._multiply(r, ed25519.BASE))
    h = int.from_bytes(hashlib.sha512(encoded_r + public + message).digest(), "little") % ed25519.L
    return encoded_r + ((r + h * scalar) % ed25519.L).to_bytes(32, "little")
