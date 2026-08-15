"""
Encryption utilities for HydraShield sensitive data.

Provides symmetric encryption at rest using the `cryptography` library when
available, with a graceful fallback to one-way hashing for environments where
the optional dependency is not installed.

Only standard-library and optional-dependency imports are used so that the core
platform remains installable without additional packages.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Dict, Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    _HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - exercised only in restricted environments
    _HAS_CRYPTOGRAPHY = False


class EncryptionManager:
    """
    Manage encryption of sensitive data at rest.

    Parameters
    ----------
    key : Optional[str]
        Base64-encoded Fernet key. If omitted, a new random key is generated.
        In production, this key MUST come from a secure secret store (e.g., a
        cloud KMS or environment variable) and never be committed to source.
    salt : bytes
        Salt used for key derivation when deriving a key from a passphrase.
    """

    def __init__(self, key: Optional[str] = None, salt: Optional[bytes] = None):
        self.salt = salt if salt is not None else os.urandom(16)
        self._key = key

        if _HAS_CRYPTOGRAPHY:
            if key is None:
                # Generate a fresh key for ephemeral use (e.g., tests).
                self._fernet = Fernet(Fernet.generate_key())
            else:
                self._fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
        else:
            self._fernet = None

    @staticmethod
    def generate_key() -> str:
        """Generate and return a new Fernet key as a string."""
        if _HAS_CRYPTOGRAPHY:
            return Fernet.generate_key().decode("ascii")
        # Fallback: a random URL-safe token is NOT a Fernet key, but is
        # returned so callers can still obtain a secret for hashing fallback.
        return secrets.token_urlsafe(32)

    @classmethod
    def derive_key_from_passphrase(
        cls, passphrase: str, salt: Optional[bytes] = None, length: int = 32
    ) -> bytes:
        """
        Derive a key from a passphrase using PBKDF2-HMAC-SHA256.

        This is intended to help users turn human-memorable secrets into
        encryption keys. In production, prefer a dedicated secret manager.
        """
        if _HAS_CRYPTOGRAPHY:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=length,
                salt=salt if salt is not None else os.urandom(16),
                iterations=390_000,
            )
            return kdf.derive(passphrase.encode("utf-8"))
        # Fallback using hashlib.pbkdf2_hmac (standard library).
        return hashlib.pbkdf2_hmac(
            "sha256",
            passphrase.encode("utf-8"),
            salt if salt is not None else os.urandom(16),
            390_000,
            dklen=length,
        )

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.

        Returns a base64 token. If the `cryptography` library is unavailable,
        the value is stored as a one-way HMAC digest and the original cannot be
        recovered, which still protects confidentiality at rest.
        """
        if _HAS_CRYPTOGRAPHY and self._fernet is not None:
            encrypted = self._fernet.encrypt(plaintext.encode("utf-8"))
            return encrypted.decode("ascii")

        # Fallback: one-way digest. Prefix makes the encoding explicit.
        digest = hmac.new(self._key_bytes(), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    def decrypt(self, token: str) -> str:
        """
        Decrypt a token produced by :meth:`encrypt`.

        Raises
        ------
        RuntimeError
            If strong encryption is unavailable (fallback mode) because the
            fallback is one-way and cannot be reversed.
        """
        if not _HAS_CRYPTOGRAPHY or self._fernet is None:
            raise RuntimeError(
                "Strong decryption is unavailable: install the 'cryptography' "
                "package to enable reversible encryption."
            )

        if token.startswith("hmac-sha256:"):
            raise ValueError("Token was created in one-way hashing fallback mode and cannot be decrypted.")

        decrypted = self._fernet.decrypt(token.encode("utf-8"))
        return decrypted.decode("utf-8")

    def _key_bytes(self) -> bytes:
        """Return raw key bytes for fallback HMAC operations."""
        if self._key is None:
            return b"hydrashield-fallback-key"
        if isinstance(self._key, str):
            return self._key.encode("utf-8")
        return self._key

    @staticmethod
    def redact(value: str, visible_chars: int = 3, mask: str = "***") -> str:
        """
        Redact a sensitive value for logging and display.

        Only the last ``visible_chars`` characters are kept; the rest are
        replaced with ``mask``.
        """
        if not value:
            return ""
        if len(value) <= visible_chars:
            return mask
        return f"{mask}{value[-visible_chars:]}"

    @staticmethod
    def hash_sensitive(value: str, salt: Optional[bytes] = None) -> str:
        """Return a salted one-way SHA-256 hash of a sensitive value."""
        salt = salt if salt is not None else os.urandom(16)
        digest = hashlib.sha256(salt + value.encode("utf-8")).hexdigest()
        return f"{base64.b64encode(salt).decode('ascii')}${digest}"