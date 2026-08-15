"""
API security utilities for HydraShield.

Implements lightweight, dependency-free authentication, authorization, and
rate-limiting primitives suitable for integrating with the dashboard's Flask
APIs while remaining usable in tests and constrained environments.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set


def _constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to mitigate timing attacks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


@dataclass
class ApiSecurityManager:
    """
    Manage API authentication, authorization, and rate limiting.

    Parameters
    ----------
    secret_key : str
        Shared secret used to sign API tokens. In production this must be
        supplied from a secure store, not hard-coded.
    token_ttl_seconds : int
        Time-to-live for issued tokens in seconds.
    realm : str
        Auth realm name used in WWW-Authenticate challenge headers.
    """

    secret_key: str
    token_ttl_seconds: int = 3600
    realm: str = "HydraShieldAPI"

    _tokens: Dict[str, Dict] = field(default_factory=dict)
    _roles: Dict[str, Set[str]] = field(default_factory=dict)
    _rate_limit_buckets: Dict[str, List[float]] = field(default_factory=dict)

    # ---- Token management -------------------------------------------------

    def issue_token(self, client_id: str, roles: Optional[List[str]] = None) -> str:
        """
        Issue a signed, time-limited bearer token for a client.

        The token is HMAC-SHA256 signed and embeds the client id, roles, and an
        expiry timestamp, all verifiable without server-side session storage.
        """
        roles = roles or []
        issued = int(time.time())
        expiry = issued + self.token_ttl_seconds
        role_part = ",".join(sorted(roles))
        payload = f"{client_id}|{role_part}|{issued}|{expiry}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        token = f"{payload}.{signature}"
        self._tokens[client_id] = {"expiry": expiry, "roles": set(roles)}
        return token

    def verify_token(self, token: str) -> Optional[Dict]:
        """
        Verify a bearer token and return its claims if valid.

        Returns ``None`` if the token is malformed, expired, or has an invalid
        signature.
        """
        try:
            payload, signature = token.rsplit(".", 1)
        except ValueError:
            return None

        expected = hmac.new(
            self.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not _constant_time_compare(signature, expected):
            return None

        try:
            client_id, role_part, issued, expiry = payload.split("|")
        except ValueError:
            return None

        if int(expiry) < int(time.time()):
            return None

        roles = set(role_part.split(",")) if role_part else set()
        return {
            "client_id": client_id,
            "roles": roles,
            "issued_at": int(issued),
            "expires_at": int(expiry),
        }

    # ---- Authorization ----------------------------------------------------

    def requires_role(self, role: str) -> Callable:
        """
        Decorator that enforces a required role on a view function.

        The decorated function receives a ``claims`` keyword argument. In a
        production Flask app, an HTTP bearer token would be parsed from the
        request and passed in; here claims are expected to be supplied by the
        caller or middleware.
        """

        def decorator(func: Callable) -> Callable:
            def wrapper(*args, **kwargs):
                claims = kwargs.pop("claims", None)
                if claims is None:
                    raise PermissionError("Missing authentication claims.")
                roles = claims.get("roles", set())
                if role not in roles:
                    raise PermissionError(f"Missing required role: {role}")
                return func(*args, **kwargs)

            return wrapper

        return decorator

    def has_role(self, claims: Optional[Dict], role: str) -> bool:
        """Return True if ``claims`` contains ``role``."""
        if not claims:
            return False
        return role in claims.get("roles", set())

    def assign_roles(self, client_id: str, roles: List[str]) -> None:
        """Assign roles to a client id (server-side role registry)."""
        self._roles[client_id] = set(roles)

    def get_roles(self, client_id: str) -> Set[str]:
        """Return the roles assigned to a client id."""
        return self._roles.get(client_id, set())

    # ---- Rate limiting ----------------------------------------------------

    def is_rate_limited(
        self,
        client_id: str,
        max_requests: int,
        window_seconds: int,
        now: Optional[float] = None,
    ) -> bool:
        """
        Return True if ``client_id`` has exceeded ``max_requests`` within the
        sliding ``window_seconds`` window.
        """
        now = now if now is not None else time.time()
        bucket = self._rate_limit_buckets.setdefault(client_id, [])

        # Prune timestamps outside the window.
        cutoff = now - window_seconds
        bucket[:] = [ts for ts in bucket if ts >= cutoff]

        if len(bucket) >= max_requests:
            return True

        bucket.append(now)
        return False

    def reset_rate_limit(self, client_id: str) -> None:
        """Clear the rate-limit history for a client id."""
        self._rate_limit_buckets.pop(client_id, None)

    # ---- Input sanitisation ----------------------------------------------

    @staticmethod
    def sanitise_input(value: str, max_length: int = 512) -> str:
        """
        Basic input sanitisation: strip control characters and truncate.

        This is a defensive measure, not a replacement for framework-level
        escaping of user-supplied data in views and SQL.
        """
        import unicodedata

        value = value or ""
        cleaned = "".join(
            ch for ch in value if unicodedata.category(ch)[0] != "C"
        )
        return cleaned[:max_length]

    @staticmethod
    def validate_callback_url(url: str, allowed_hosts: Optional[Set[str]] = None) -> bool:
        """
        Validate a callback/redirect URL to prevent open-redirect attacks.

        Only URLs whose scheme is http/https and whose host is in
        ``allowed_hosts`` (when provided) are permitted.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if allowed_hosts is not None and parsed.netloc not in allowed_hosts:
            return False
        return True