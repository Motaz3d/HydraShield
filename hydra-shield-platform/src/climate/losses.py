"""
Loss Data Registry v1 (docs/ECONOMIC_INTELLIGENCE.md — no-fake-money rule).

Loads ``config/loss_registry.json`` — the registry of documented
disaster-loss data sources (EM-DAT, DesInventar, World Bank/GFDRR, NOAA,
Munich Re, Swiss Re) with their access conditions and integration status —
and formalises the loss summary with the platform's strict separation of
observed / estimated / modelled / projected figures.

Honesty contract (absolute):

- No loss figures exist in integrated sources. ``observed_events`` in the
  registry is EMPTY and the observed block says exactly:
  "No documented loss figures in integrated sources."
- Estimated, modelled and projected blocks are each ``not_available`` with
  an explicit statement — never merged, never invented.
- Registry sources are research candidates unless explicitly marked
  ``integrated``; candidate records carry real official URLs and their
  access/licence conditions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from .economic_impact import OBSERVED_LOSSES_STATEMENT
from .ontology import Confidence

_DEFAULT_REGISTRY = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "loss_registry.json"
)

_VALID_SOURCE_STATUS = ("candidate", "integrated", "unavailable")
_VALID_SOURCE_ACCESS = ("registration_required", "api", "download")

ESTIMATED_LOSSES_STATEMENT = "No estimated loss figures exist in integrated sources."
MODELLED_LOSSES_STATEMENT = "No modelled loss figures exist in integrated sources."
PROJECTED_LOSSES_STATEMENT = "No projected loss figures exist in integrated sources."


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_loss_registry(path: str | None = None) -> Dict[str, Any]:
    registry_path = path or os.environ.get("HYDRASHIELD_LOSS_REGISTRY") or _DEFAULT_REGISTRY
    with open(registry_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_loss_registry(registry: Dict[str, Any]) -> List[str]:
    """Structural validation; returns a list of problems (empty = valid)."""

    problems: List[str] = []
    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append("no sources declared")
        sources = []
    seen: set = set()
    for i, src in enumerate(sources):
        sid = src.get("id")
        if not sid:
            problems.append(f"source {i}: missing id")
        elif sid in seen:
            problems.append(f"source {i}: duplicate id '{sid}'")
        seen.add(sid)
        for field in ("name", "provider", "url", "coverage", "status"):
            if not src.get(field):
                problems.append(f"source '{sid}': missing {field}")
        url = str(src.get("url") or "")
        if url and not url.startswith("https://"):
            problems.append(f"source '{sid}': url must be https")
        if src.get("access") not in _VALID_SOURCE_ACCESS:
            problems.append(
                f"source '{sid}': access must be one of {list(_VALID_SOURCE_ACCESS)}")
        if src.get("status") not in _VALID_SOURCE_STATUS:
            problems.append(
                f"source '{sid}': status must be one of {list(_VALID_SOURCE_STATUS)}")
    events = registry.get("observed_events")
    if not isinstance(events, list):
        problems.append("observed_events must be a list (empty until a "
                        "documented source is integrated)")
    if not registry.get("separation_note"):
        problems.append("missing separation_note")
    return problems


def loss_sources() -> List[Dict[str, Any]]:
    """The registry's source records (candidates unless marked integrated)."""

    return list(load_loss_registry().get("sources") or [])


def loss_summary() -> Dict[str, Any]:
    """The loss summary with strict observed/estimated/modelled/projected
    separation. No loss figures exist in integrated sources — the observed
    block says exactly that; the other blocks are not_available."""

    registry = load_loss_registry()
    sources = registry.get("sources") or []
    events = registry.get("observed_events") or []
    integrated = [s for s in sources if s.get("status") == "integrated"]
    reviewed = [s.get("id") for s in sources if s.get("id")]

    if events:
        observed_losses = {
            "status": "ok",
            "statement": f"{len(events)} documented loss event(s) from "
                         "integrated sources.",
            "event_count": len(events),
            "sources_integrated": [s.get("id") for s in integrated],
            "confidence": Confidence.LOW.value,
        }
    else:
        observed_losses = {
            "status": "unavailable",
            "statement": OBSERVED_LOSSES_STATEMENT,
            "sources_reviewed": reviewed,
            "confidence": Confidence.LOW.value,
        }

    by_status: Dict[str, int] = {}
    for s in sources:
        by_status[str(s.get("status"))] = by_status.get(str(s.get("status")), 0) + 1

    return {
        "status": "ok",
        "generated_at": _utcnow_iso(),
        "observed_losses": observed_losses,
        "estimated_losses": {
            "status": "not_available",
            "statement": ESTIMATED_LOSSES_STATEMENT,
            "confidence": Confidence.LOW.value,
        },
        "modelled_losses": {
            "status": "not_available",
            "statement": MODELLED_LOSSES_STATEMENT,
            "confidence": Confidence.LOW.value,
        },
        "projected_losses": {
            "status": "not_available",
            "statement": PROJECTED_LOSSES_STATEMENT,
            "confidence": Confidence.LOW.value,
        },
        "separation_note": registry.get("separation_note"),
        "registry": {
            "registry_id": registry.get("registry_id"),
            "version": registry.get("version"),
            "config": "config/loss_registry.json",
            "source_count": len(sources),
            "sources_by_status": by_status,
            "observed_event_count": len(events),
        },
        "limitations": [
            "No loss figure (observed, estimated, modelled or projected) is "
            "produced anywhere in this payload.",
            "Registry sources marked 'candidate' are reviewed entry points "
            "only — none is integrated; access and licence conditions are "
            "stated per source.",
        ],
    }
