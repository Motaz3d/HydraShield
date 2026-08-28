"""
Comprehensive organization inventory engine.

Deep-scans companies, institutions and government bodies across sectors and
countries via Wikidata SPARQL, feeding the marketing leads workspace.

Honesty contract (HARD):
    - Websites come ONLY from Wikidata P856 (the OPTIONAL ?website in the
      SPARQL query). No guessed, inferred or invented domains.
    - Rows without a P856 website are NEVER turned into leads; they go to the
      pending snapshot with a clear reason.
    - Organization names and country attribution come from Wikidata; unresolved
      concepts or countries are recorded as skipped, never fabricated.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .signatories import (
    _best_wikidata_entity,
    _wikidata_requests_get,
    normalise_org,
)

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
_WB_SEARCH_URL = "https://www.wikidata.org/w/api.php?action=wbsearchentities&search={query}&language=en&format=json&limit=3"

_ENTITY_QID_CACHE: Dict[str, Optional[str]] = {}

# ---------------------------------------------------------------------------
# Scan matrix
# ---------------------------------------------------------------------------

TARGETS: List[Dict[str, Any]] = [
    {"concept_label": "bank", "concept_hint": "bank", "segment": "banking", "apply_to": "ALL"},
    {"concept_label": "central bank", "concept_hint": "central bank", "segment": "banking", "apply_to": "ALL"},
    {"concept_label": "insurance company", "concept_hint": "insurance company", "segment": "insurance", "apply_to": "ALL"},
    {"concept_label": "investment company", "concept_hint": "investment company", "segment": "investment", "apply_to": "ALL"},
    {"concept_label": "asset management company", "concept_hint": "asset management company", "segment": "investment", "apply_to": "ALL"},
    {"concept_label": "pension fund", "concept_hint": "pension fund", "segment": "investment", "apply_to": "ALL"},
    {"concept_label": "sovereign wealth fund", "concept_hint": "sovereign wealth fund", "segment": "investment", "apply_to": "ALL"},
    {"concept_label": "real estate company", "concept_hint": "real estate company", "segment": "real_estate", "apply_to": "ALL"},
    {"concept_label": "real estate investment trust", "concept_hint": "real estate investment trust", "segment": "real_estate", "apply_to": "ALL"},
    {"concept_label": "ministry of the environment", "concept_hint": "ministry of the environment", "segment": "governments", "apply_to": "ALL"},
    {"concept_label": "government agency", "concept_hint": "government agency", "segment": "governments", "apply_to": "ALL"},
    {"concept_label": "meteorological service", "concept_hint": "meteorological service", "segment": "governments", "apply_to": "ALL"},
    {"concept_label": "disaster management agency", "concept_hint": "disaster management agency", "segment": "governments", "apply_to": "ALL"},
    {"concept_label": "university", "concept_hint": "university", "segment": "research_centers", "apply_to": "ALL"},
    {"concept_label": "research institute", "concept_hint": "research institute", "segment": "research_centers", "apply_to": "ALL"},
    # Consultants — the full professional-services field (engineering,
    # management, audit, architecture), not only environmental boutiques.
    # concept_hint is the wbsearchentities label resolved to a Q-id.
    {"concept_label": "consulting company", "concept_hint": "consulting company", "segment": "consultants", "apply_to": "ALL"},
    {"concept_label": "management consultancy", "concept_hint": "management consultancy", "segment": "consultants", "apply_to": "ALL"},
    {"concept_label": "engineering firm", "concept_hint": "engineering firm", "segment": "consultants", "apply_to": "ALL"},
    {"concept_label": "accounting firm", "concept_hint": "accounting firm", "segment": "consultants", "apply_to": "ALL"},
    {"concept_label": "audit firm", "concept_hint": "audit firm", "segment": "consultants", "apply_to": "ALL"},
    {"concept_label": "architectural firm", "concept_hint": "architectural firm", "segment": "consultants", "apply_to": "ALL"},
]

# ISO-3166-1 alpha-2 → Wikidata English label (resolved to Q-id at runtime).
COUNTRIES: Dict[str, str] = {
    # East Asia
    "CN": "China",
    "JP": "Japan",
    "KR": "South Korea",
    "TW": "Taiwan",
    "HK": "Hong Kong",
    "MN": "Mongolia",
    # Southeast Asia
    "SG": "Singapore",
    "ID": "Indonesia",
    "MY": "Malaysia",
    "TH": "Thailand",
    "VN": "Vietnam",
    "PH": "Philippines",
    "MM": "Myanmar",
    "KH": "Cambodia",
    "LA": "Laos",
    "BN": "Brunei",
    "TL": "East Timor",
    # Europe focus
    "LU": "Luxembourg",
    "BE": "Belgium",
    "NL": "Netherlands",
    "DE": "Germany",
    "FR": "France",
    "CH": "Switzerland",
    "AT": "Austria",
    "DK": "Denmark",
    "FI": "Finland",
    "SE": "Sweden",
    "NO": "Norway",
    "PL": "Poland",
    "CZ": "Czech Republic",
    "HR": "Croatia",
    "RO": "Romania",
    "PT": "Portugal",
    "ES": "Spain",
    "IT": "Italy",
    "GR": "Greece",
    "GB": "United Kingdom",
}

# ---------------------------------------------------------------------------
# Segment-specific lead content (mirrors the signatory builder pattern)
# ---------------------------------------------------------------------------

_SEGMENT_ROLE = {
    "banking": "Chief Risk Officer",
    "insurance": "Chief Risk Officer",
    "investment": "Investment Director",
    "real_estate": "Asset Manager",
    "governments": "Climate Policy Officer",
    "research_centers": "Research Director",
    "consultants": "Chief Sustainability Officer",
}

_SEGMENT_PRODUCT = {
    "banking": "portfolio_screening",
    "insurance": "portfolio_screening",
    "investment": "api",
    "real_estate": "professional_report",
    "governments": "organization_account",
    "research_centers": "organization_account",
    "consultants": "professional_report",
}

_SEGMENT_CAPABILITY = {
    "banking": "portfolio-location climate-risk screening with traceable evidence",
    "insurance": "portfolio-location climate-risk screening with traceable evidence",
    "investment": "multi-location exposure screening and monitoring",
    "real_estate": "site screening across six hazards with documented sources",
    "governments": "regional multi-hazard intelligence and annual reports",
    "research_centers": "reproducible, content-hashed hazard analysis and open registries",
    "consultants": "audit-grade climate evidence for client deliverables (CSRD, EUDR, site assessments)",
}

_SEGMENT_PROBLEM = {
    "banking": "loan-book and collateral locations need documented climate exposure evidence",
    "insurance": "portfolio exposure to wildfire, flood and coastal hazards is hard to evidence per location",
    "investment": "due diligence lacks traceable climate evidence and portfolio concentration is under-measured",
    "real_estate": "site selection and disclosure need documented climate exposure with sources",
    "governments": "national and regional resilience planning needs traceable multi-hazard evidence",
    "research_centers": "reproducible research requires provenance-carrying analysis and open registries",
    "consultants": "client engagements need defensible, source-cited climate evidence without days of manual research",
}

_SEGMENT_PAIN = {
    "banking": "Needs location-level climate evidence for credit files and regulatory disclosure.",
    "insurance": "Needs per-location hazard evidence to support underwriting judgement.",
    "investment": "Needs documented exposure context for held assets and new acquisitions.",
    "real_estate": "Needs source-attached site reports for buyers, lenders and disclosure.",
    "governments": "Needs territorial intelligence with primary institutional sources for planning.",
    "research_centers": "Needs open, versioned evidence pipelines that can be reproduced and cited.",
}

_SEGMENT_EVIDENCE = {
    "banking": "location screening API with source-attached results",
    "insurance": "per-location multi-hazard screening with provenance",
    "investment": "multi-location exposure screening and historical event context",
    "real_estate": "site-specific PDF reports with traceable methodology",
    "governments": "regional analysis and annual intelligence reports",
    "research_centers": "content-hashed analysis runs and public source registries",
}

_SEGMENT_FIT = {
    "banking": "Financial institution with asset locations that need climate evidence.",
    "insurance": "Insurer with insured locations that benefit from documented hazard context.",
    "investment": "Investor or asset manager with portfolio locations to screen.",
    "real_estate": "Real-estate owner or developer with physical assets to assess.",
    "governments": "Government body responsible for resilience, policy or territorial planning.",
    "research_centers": "Research institution that values reproducible, evidence-labelled analysis.",
}

TODAY = date.today().isoformat()


def _source_url_from_qid(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}"


def resolve_entity_qid(name: str, fetch: Optional[Callable[[str, float], Any]] = None) -> Optional[str]:
    """
    Resolve a Wikidata entity name to its Q-id using wbsearchentities.

    The result is cached in-process for the duration of the run. ``fetch`` is
    injectable for tests and must behave like ``requests.get``.
    """
    norm = normalise_org(name)
    if not norm:
        return None
    if norm in _ENTITY_QID_CACHE:
        return _ENTITY_QID_CACHE[norm]

    fetcher = fetch or _wikidata_requests_get
    try:
        url = _WB_SEARCH_URL.format(query=urllib.parse.quote_plus(name))
        resp = fetcher(url, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        entity = _best_wikidata_entity(data.get("search", []), name)
        qid = entity["id"] if entity else None
        _ENTITY_QID_CACHE[norm] = qid
        return qid
    except Exception:
        _ENTITY_QID_CACHE[norm] = None
        return None


def inventory_query(concept_qid: str, country_qid: str, limit: int = 200) -> str:
    """Build the Wikidata SPARQL query for organizations of a concept in a country."""
    return (
        "SELECT ?org ?orgLabel ?website WHERE {"
        f"  ?org wdt:P31/wdt:P279* wd:{concept_qid}."
        f"  ?org wdt:P17 wd:{country_qid}."
        "  OPTIONAL { ?org wdt:P856 ?website }"
        '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }'
        f"}} LIMIT {int(limit)}"
    )


def sparql(query: str, fetch: Optional[Callable[[str, float], Any]] = None) -> List[Dict[str, Any]]:
    """
    Run a SPARQL SELECT against the Wikidata query service.

    Returns the list of result bindings. ``fetch`` is injectable for tests.
    """
    fetcher = fetch or _wikidata_requests_get
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    url = f"{SPARQL_ENDPOINT}?{params}"
    try:
        resp = fetcher(url, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", {}).get("bindings", [])
    except Exception:
        return []


def _qid_from_uri(uri: str) -> str:
    """Extract a Q-id from a Wikidata entity URI, or return the value as-is."""
    if not uri:
        return ""
    if uri.startswith("http://www.wikidata.org/entity/"):
        return uri.split("/")[-1]
    return uri


def _binding_value(binding: Dict[str, Any], key: str) -> Optional[str]:
    val = binding.get(key, {})
    return val.get("value") if isinstance(val, dict) else None


def _active_targets(concepts: Optional[List[str]]) -> List[Dict[str, Any]]:
    if not concepts:
        return list(TARGETS)
    wanted = {c.lower().strip() for c in concepts}
    return [t for t in TARGETS if t["concept_label"].lower() in wanted]


def _active_countries(countries: Optional[List[str]]) -> List[Tuple[str, str]]:
    if not countries:
        return list(COUNTRIES.items())
    codes = {c.upper().strip() for c in countries}
    return [(code, name) for code, name in COUNTRIES.items() if code in codes]


def run_inventory(
    countries: Optional[List[str]] = None,
    concepts: Optional[List[str]] = None,
    limit_per_query: int = 200,
    sleep_s: float = 1.0,
    fetch: Optional[Callable[[str, float], Any]] = None,
    progress: Optional[Callable[[str, str, int], None]] = None,
) -> Dict[str, Any]:
    """
    Run the organization inventory sweep.

    Returns a dict with ``rows``, ``counts``, ``skipped`` and
    ``capped_queries``. Each row contains ``organization``, ``country_code``,
    ``segment``, ``website`` (or None), ``wikidata_id``, ``concepts`` and
    ``source_url``.
    """
    targets = _active_targets(concepts)
    country_items = _active_countries(countries)

    skipped: List[Dict[str, str]] = []
    concept_qids: Dict[str, str] = {}
    country_qids: Dict[str, str] = {}

    for target in targets:
        qid = resolve_entity_qid(target["concept_hint"], fetch=fetch)
        if qid:
            concept_qids[target["concept_label"]] = qid
        else:
            skipped.append({
                "kind": "concept",
                "label": target["concept_label"],
                "reason": "Could not resolve concept to a Wikidata Q-id",
            })

    for code, name in country_items:
        qid = resolve_entity_qid(name, fetch=fetch)
        if qid:
            country_qids[code] = qid
        else:
            skipped.append({
                "kind": "country",
                "code": code,
                "label": name,
                "reason": "Could not resolve country to a Wikidata Q-id",
            })

    counts = {
        "queries": 0,
        "hits": 0,
        "unique_orgs": 0,
        "with_website": 0,
        "without_website": 0,
    }
    capped_queries: List[Dict[str, str]] = []
    # Dedupe key -> row
    rows_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for target in targets:
        concept_label = target["concept_label"]
        concept_qid = concept_qids.get(concept_label)
        if not concept_qid:
            continue
        segment = target["segment"]

        for code, _name in country_items:
            country_qid = country_qids.get(code)
            if not country_qid:
                continue

            query = inventory_query(concept_qid, country_qid, limit=limit_per_query)
            bindings = sparql(query, fetch=fetch)
            counts["queries"] += 1
            counts["hits"] += len(bindings)

            if len(bindings) >= limit_per_query:
                capped_queries.append({
                    "concept": concept_label,
                    "country": code,
                    "limit": limit_per_query,
                    "reason": "Query hit the LIMIT cap; result may be incomplete",
                })

            for binding in bindings:
                org_uri = _binding_value(binding, "org") or ""
                org_label = (_binding_value(binding, "orgLabel") or "").strip()
                website = (_binding_value(binding, "website") or "").strip() or None
                qid = _qid_from_uri(org_uri)
                if not org_label or not qid:
                    continue

                norm = normalise_org(org_label)
                if not norm:
                    continue

                key = (norm, code)
                existing = rows_by_key.get(key)
                if existing:
                    if concept_label not in existing["concepts"]:
                        existing["concepts"].append(concept_label)
                    # Keep a website if we have one; prefer the first seen.
                    if website and not existing.get("website"):
                        existing["website"] = website
                    continue

                rows_by_key[key] = {
                    "organization": org_label,
                    "country_code": code,
                    "segment": segment,
                    "website": website,
                    "wikidata_id": qid,
                    "concepts": [concept_label],
                    "source_url": _source_url_from_qid(qid),
                }

            if sleep_s:
                time.sleep(sleep_s)

            if progress:
                progress(concept_label, code, len(bindings))

    rows = list(rows_by_key.values())
    counts["unique_orgs"] = len(rows)
    counts["with_website"] = sum(1 for r in rows if r.get("website"))
    counts["without_website"] = counts["unique_orgs"] - counts["with_website"]

    return {
        "rows": rows,
        "counts": counts,
        "skipped": skipped,
        "capped_queries": capped_queries,
    }


def to_lead(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an inventory row into a marketing lead JSON."""
    segment = row.get("segment", "investment")
    organization = row["organization"]
    website = row.get("website") or ""
    wikidata_id = row.get("wikidata_id", "")
    country_code = row.get("country_code", "")
    concepts = row.get("concepts", [])
    source_url = row.get("source_url", _source_url_from_qid(wikidata_id))

    role = _SEGMENT_ROLE.get(segment, "Risk Manager")
    product = _SEGMENT_PRODUCT.get(segment, "api")
    capability = _SEGMENT_CAPABILITY.get(segment, "climate-risk intelligence")
    problem = _SEGMENT_PROBLEM.get(segment, "climate exposure needs documented evidence")
    pain = _SEGMENT_PAIN.get(segment, "Needs traceable climate-risk evidence.")
    evidence = _SEGMENT_EVIDENCE.get(segment, "multi-hazard screening with source-attached results")
    fit = _SEGMENT_FIT.get(segment, "Organization with physical assets or responsibilities to screen.")

    return {
        "organization": organization,
        "segment": segment,
        "country": country_code,
        "region": "",
        "website": website,
        "contact_type": "role_based_public",
        "decision_maker_role": role,
        "identified_problem": problem,
        "climate_exposure": "Physical assets and operations exposed to climate hazards.",
        "potential_pain": pain,
        "relevant_hazards": ["flood", "wildfire", "heat", "wind", "coastal", "drought"],
        "commercial_signals": [],
        "event_signals": [],
        "evidence": evidence,
        "relevant_capability": capability,
        "priority": "medium",
        "recommended_product": product,
        "recommended_message": (
            f"Offer {organization} a focused pilot that pairs {evidence} "
            "with traceable physical-risk evidence."
        ),
        "fit_score": fit,
        "urgency": "medium",
        "outreach_status": "researched",
        "status": "open",
        "interactions": [
            {
                "date": TODAY,
                "type": "discovered",
                "summary": (
                    "Discovered via Wikidata organization inventory "
                    f"({', '.join(concepts)})."
                ),
                "source": source_url,
            }
        ],
        "next_action": "Qualify: verify current public signal and select contact route",
        "owner": "operator",
        "source": source_url,
        "date_checked": TODAY,
        "wikidata_id": wikidata_id,
        "concepts": concepts,
        "inventory_meta": {
            "concept_label": concepts[0] if concepts else "",
            "wikidata_id": wikidata_id,
            "source_url": source_url,
        },
    }
