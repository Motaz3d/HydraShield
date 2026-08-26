"""
Permanent signatory-list acquisition system for the Talaix marketing CRM.

Dependency-free core (no Flask imports). It tracks official climate-finance
signatory lists, imports them into marketing/leads/*.json, and maintains a
source registry with honest pending states for lists that are not yet
machine-readable.

Honesty contract: we import only what an official list publishes. A source
that is JS/AJAX-rendered or that publishes no public member list is recorded
as pending with a stated reason — never scraped by guessing endpoints.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

PCAF_URL = "https://carbonaccountingfinancials.com/en/signatories"
PCAF_HOST = "carbonaccountingfinancials.com"
PCAF_SOURCE = "pcaf"
PCAF_SOURCE_URL = PCAF_URL

TODAY = date.today().isoformat()

_MIN_PCAF_ROWS = 200

_WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php?action=wbsearchentities&search={query}&language=en&format=json&limit=3"
_WIKIDATA_CLAIMS_URL = "https://www.wikidata.org/w/api.php?action=wbgetclaims&entity={qid}&property=P856&format=json"
_WIKIDATA_CACHE: Dict[str, Optional[Dict[str, str]]] = {}


def _abs_url(href: Optional[str], base: str = PCAF_URL) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        from urllib.parse import urljoin

        return urljoin(base, href)
    if href.startswith("#"):
        return None
    return urljoin(base, href)


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    # Strip trailing footnote markers like *, †, ‡.
    text = re.sub(r"\s*[\*†‡]+\s*$", "", text)
    return text.strip()


class SignatorySourceError(Exception):
    """Raised when a live signatory source cannot be parsed or is structurally unexpected."""


# ---------------------------------------------------------------------------
# Parsing — PCAF
# ---------------------------------------------------------------------------

_KNOWN_CELL_CLASSES = {
    "inst_name",
    "hq",
    "region",
    "category",
    "assets",
    "status",
    "inst_date",
    "download",
}


class _PCAFParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.current_class: Optional[str] = None
        self.buffer: List[str] = []
        self.row: Dict[str, Any] = {}
        self.date_index = 0  # which inst_date cell we are in within the current row
        self.rows: List[Dict[str, Any]] = []
        self._date_field_order = ["date_joined", "first_disclosure", "most_recent_disclosure"]

    def _attrs(self, attrs: List[tuple]) -> Dict[str, str]:
        return {k: v for k, v in attrs}

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attr = self._attrs(attrs)
        cls = attr.get("class", "")
        if tag == "table" and attr.get("id") == "instTable":
            self.in_table = True
            return
        if not self.in_table:
            return
        if tag == "tr":
            self.in_tr = True
            self.row = {}
            self.row_has_td = False
            self.date_index = 0
            return
        if tag in ("td", "th") and self.in_tr:
            self.in_td = True
            if tag == "td":
                self.row_has_td = True
            self.buffer = []
            classes = set(cls.split())
            known = classes & _KNOWN_CELL_CLASSES
            self.current_class = next(iter(known)) if known else None
            if self.current_class == "download":
                href = attr.get("href")
                if href:
                    self.row["disclosure_url"] = _abs_url(href)
                else:
                    # The link may wrap the cell content; remember we want its href.
                    self.current_class = "download"
            return
        if tag == "a" and self.in_td:
            if self.current_class == "download":
                href = attr.get("href")
                if href:
                    self.row["disclosure_url"] = _abs_url(href)
            # For inst_name we keep the link text, not the href.

    def handle_data(self, data: str) -> None:
        if self.in_td and self.current_class:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_table:
            return
        if tag in ("td", "th") and self.in_td:
            self.in_td = False
            if self.current_class:
                text = _clean_text("".join(self.buffer))
                if self.current_class == "inst_date":
                    field = self._date_field_order[self.date_index] if self.date_index < 3 else None
                    if field:
                        self.row[field] = text
                    self.date_index += 1
                elif self.current_class == "download":
                    # text here is usually "Download"; the URL was captured from the <a>.
                    pass
                else:
                    self.row[self.current_class] = text
            self.current_class = None
            self.buffer = []
            return
        if tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.row and "inst_name" in self.row and self.row_has_td:
                self.rows.append(self.row)
            return
        if tag == "table":
            self.in_table = False


def parse_pcaf_table(html: str) -> List[Dict[str, Any]]:
    """
    Parse the PCAF signatory table from a server-rendered HTML page.

    Returns a list of row dicts with keys:
        organization, country, region, category, assets_usd_m, status,
        date_joined, first_disclosure, most_recent_disclosure, disclosure_url,
        source, source_url.
    """
    parser = _PCAFParser()
    parser.feed(html)
    out: List[Dict[str, Any]] = []
    for row in parser.rows:
        org = row.get("inst_name", "")
        if not org or org.strip().lower() == "financial institution":
            # Skip the table's own header row (PCAF uses <td> in <thead>).
            continue
        assets_text = row.get("assets", "")
        assets_val: Optional[int] = None
        if assets_text:
            # "644,938" → 644938 (million USD)
            digits = re.sub(r"[^0-9]", "", assets_text)
            if digits:
                try:
                    assets_val = int(digits)
                except ValueError:
                    assets_val = None
        out.append(
            {
                "organization": org,
                "country": row.get("hq", ""),
                "region": row.get("region", ""),
                "category": row.get("category", ""),
                "assets_usd_m": assets_val,
                "status": row.get("status", ""),
                "date_joined": row.get("date_joined", ""),
                "first_disclosure": row.get("first_disclosure", ""),
                "most_recent_disclosure": row.get("most_recent_disclosure", ""),
                "disclosure_url": row.get("disclosure_url"),
                "source": PCAF_SOURCE,
                "source_url": PCAF_SOURCE_URL,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _requests_get(url: str, timeout: float = 30.0) -> str:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise SignatorySourceError(f"requests is not installed: {exc}")
    headers = {
        "User-Agent": "TalaixLeadResearch/1.0 (+https://talaix.com)",
        "Accept": "text/html",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def fetch_pcaf_signatories(fetch: Optional[Callable[[str], str]] = None) -> List[Dict[str, Any]]:
    """
    Download and parse the PCAF signatory list.

    ``fetch`` is injectable for tests. Raises ``SignatorySourceError`` when the
    source is unavailable or its structure has changed (fewer than 200 rows).
    """
    fetcher = fetch or _requests_get
    try:
        html = fetcher(PCAF_URL)
    except Exception as exc:
        raise SignatorySourceError(f"PCAF fetch failed: {exc}") from exc
    rows = parse_pcaf_table(html)
    if len(rows) < _MIN_PCAF_ROWS:
        raise SignatorySourceError(
            f"PCAF structure changed or page unavailable — parsed {len(rows)} rows; refusing to import"
        )
    return rows


# ---------------------------------------------------------------------------
# Normalisation and classification
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = {
    "sa",
    "s.a.",
    "nv",
    "n.v.",
    "ltd",
    "limited",
    "llc",
    "plc",
    "ag",
    "ab",
    "as",
    "oy",
    "oyj",
    "spa",
    "s.p.a.",
    "gmbh",
    "inc",
    "corp",
    "corporation",
    "group",
    "holdings",
    "holding",
    "bancorp",
    "bank",
    "co",
    "co.",
    "srl",
    "s.r.l.",
    "bv",
    "b.v.",
}


def normalise_org(name: str) -> str:
    """
    Normalise an organisation name for matching only.

    Lowercases, strips punctuation, drops common legal suffixes (unless the
    whole name is the suffix), and collapses whitespace.
    """
    text = name.lower()
    # Remove punctuation except spaces and dots (dots needed to keep s.a. etc).
    text = re.sub(r"[^a-z0-9\s.]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split()
    # Drop trailing suffix tokens, but never reduce the name to nothing.
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    # A single remaining suffix token (e.g. "s.a.") is noise, unless the
    # entire name is the word "bank".
    if len(tokens) == 1 and tokens[0] in _LEGAL_SUFFIXES and tokens[0] != "bank":
        tokens.pop()
    if not tokens:
        return ""
    return " ".join(tokens)


def category_to_segment(category: str) -> str:
    """Map a PCAF category string to a Talaix marketing segment."""
    cat = (category or "").lower().strip()
    if cat == "commercial bank":
        return "banking"
    if cat == "insurance":
        return "insurance"
    if "asset owner" in cat or "asset manager" in cat or "asset owner/managers" in cat:
        return "investment"
    if cat == "export credit agency":
        return "banking"
    return "investment"


def _is_pcaf_host(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    host = hostname.lower().lstrip("www.")
    return host == PCAF_HOST or host.endswith(f".{PCAF_HOST}")


def _website_from_disclosure_url(url: Optional[str]) -> Optional[str]:
    """Return the organisation's own website only when the disclosure PDF is self-hosted."""
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    if _is_pcaf_host(parsed.hostname):
        return None
    return f"https://{parsed.hostname.lower()}"


