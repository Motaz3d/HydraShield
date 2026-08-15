"""
HydraShield Security Module.

Provides security and privacy utilities for the platform:
    - encryption:    Encryption of sensitive data at rest and in transit.
    - api_security:  API authentication, authorization, and rate limiting.
    - gdpr:          GDPR compliance helpers (consent, anonymisation, minimisation).
"""

__version__ = "0.1.0"
__all__ = [
    "EncryptionManager",
    "ApiSecurityManager",
    "GdprCompliance",
    "DataAnonymiser",
]

from .encryption import EncryptionManager
from .api_security import ApiSecurityManager
from .gdpr import GdprCompliance, DataAnonymiser