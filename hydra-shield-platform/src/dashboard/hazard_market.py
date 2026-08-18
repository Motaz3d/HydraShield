"""
HydraShield hazard-first commercial radar
(docs/COMMERCIAL_INTELLIGENCE.md).

Builds commercial opportunities FROM real hazard intelligence — never
from generic company lists:

    hazard signal (real snapshot entries)
    → region / country (parsed from the snapshot area name)
    → prospects in that geography (or with a matching hazard interest)
    → product fit (the segment's product matching + the lead's record)
    → why-now (the real current signal)
    → message + next action + evidence (source URLs, date_checked)

Honesty rules:

- A country is only matched when the snapshot area name actually contains
  the country name — an explicit, small mapping for the countries present
  in our lead records; no guessing.
- No prospect is invented; every output references a real lead record.
- The snapshot's hazard is wildfire (the current live grid); other
  hazards appear only when the platform computes them for an area.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Country name (as it appears in snapshot area names) → ISO-2, covering
#: the countries present in the lead workspace. Deliberately small and
#: explicit — extend only when a lead in a new country exists.
COUNTRY_NAME_TO_ISO = {
    "spain": "ES", "italy": "IT", "france": "FR", "portugal": "PT",
    "greece": "GR", "germany": "DE", "netherlands": "NL", "belgium": "BE",
    "luxembourg": "LU", "united kingdom": "GB", "uk": "GB",
    "switzerland": "CH", "austria": "AT", "poland": "PL",
    "croatia": "HR", "slovenia": "SI", "sweden": "SE", "denmark": "DK",
    "ireland": "IE", "finland": "FI", "norway": "NO",
    "czechia": "CZ", "czech republic": "CZ",
    # Asia (commercial radar expansion — leads/signals exist here)
    "china": "CN", "japan": "JP", "south korea": "KR", "korea": "KR",
    "singapore": "SG", "india": "IN", "indonesia": "ID",
    "philippines": "PH", "vietnam": "VN", "viet nam": "VN",
    "thailand": "TH", "malaysia": "MY",
}

#: The live snapshot is the wildfire product today; other hazards appear
#: here only when the platform computes them for the area.
SNAPSHOT_HAZARD = "wildfire"

#: Priority commercial segments (first experiment focus).
PRIORITY_SEGMENTS = {
    "environmental_consulting": "Climate / ESG Consulting",
    "investment": "Investment / Infrastructure",
    "insurance": "Insurance / Risk",
    "governments": "Governments / Municipalities",
    "real_estate": "Real Estate / Engineering",
    "research_centers": "Research / EO / GIS",
}


def area_country_iso(area_name: str) -> Optional[str]:
    """Extract the country from a snapshot area name
    (e.g. 'Andalusia (Huelva), Spain' → 'ES'). None when no known country
    name appears — never guessed."""
    text = (area_name or "").lower()
    for name, iso in COUNTRY_NAME_TO_ISO.items():
        if name in text:
            return iso
    return None


def _product_fit(lead: Dict, product_matching: Dict[str, list]) -> List[str]:
    """Product fit for a lead: its segment's matching list, else its own
    recommended product."""
    seg = lead.get("segment") or ""
    if seg in product_matching:
        return product_matching[seg]
    rec = lead.get("recommended_product")
    return [rec] if rec else []


def build_opportunities(
    leads: List[Dict],
    snapshot_entries: List[Dict],
    product_matching: Optional[Dict[str, list]] = None,
) -> List[Dict[str, Any]]:
    """Hazard-first opportunity list.

    For each elevated snapshot area, find prospects (a) in the same
    country (strong geographic match) or (b) with the hazard in their
    declared interests (weak match), restricted to priority segments.
    Every opportunity carries the full evidence chain.
    """
    product_matching = product_matching or {}
    opportunities: List[Dict[str, Any]] = []
    for entry in snapshot_entries or []:
        area_name = entry.get("name") or ""
        iso = area_country_iso(area_name)
        risk_class = entry.get("risk_class") or "unknown"
        for lead in leads or []:
            segment = lead.get("segment") or ""
            if segment not in PRIORITY_SEGMENTS:
                continue
            if lead.get("status", "open") in ("won", "lost"):
                continue
            in_country = bool(iso) and (lead.get("country") or "").upper() == iso
            hazard_interest = SNAPSHOT_HAZARD in (lead.get("relevant_hazards") or [])
            if not in_country and not hazard_interest:
                continue
            match = "geographic" if in_country else "hazard_interest"
            fit = _product_fit(lead, product_matching)
            opportunities.append({
                "hazard": SNAPSHOT_HAZARD,
                "area": area_name,
                "risk_class": risk_class,
                "country": iso,
                "organization": lead.get("organization"),
                "segment": segment,
                "segment_label": PRIORITY_SEGMENTS[segment],
                "priority": lead.get("priority", "medium"),
                "match": match,
                "problem": lead.get("identified_problem"),
                "product_fit": fit,
                "why_now": (f"{risk_class} wildfire risk currently computed "
                            f"for {area_name} (live platform snapshot)"),
                "message": lead.get("recommended_message"),
                "next_action": lead.get("next_action"),
                "evidence": {
                    "signal": "HydraShield live risk snapshot",
                    "lead_source": lead.get("source"),
                    "date_checked": lead.get("date_checked"),
                },
            })
    # Geographic matches first, then hazard-interest; high priority first.
    _prio = {"high": 0, "medium": 1, "low": 2}
    opportunities.sort(key=lambda o: (
        0 if o["match"] == "geographic" else 1,
        _prio.get(o["priority"], 3),
        o["organization"] or ""))
    # Dedupe per organization, keeping the strongest (first) match.
    seen = set()
    unique = []
    for o in opportunities:
        if o["organization"] in seen:
            continue
        seen.add(o["organization"])
        unique.append(o)
    return unique