# ---------------------------------------------------------------------------
# Wikidata official-website resolution
# ---------------------------------------------------------------------------


def _wikidata_requests_get(url: str, timeout: float = 15.0) -> Any:
    import requests

    headers = {
        "User-Agent": "TalaixLeadResearch/1.0 (+https://talaix.com)",
        "Accept": "application/json",
    }
    return requests.get(url, headers=headers, timeout=timeout)


def _best_wikidata_entity(search_results: List[Dict[str, Any]], org_name: str) -> Optional[Dict[str, Any]]:
    """Pick the best Wikidata entity or reject it when the label is clearly different."""
    norm = normalise_org(org_name)
    if not norm:
        return None
    norm_tokens = set(norm.split())
    best: Optional[Dict[str, Any]] = None
    best_score = 0

    for entity in search_results:
        label = entity.get("label", "")
        label_norm = normalise_org(label)
        if not label_norm:
            continue
        label_tokens = set(label_norm.split())

        if label_norm == norm:
            score = 100
        elif norm in label_norm or label_norm in norm:
            score = 75
        else:
            overlap = norm_tokens & label_tokens
            if not overlap:
                continue
            score = int(50 * len(overlap) / max(len(norm_tokens), len(label_tokens)))

        if score > best_score:
            best_score = score
            best = entity

    # Require a strong match (exact or containment) to avoid inventing websites.
    if best_score < 75:
        return None
    return best


