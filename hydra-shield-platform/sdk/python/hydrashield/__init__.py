"""Talaix Python SDK — stdlib-only client for the public REST API.

Contract: docs/API_V2.md. Real data only: ``unavailable`` / ``key_required``
payloads are returned as data (never raised); only true errors
(``{"error", "status"}`` bodies on non-2xx responses) raise
:class:`TalaixError`.

Two clients: :class:`TalaixClient` for the v1/v2 platform API, and
:class:`TxClient` for the TX Engine API (``/api/tx/*`` — uniform TxResult
envelope + the standard Job Object for deep analyses).
"""

from .client import TalaixClient, TalaixError
from .tx import TxClient

__all__ = ["TalaixClient", "TalaixError", "TxClient"]
__version__ = "0.2.0"
