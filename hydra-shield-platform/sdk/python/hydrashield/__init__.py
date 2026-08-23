"""Talaix Python SDK — stdlib-only client for the public REST API.

Contract: docs/API_V2.md. Real data only: ``unavailable`` / ``key_required``
payloads are returned as data (never raised); only true errors
(``{"error", "status"}`` bodies on non-2xx responses) raise
:class:`TalaixError`.
"""

from .client import TalaixClient, TalaixError

__all__ = ["TalaixClient", "TalaixError"]
__version__ = "0.1.0"
