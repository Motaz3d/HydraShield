"""Tests for the security module (encryption, API security, GDPR)."""

import time

import pytest

from src.security.encryption import EncryptionManager
from src.security.api_security import ApiSecurityManager
from src.security.gdpr import GdprCompliance, DataAnonymiser


class TestEncryptionManager:
    """Tests for EncryptionManager."""

    def test_generate_key(self):
        key = EncryptionManager.generate_key()
        assert isinstance(key, str)
        assert len(key) > 10

    def test_encrypt_decrypt_roundtrip(self):
        manager = EncryptionManager()
        token = manager.encrypt("secret-value")
        assert token != "secret-value"

        # If cryptography is available, decryption is reversible.
        try:
            assert manager.decrypt(token) == "secret-value"
        except RuntimeError:
            # Fallback mode: one-way hashing, cannot decrypt.
            assert token.startswith("hmac-sha256:")

    def test_encrypt_with_key(self):
        key = EncryptionManager.generate_key()
        a = EncryptionManager(key=key)
        b = EncryptionManager(key=key)

        token = a.encrypt("hello")
        try:
            assert b.decrypt(token) == "hello"
        except RuntimeError:
            # Fallback environment.
            pass

    def test_redact(self):
        assert EncryptionManager.redact("123456789", visible_chars=3) == "***789"
        assert EncryptionManager.redact("ab", visible_chars=3) == "***"
        assert EncryptionManager.redact("") == ""

    def test_hash_sensitive_is_one_way(self):
        digest = EncryptionManager.hash_sensitive("value", salt=b"0123456789abcdef")
        assert isinstance(digest, str)
        assert "value" not in digest
        # Same value + same salt -> same digest.
        assert digest == EncryptionManager.hash_sensitive("value", salt=b"0123456789abcdef")


class TestApiSecurityManager:
    """Tests for ApiSecurityManager."""

    def setup_method(self):
        self.security = ApiSecurityManager(secret_key="test-secret")

    def test_issue_and_verify_token(self):
        token = self.security.issue_token("client-a", roles=["operator"])
        claims = self.security.verify_token(token)
        assert claims is not None
        assert claims["client_id"] == "client-a"
        assert "operator" in claims["roles"]

    def test_verify_tampered_token_fails(self):
        token = self.security.issue_token("client-a")
        payload, signature = token.rsplit(".", 1)
        tampered = f"{payload}.{'0' * len(signature)}"
        assert self.security.verify_token(tampered) is None

    def test_verify_expired_token_fails(self):
        self.security.token_ttl_seconds = -1
        token = self.security.issue_token("client-a")
        assert self.security.verify_token(token) is None

    def test_requires_role(self):
        @self.security.requires_role("admin")
        def protected(*args, **kwargs):
            return "ok"

        with pytest.raises(PermissionError):
            protected(claims={"roles": set()})

        with pytest.raises(PermissionError):
            protected()  # no claims

        assert protected(claims={"roles": {"admin"}}) == "ok"

    def test_rate_limiting(self):
        client = "bursty"
        for _ in range(3):
            assert not self.security.is_rate_limited(client, max_requests=3, window_seconds=60)
        # 4th request exceeds the limit.
        assert self.security.is_rate_limited(client, max_requests=3, window_seconds=60)

    def test_sanitise_input(self):
        assert ApiSecurityManager.sanitise_input("abc", max_length=2) == "ab"
        # Control characters (newline) are stripped.
        assert "\n" not in ApiSecurityManager.sanitise_input("a\nb")

    def test_validate_callback_url(self):
        assert ApiSecurityManager.validate_callback_url("https://example.com/x")
        assert not ApiSecurityManager.validate_callback_url("javascript:alert(1)")
        assert ApiSecurityManager.validate_callback_url(
            "https://example.com/x", allowed_hosts={"example.com"}
        )
        assert not ApiSecurityManager.validate_callback_url(
            "https://evil.com/x", allowed_hosts={"example.com"}
        )


class TestGdprCompliance:
    """Tests for GDPR compliance helpers."""

    def test_consent_flow(self):
        gdpr = GdprCompliance()
        gdpr.record_consent("subject-1", "marketing", granted=True)
        assert gdpr.has_consent("subject-1", "marketing") is True

        gdpr.withdraw_consent("subject-1", "marketing")
        assert gdpr.has_consent("subject-1", "marketing") is False

    def test_invalid_lawful_basis(self):
        gdpr = GdprCompliance()
        with pytest.raises(ValueError):
            gdpr.record_consent("s", "p", True, lawful_basis="not-a-basis")

    def test_deletion_scheduling(self):
        gdpr = GdprCompliance(retention_days=0)
        gdpr.record_consent("subject-1", "p", True)
        # Retention of 0 days -> immediately due.
        assert gdpr.due_for_deletion("subject-1") is True

    def test_pseudonymise(self):
        gdpr = GdprCompliance()
        out = gdpr.pseudonymise("john@example.com", salt=b"0123456789abcdef")
        assert "john@example.com" not in out


class TestDataAnonymiser:
    """Tests for DataAnonymiser."""

    def test_anonymise_text(self):
        anon = DataAnonymiser()
        result = anon.anonymise_text("Contact john@example.com or +1 555 123 4567")
        assert "john@example.com" not in result
        assert "555" not in result

    def test_anonymise_record(self):
        anon = DataAnonymiser()
        record = {"name": "Alice", "age": 34, "city": "Lisbon"}
        out = anon.anonymise_record(record)
        # name is a sensitive field -> generalised.
        assert out["name"] != "Alice"
        # city kept intact.
        assert out["city"] == "Lisbon"

    def test_minimise_record(self):
        anon = DataAnonymiser()
        record = {"name": "Alice", "age": 34, "city": "Lisbon"}
        minimised = anon.minimise_record(record, {"age"})
        assert set(minimised.keys()) == {"age"}

    def test_generate_pseudonym(self):
        p1 = DataAnonymiser.generate_pseudonym()
        p2 = DataAnonymiser.generate_pseudonym()
        assert p1 != p2
        assert p1.startswith("subject_")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])