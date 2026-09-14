"""Business-language labels for internal identifiers printed in reports.

Internal statuses, keys and enum values are machine contracts. A customer-facing
document must never print one as-is, so every renderer maps it through
:func:`human_label` — or through the vocabulary-specific label map owned by the
engine module that defines that vocabulary (for example
``src.climate.sustainability.coverage_label`` or
``src.dashboard.ignition.component_label``).

This module holds only the labels for values that have no engine-side home:
report provenance component keys, mapped-facility keys and generic statuses.
Anything not listed still renders as readable prose, never as ``snake_case``.
"""

from __future__ import annotations

from typing import Dict, Optional

#: Curated labels for internal keys that reach a report.
KEY_LABELS: Dict[str, str] = {
    # Report provenance components (the keys are internal identifiers).
    "landcover": "Land cover",
    "fire_danger": "Fire danger",
    "active_fires": "Active fires",
    "micro_area": "Micro-area",
    # Mapped OpenStreetMap facility counts (population / exposure layers).
    "hospitals": "Hospitals",
    "schools": "Schools",
    "fire_stations": "Fire stations",
    "power_facilities": "Power facilities",
    # Generic statuses.
    "ok": "Available",
    "unavailable": "Not available",
    "no_events": "No events recorded",
    "insufficient_data": "Insufficient data",
    "not_available": "Not available",
    "not_quantified": "Not quantified",
    "unknown": "Unknown",
}


def human_label(key: Optional[str], fallback: str = "—") -> str:
    """Return a readable, business-language label for an internal identifier.

    Curated labels win; anything else is title-cased with the underscores
    removed, so no internal identifier can leak into a customer-facing document.
    """
    if key is None or key == "":
        return fallback
    text = str(key)
    return KEY_LABELS.get(text, text.replace("_", " ").strip().capitalize())
