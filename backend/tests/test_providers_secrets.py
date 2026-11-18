import base64

import pytest

from app.core.config import Settings
from app.providers.secrets import SecretError, open_secret, seal


def _settings(**kw) -> Settings:
    base = {"app_env": "test", "secret_key": "test-signing-key-0123456789abcdef", "database_url": "postgresql://x"}
    base.update(kw)
    return Settings(**base)


def test_round_trip_and_last_four():
    s = _settings()
    sealed = seal(s, "sk-live-abcdef1234", organization_id="org-1", name="provider:openai")
    assert sealed.last4 == "1234"
    assert open_secret(s, sealed, organization_id="org-1", name="provider:openai") == "sk-live-abcdef1234"


def test_ciphertext_does_not_contain_the_plaintext():
    s = _settings()
    sealed = seal(s, "sk-canary-XYZ-98765", organization_id="o", name="n")
    assert b"canary" not in sealed.ciphertext
    assert b"98765" not in sealed.ciphertext


def test_each_seal_uses_a_fresh_nonce():
    s = _settings()
    a = seal(s, "same-secret-value", organization_id="o", name="n")
    b = seal(s, "same-secret-value", organization_id="o", name="n")
    assert a.nonce != b.nonce and a.ciphertext != b.ciphertext


def test_ciphertext_is_bound_to_its_organization_and_name():
    s = _settings()
    sealed = seal(s, "sk-bound-value-1111", organization_id="org-1", name="provider:a")
    with pytest.raises(SecretError):
        open_secret(s, sealed, organization_id="org-2", name="provider:a")
    with pytest.raises(SecretError):
        open_secret(s, sealed, organization_id="org-1", name="provider:b")


def test_tampered_ciphertext_is_rejected():
    s = _settings()
    sealed = seal(s, "sk-tamper-value-2222", organization_id="o", name="n")
    flipped = bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:]
    tampered = type(sealed)(ciphertext=flipped, nonce=sealed.nonce, key_version=sealed.key_version, last4=sealed.last4)
    with pytest.raises(SecretError):
        open_secret(s, tampered, organization_id="o", name="n")


def test_configured_key_is_used_and_must_be_32_bytes():
    key = base64.b64encode(b"k" * 32).decode()
    s = _settings(secret_encryption_key=key)
    sealed = seal(s, "sk-configured-3333", organization_id="o", name="n")
    assert open_secret(_settings(secret_encryption_key=key), sealed, organization_id="o", name="n") == "sk-configured-3333"
    with pytest.raises(SecretError):
        seal(_settings(secret_encryption_key=base64.b64encode(b"short").decode()), "x" * 9,
             organization_id="o", name="n")


def test_production_refuses_to_run_without_a_configured_key():
    with pytest.raises(SecretError):
        seal(_settings(app_env="production", secret_key="a-real-production-signing-key-value"), "sk-prod-44444",
             organization_id="o", name="n")


def test_empty_secret_is_refused():
    with pytest.raises(SecretError):
        seal(_settings(), "", organization_id="o", name="n")
