"""Envelope encryption for provider credentials (SECURITY_ARCHITECTURE.md section 6).

AES-256-GCM. Each secret gets a fresh random 96-bit nonce. The associated data binds the ciphertext
to its organization and name, so a stored value cannot be moved to another record and still decrypt.
The key comes from configuration (a KMS in production). Only ciphertext, nonce, key version and the
last four characters are stored; the plaintext is never written anywhere.
"""

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings


class SecretError(Exception):
    pass


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    key_version: int
    last4: str


def _key_from_settings(settings: Settings) -> bytes:
    if settings.secret_encryption_key:
        raw = base64.b64decode(settings.secret_encryption_key)
        if len(raw) != 32:
            raise SecretError("AIDLC_SECRET_ENCRYPTION_KEY must decode to 32 bytes")
        return raw
    if settings.app_env in ("development", "test"):
        # Development and test only: derive from the signing key so local runs work without setup.
        return hashlib.sha256(b"aidlc-dev-kek:" + settings.secret_key.encode()).digest()
    raise SecretError("AIDLC_SECRET_ENCRYPTION_KEY is required outside development")


def _aad(organization_id: str, name: str) -> bytes:
    return f"org={organization_id};name={name}".encode()


def seal(settings: Settings, plaintext: str, *, organization_id: str, name: str) -> Sealed:
    if not plaintext:
        raise SecretError("secret is empty")
    aead = AESGCM(_key_from_settings(settings))
    nonce = os.urandom(12)
    ciphertext = aead.encrypt(nonce, plaintext.encode(), _aad(organization_id, name))
    return Sealed(ciphertext=ciphertext, nonce=nonce, key_version=1, last4=plaintext[-4:])


def open_secret(settings: Settings, sealed: Sealed, *, organization_id: str, name: str) -> str:
    aead = AESGCM(_key_from_settings(settings))
    try:
        return aead.decrypt(sealed.nonce, sealed.ciphertext, _aad(organization_id, name)).decode()
    except InvalidTag as exc:
        raise SecretError("secret could not be opened") from exc
