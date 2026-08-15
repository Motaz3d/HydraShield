"""
GDPR compliance helpers for HydraShield.

Provides utilities for consent management, data minimisation, anonymisation,
and data subject request handling, aligned with the EU General Data Protection
Regulation (GDPR) requirements relevant to the platform.
"""

from __future__ import annotations

import hashlib
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from .encryption import EncryptionManager

# Regex patterns for common identifiers (best-effort detection).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


@dataclass
class GdprCompliance:
    """
    Track and enforce GDPR-related consent and data-subject requests.

    Parameters
    ----------
    retention_days : int
        Default data retention period in days.
    lawful_bases : Set[str]
        Lawful bases recognised by the platform (e.g., consent, legitimate
        interest, public task).
    """

    retention_days: int = 365
    lawful_bases: Set[str] = field(
        default_factory=lambda: {
            "consent",
            "contract",
            "legal_obligation",
            "vital_interests",
            "public_task",
            "legitimate_interests",
        }
    )

    _consent_records: Dict[str, Dict] = field(default_factory=dict)
    _deletion_queue: Dict[str, datetime] = field(default_factory=dict)

    def record_consent(
        self,
        data_subject_id: str,
        purpose: str,
        granted: bool,
        lawful_basis: str = "consent",
        recorded_at: Optional[datetime] = None,
    ) -> Dict:
        """
        Record a data subject's consent decision for a given processing
        purpose.

        Returns the stored consent record.
        """
        if lawful_basis not in self.lawful_bases:
            raise ValueError(f"Unsupported lawful basis: {lawful_basis}")

        recorded_at = recorded_at or datetime.now(timezone.utc)
        record = {
            "data_subject_id": data_subject_id,
            "purpose": purpose,
            "granted": bool(granted),
            "lawful_basis": lawful_basis,
            "recorded_at": recorded_at.isoformat(),
            "expires_at": (recorded_at + timedelta(days=self.retention_days)).isoformat(),
        }
        key = f"{data_subject_id}:{purpose}"
        self._consent_records[key] = record

        # Schedule automatic deletion at the end of the retention period.
        self._deletion_queue[data_subject_id] = recorded_at + timedelta(days=self.retention_days)
        return record

    def has_consent(self, data_subject_id: str, purpose: str) -> bool:
        """Return True if valid consent is on file for the purpose."""
        record = self._consent_records.get(f"{data_subject_id}:{purpose}")
        if not record:
            return False
        if record["lawful_basis"] == "consent" and not record["granted"]:
            return False
        return True

    def withdraw_consent(self, data_subject_id: str, purpose: str) -> None:
        """Withdraw consent for a purpose (GDPR right to withdraw)."""
        key = f"{data_subject_id}:{purpose}"
        if key in self._consent_records:
            self._consent_records[key]["granted"] = False

    def request_deletion(self, data_subject_id: str) -> None:
        """Queue a data subject for deletion (GDPR right to erasure)."""
        self._deletion_queue[data_subject_id] = datetime.now(timezone.utc)

    def due_for_deletion(self, data_subject_id: str, now: Optional[datetime] = None) -> bool:
        """Return True if the subject's retention window has elapsed."""
        now = now or datetime.now(timezone.utc)
        scheduled = self._deletion_queue.get(data_subject_id)
        return scheduled is not None and scheduled <= now

    def pseudonymise(self, value: str, salt: Optional[bytes] = None) -> str:
        """Pseudonymise a value using a salted irreversible hash."""
        return EncryptionManager.hash_sensitive(value, salt)


@dataclass
class DataAnonymiser:
    """
    Anonymise structured records containing personal data.

    Provides k-anonymity-inspired generalisation and randomisation helpers that
    reduce the risk of re-identification while retaining analytical utility.
    """

    sensitive_fields: Set[str] = field(
        default_factory=lambda: {
            "name",
            "email",
            "phone",
            "address",
            "id_number",
            "ip_address",
        }
    )
    rng: random.Random = field(default_factory=lambda: random.Random(42))

    def anonymise_text(self, value: str) -> str:
        """Mask common identifiers (emails and phone numbers) in text."""
        value = value or ""
        value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
        value = _PHONE_RE.sub("[REDACTED_PHONE]", value)
        return value

    def anonymise_record(self, record: Dict) -> Dict:
        """
        Anonymise a single record by removing or generalising sensitive fields.

        Fields listed in ``sensitive_fields`` are dropped or masked.
        """
        result = {}
        for key, val in record.items():
            if key in self.sensitive_fields:
                result[key] = self._generalise(val)
            else:
                result[key] = val
        return result

    def anonymise_dataset(self, records: List[Dict]) -> List[Dict]:
        """Anonymise a dataset of records."""
        return [self.anonymise_record(r) for r in records]

    def _generalise(self, value) -> object:
        """Generalise a value to reduce identifiability."""
        if isinstance(value, str):
            # Keep only the first character and length class for strings.
            if len(value) <= 2:
                return f"{value[:1]}*"
            return f"{value[:1]}{'*' * (len(value) - 1)}"
        if isinstance(value, (int, float)):
            # Generalise numbers by dropping precision.
            if isinstance(value, float):
                return round(value / 10) * 10
            return (value // 10) * 10
        return None

    @staticmethod
    def generate_pseudonym(prefix: str = "subject") -> str:
        """Generate a random pseudonymous identifier."""
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def minimise_record(self, record: Dict, needed_fields: Set[str]) -> Dict:
        """
        Apply data minimisation: keep only the fields needed to fulfil a
        stated purpose.
        """
        return {k: v for k, v in record.items() if k in needed_fields}