def resolve_official_website(
    org_name: str,
    fetch: Optional[Callable[[str, float], Any]] = None,
) -> Optional[Dict[str, str]]:
    """
    Resolve an organisation's official website via Wikidata (P856).

    Returns ``{"website": url, "wikidata_id": "Q...", "source": "wikidata"}``
    or ``None`` when no unambiguous official website is found. ``fetch`` is
    injectable for tests and must behave like ``requests.get``.
    """
    norm = normalise_org(org_name)
    if not norm:
        return None
    if norm in _WIKIDATA_CACHE:
        return _WIKIDATA_CACHE[norm]

    fetcher = fetch or _wikidata_requests_get
    try:
        search_url = _WIKIDATA_SEARCH_URL.format(query=quote_plus(org_name))
        resp = fetcher(search_url, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        entity = _best_wikidata_entity(data.get("search", []), org_name)
        if not entity:
            _WIKIDATA_CACHE[norm] = None
            return None

        qid = entity["id"]
        claims_url = _WIKIDATA_CLAIMS_URL.format(qid=qid)
        resp2 = fetcher(claims_url, timeout=15.0)
        resp2.raise_for_status()
        claims_data = resp2.json()
        claims = claims_data.get("claims", {}).get("P856", [])
        if not claims:
            _WIKIDATA_CACHE[norm] = None
            return None

        site = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
        if not site or not site.startswith(("http://", "https://")):
            _WIKIDATA_CACHE[norm] = None
            return None

        result = {"website": site, "wikidata_id": qid, "source": "wikidata"}
        _WIKIDATA_CACHE[norm] = result
        return result
    except Exception:
        return None


def resolve_websites(
    rows: List[Dict[str, Any]],
    fetch: Optional[Callable[[str, float], Any]] = None,
    sleep_s: float = 0.3,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Resolve an honest website for each parsed signatory row.

    - If the disclosure PDF is self-hosted (not on PCAF's domain), that domain
      is used as the website (source ``self-disclosure``).
    - Otherwise the organisation name is looked up on Wikidata and the P856
      official-website claim is used (source ``wikidata``).
    - Rows with no verifiable website become ``pending`` with a clear reason.

    Returns ``(resolved_rows, pending_rows)``. ``resolved_rows`` are augmented
    with ``website``, ``website_source`` and ``wikidata_id``.
    """
    resolved: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []

    for row in rows:
        org = row.get("organization", "").strip()
        disclosure_url = row.get("disclosure_url")
        website = _website_from_disclosure_url(disclosure_url)
        website_source = "self-disclosure"
        wikidata_id: Optional[str] = None

        if not website:
            norm = normalise_org(org)
            cache_miss = norm not in _WIKIDATA_CACHE
            wd = resolve_official_website(org, fetch=fetch)
            if wd:
                website = wd["website"]
                website_source = "wikidata"
                wikidata_id = wd["wikidata_id"]
            if cache_miss and sleep_s:
                time.sleep(sleep_s)

        if website:
            new_row = dict(row)
            new_row["website"] = website
            new_row["website_source"] = website_source
            new_row["wikidata_id"] = wikidata_id
            resolved.append(new_row)
        else:
            pending.append(
                {
                    "organization": org,
                    "country": row.get("country", ""),
                    "category": row.get("category", ""),
                    "status": row.get("status", ""),
                    "signatory_meta": {
                        "disclosure_url": _abs_url(disclosure_url),
                        "category": row.get("category", ""),
                        "status": row.get("status", ""),
                        "source_url": row.get("source_url", ""),
                    },
                    "pending_reason": "no official website found (PCAF publishes no org sites; Wikidata has no entry)",
                }
            )

    return resolved, pending


# ---------------------------------------------------------------------------
# Lead building and merging
# ---------------------------------------------------------------------------

_SEGMENT_ROLE = {
    "banking": "Chief Risk Officer",
    "insurance": "Chief Risk Officer",
    "investment": "Investment Director",
}

_SEGMENT_PRODUCT = {
    "banking": "portfolio_screening",
    "insurance": "portfolio_screening",
    "investment": "api",
}

_SEGMENT_CAPABILITY = {
    "banking": "portfolio-location climate-risk screening with traceable evidence",
    "insurance": "portfolio-location climate-risk screening with traceable evidence",
    "investment": "multi-location exposure screening and monitoring",
}


def build_lead(org_row: Dict[str, Any], source_id: str) -> Dict[str, Any]:
    """Create a new lead JSON from a signatory row."""
    segment = category_to_segment(org_row.get("category", ""))
    website = org_row.get("website") or _website_from_disclosure_url(org_row.get("disclosure_url"))
    website_source = org_row.get("website_source") or ("self-disclosure" if website else "")
    wikidata_id = org_row.get("wikidata_id") or ""
    role = _SEGMENT_ROLE.get(segment, "Risk Manager")
    product = _SEGMENT_PRODUCT.get(segment, "api")
    capability = _SEGMENT_CAPABILITY.get(segment, "climate-risk intelligence")
    priority = "high" if (org_row.get("status") or "").strip().lower() == "disclosed" else "medium"
    return {
        "organization": org_row["organization"],
        "segment": segment,
        "country": org_row.get("country", ""),
        "region": org_row.get("region", ""),
        "website": website or "",
        "website_source": website_source,
        "wikidata_id": wikidata_id,
        "contact_type": "role_based_public",
        "decision_maker_role": role,
        "identified_problem": (
            "PCAF signatory committed to measuring and disclosing financed emissions; "
            "physical-risk evidence complements emissions accounting."
        ),
        "climate_exposure": "Financed-asset portfolio exposed to climate hazards.",
        "potential_pain": (
            "Needs documented physical-risk evidence to accompany financed-emissions disclosure."
        ),
        "relevant_hazards": ["flood", "wildfire", "heat", "wind", "coastal", "drought"],
        "commercial_signals": [],
        "event_signals": [],
        "evidence": "portfolio-location multi-hazard screening with source-attached results",
        "relevant_capability": capability,
        "priority": priority,
        "recommended_product": product,
        "recommended_message": (
            f"Offer {org_row['organization']} a portfolio-location pilot that pairs "
            f"PCAF-style disclosure with traceable physical-risk evidence."
        ),
        "fit_score": "PCAF signatory with a public commitment to financed-emissions transparency.",
        "urgency": "medium",
        "outreach_status": "researched",
        "status": "open",
        "interactions": [
            {
                "date": TODAY,
                "type": "discovered",
                "summary": (
                    f"Discovered via signatory-list import ({source_id}): "
                    f"{org_row.get('status', 'signatory')} status."
                ),
                "source": org_row.get("source_url", ""),
            }
        ],
        "next_action": "Qualify: verify current public signal and select contact route",
        "owner": "operator",
        "source": org_row.get("source_url", ""),
        "date_checked": TODAY,
        "signatory_of": [source_id],
        "signatory_meta": {
            source_id: {
                "status": org_row.get("status", ""),
                "assets_usd_m": org_row.get("assets_usd_m"),
                "date_joined": org_row.get("date_joined", ""),
                "first_disclosure": org_row.get("first_disclosure", ""),
                "most_recent_disclosure": org_row.get("most_recent_disclosure", ""),
                "disclosure_url": org_row.get("disclosure_url"),
                "category": org_row.get("category", ""),
                "source_url": org_row.get("source_url", ""),
            }
        },
    }


def merge_signatory(lead_json: Dict[str, Any], source_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge a signatory source into an existing lead.

    - Appends ``source_id`` to ``signatory_of`` (unique, sorted).
    - Stores/updates ``signatory_meta[source_id]``.
    - Upgrades ``priority`` to high if any signatory status is "Disclosed" or
      the organisation appears on two or more signatory lists.
    """
    memberships = set(lead_json.get("signatory_of", []))
    memberships.add(source_id)
    lead_json["signatory_of"] = sorted(memberships)

    meta = lead_json.setdefault("signatory_meta", {})
    meta[source_id] = {
        "status": fields.get("status", ""),
        "assets_usd_m": fields.get("assets_usd_m"),
        "date_joined": fields.get("date_joined", ""),
        "first_disclosure": fields.get("first_disclosure", ""),
        "most_recent_disclosure": fields.get("most_recent_disclosure", ""),
        "disclosure_url": fields.get("disclosure_url"),
        "category": fields.get("category", ""),
        "source_url": fields.get("source_url", ""),
    }

    disclosed = any(
        (m.get("status") or "").strip().lower() == "disclosed"
        for m in meta.values()
    )
    if disclosed or len(memberships) >= 2:
        lead_json["priority"] = "high"

    # Append a discovery interaction only if this source is new to the lead.
    interactions = lead_json.setdefault("interactions", [])
    already_logged = any(
        source_id in (ix.get("summary") or "") for ix in interactions
    )
    if not already_logged:
        interactions.append(
            {
                "date": TODAY,
                "type": "discovered",
                "summary": (
                    f"Updated via signatory-list import ({source_id}): "
                    f"{fields.get('status', 'signatory')} status."
                ),
                "source": fields.get("source_url", ""),
            }
        )

    return lead_json


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

SOURCES: List[Dict[str, Any]] = [
    {
        "id": PCAF_SOURCE,
        "name": "Partnership for Carbon Accounting Financials (PCAF)",
        "url": PCAF_URL,
        "live": True,
        "pending_reason": None,
        "adapter": fetch_pcaf_signatories,
    },
    {
        "id": "unepfi",
        "name": "UNEP FI Membership",
        "url": "https://www.unepfi.org/members/",
        "live": False,
        "pending_reason": "AJAX-rendered list; no confirmed public endpoint",
        "adapter": None,
    },
    {
        "id": "icma",
        "name": "International Capital Market Association (ICMA)",
        "url": "https://www.icmagroup.org/About-ICMA/Membership/Members/",
        "live": False,
        "pending_reason": "JS-rendered",
        "adapter": None,
    },
    {
        "id": "gfanz",
        "name": "Glasgow Financial Alliance for Net Zero (GFANZ)",
        "url": "https://www.gfanzero.com/",
        "live": False,
        "pending_reason": "no public member list published",
        "adapter": None,
    },
]
