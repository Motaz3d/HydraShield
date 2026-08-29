"""Self-hosted, evidence-based email discovery engine for the marketing CRM.

The engine crawls a small, polite set of public pages on the target domain,
extracts email addresses from ``mailto:`` links and visible text, records the
exact source URL for every contact, and never presents an inferred guess as an
observed fact.

Design constraints:
- No SMTP probing (reputation risk).
- No MX lookup this phase (dnspython is not a dependency).
- ``requests`` is the only HTTP dependency; all network calls go through
  ``_fetch`` so tests can monkeypatch a single function.
- ``urllib.robotparser`` is used to respect robots.txt when it can be fetched.
"""

from __future__ import annotations

import re
from io import StringIO
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .hunter import domain_from_url

JUNK_LOCALPARTS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "webmaster", "hostmaster",
    "abuse", "bounce", "sentry", "example", "test", "admin",
})

_ROLE_LOCALPARTS = {
    "info", "contact", "hello", "office", "mail", "enquiries",
    "enquiry", "general", "support", "sales", "press", "media",
    "communication", "communications", "sustainability", "esg", "csr",
    "climate", "environment", "investor", "ir", "careers", "hr",
}

# Pages are tried in this order.  The first N unique paths are fetched.
_CANDIDATE_PATHS = [
    "/", "/contact", "/contact-us", "/about", "/about-us",
    "/team", "/people", "/leadership", "/impressum", "/legal",
    "/sustainability", "/esg", "/csr", "/press", "/news",
    "/media", "/investor-relations", "/ir",
]

_PAGE_WEIGHTS = {
    "/": 0.7,
    "/contact": 0.9,
    "/contact-us": 0.9,
    "/about": 0.9,
    "/about-us": 0.9,
    "/team": 0.9,
    "/people": 0.9,
    "/leadership": 0.9,
    "/impressum": 0.9,
    "/legal": 0.8,
    "/sustainability": 0.8,
    "/esg": 0.8,
    "/csr": 0.8,
    "/press": 0.8,
    "/news": 0.5,
    "/media": 0.8,
    "/investor-relations": 0.8,
    "/ir": 0.8,
}

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Obfuscation patterns such as "name [at] domain [dot] com".
_OBFUSCATED_RE = re.compile(
    r"([a-zA-Z0-9._%+-]+)\s*\[?\s*(?:@|at)\s*\]?\s*([a-zA-Z0-9.-]+)\s*\[?\s*(?:dot|\.)\s*\]?\s*([a-zA-Z]{2,})",
    re.IGNORECASE,
)

# Artifact strings that slip into regex matches (image names, CSS leftovers).
_ARTIFACT_RE = re.compile(r"\.(png|jpg|jpeg|gif|svg|css|js|webp|ico)$", re.IGNORECASE)

# Free-mail domains that should be dropped when the target is a corporate domain.
_FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk",
    "yahoo.co.in", "hotmail.com", "outlook.com", "live.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "qq.com",
    "163.com", "126.com", "protonmail.com",
})

# Hosting/CDN domains that are never the target organisation.
_HOSTING_CDN_DOMAINS = frozenset({
    "wixpress.com", "wix.com", "siteground.biz", "siteground.com",
    "squarespace.com", "weebly.com", "wordpress.com", "wp.com",
    "cdn.com", "cloudfront.net", "amazonaws.com", "github.io",
})


# Hard per-page cap: no single page may stall discovery — neither by
# download size nor by pathological markup (linear processing below).
_MAX_HTML_CHARS = 2_000_000


def _fetch(url: str, timeout: int = 10) -> Tuple[int, str]:
    """Fetch ``url`` and return (status_code, text).

    This is the single network boundary of the module. Tests monkeypatch it.
    Non-2xx statuses still return their body when available; transport errors
    return (0, ""). Bodies are capped at ``_MAX_HTML_CHARS`` so a pathological
    page can never stall the pipeline downstream.
    """
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "TalaixEmailDiscovery/1.0 (operator research; respects robots.txt)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }, stream=True)
        chunks = []
        size = 0
        for chunk in resp.iter_content(chunk_size=65536, decode_unicode=True):
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size >= _MAX_HTML_CHARS:
                break
        resp.close()
        return resp.status_code, "".join(chunks)[:_MAX_HTML_CHARS]
    except Exception:
        return 0, ""


def _normalize_domain(url_or_domain: str) -> Optional[str]:
    """Return a clean, lower-case domain, or None if unusable."""
    return domain_from_url(url_or_domain)


def _is_junk(email: str, target_domain: str) -> bool:
    """Return True for addresses that should never be stored."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return True
    local, _, domain = email.partition("@")

    # Drop obvious role/junk localparts.
    if local in JUNK_LOCALPARTS:
        return True

    # Drop encoded HTML artifacts and image filenames.
    if "u003e" in email or "u003c" in email or _ARTIFACT_RE.search(email):
        return True

    # Off-domain addresses are only kept when they are on a direct subdomain
    # of the target. Free-mail and hosting/CDN domains are always dropped.
    if domain in _FREE_MAIL_DOMAINS or domain in _HOSTING_CDN_DOMAINS:
        return True

    root = target_domain.lower()
    if domain == root or domain.endswith("." + root):
        return False

    # Off-domain and unrelated subdomains are dropped.
    return True


def _classify_localpart(localpart: str) -> str:
    """Classify an email as role, personal or unknown."""
    lp = localpart.lower().strip()
    if lp in _ROLE_LOCALPARTS:
        return "role"
    # Common personal patterns: first.last, f.last, first_last, first-last,
    # firstl, flast (at least two alphabetic parts separated by punctuation).
    if re.match(r"^[a-z]+[._-][a-z]+$", lp):
        return "personal"
    if re.match(r"^[a-z][._-]?[a-z]+$", lp):
        return "personal"
    return "unknown"


def _strip_block(html: str, tag: str) -> str:
    """Remove <tag>…</tag> blocks with a linear scan — no regex, so no
    catastrophic backtracking on pathological pages."""
    out = []
    low = html.lower()
    open_tag = "<" + tag
    close_tag = "</" + tag + ">"
    i = 0
    while True:
        start = low.find(open_tag, i)
        if start == -1:
            out.append(html[i:])
            return " ".join(out)
        gt = low.find(">", start)
        if gt == -1:
            out.append(html[i:])
            return " ".join(out)
        end = low.find(close_tag, gt)
        out.append(html[i:start])
        if end == -1:
            return " ".join(out)
        i = end + len(close_tag)


def _strip_tags(html: str) -> str:
    """Remove <script> and <style> blocks, then crude tag stripping."""
    if len(html) > _MAX_HTML_CHARS:
        html = html[:_MAX_HTML_CHARS]
    text = _strip_block(html, "script")
    text = _strip_block(text, "style")
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def _extract_mailto(html: str, base_url: str, target_domain: str) -> List[Dict]:
    """Extract emails from mailto: hrefs."""
    found: List[Dict] = []
    for match in re.finditer(r'href=["\']mailto:([^"\'?]+)', html, re.IGNORECASE):
        raw = unquote(match.group(1)).strip().lower()
        if not raw or "@" not in raw:
            continue
        email = raw.split("?")[0].strip()
        if _is_junk(email, target_domain):
            continue
        found.append({
            "email": email,
            "type": _classify_localpart(email.split("@")[0]),
            "source_url": base_url,
            "found_on": urlparse(base_url).path or "/",
            "claim_status": "OBSERVED",
        })
    return found


def _text_windows(text: str, size: int = 1200, overlap: int = 400):
    """Yield bounded overlapping windows of ``text``.

    Any plausible email/obfuscated form is far shorter than ``overlap``, so
    no match is lost at a boundary — and no regex ever sees more than
    ``size`` chars, which makes quadratic blow-ups on pathological blobs
    (e.g. a 2 MB run of word-chars and dots) structurally impossible.
    """
    step = size - overlap
    for i in range(0, max(len(text), 1), step):
        yield text[i:i + size]


def _extract_text_emails(html: str, base_url: str, target_domain: str) -> List[Dict]:
    """Extract emails from visible text, including obfuscated forms."""
    text = _strip_tags(html)
    found: List[Dict] = []
    seen = set()

    def _keep(email: str) -> bool:
        email = email.lower().strip()
        if not email or email in seen or _is_junk(email, target_domain):
            return False
        seen.add(email)
        found.append({
            "email": email,
            "type": _classify_localpart(email.split("@")[0]),
            "source_url": base_url,
            "found_on": urlparse(base_url).path or "/",
            "claim_status": "OBSERVED",
        })
        return True

    for window in _text_windows(text):
        # Cheap gate before any regex: a window that contains neither "@"
        # nor an "at" marker cannot hold a (standard or obfuscated) email.
        # On pathological blobs this keeps the whole scan linear.
        low = window.lower()
        if "@" in window or "[at]" in low or "(at)" in low or " at " in low:
            # Standard emails.
            for match in _EMAIL_RE.finditer(window):
                _keep(match.group(0))

            # Obfuscated "[at]" / "[dot]" forms.
            for match in _OBFUSCATED_RE.finditer(window):
                local, dom, tld = match.groups()
                _keep(f"{local.strip()}@{dom.strip()}.{tld.strip()}")

    return found


def _page_weight(path: str) -> float:
    return _PAGE_WEIGHTS.get(path, 0.5)


def _build_robots(domain: str, timeout: int) -> Tuple[Optional[RobotFileParser], bool]:
    """Return (robotparser, fetched_ok). fetched_ok=False means proceed politely."""
    url = f"https://{domain}/robots.txt"
    try:
        status, text = _fetch(url, timeout=timeout)
    except Exception:
        return None, False
    if status != 200 or not text:
        return None, False
    rp = RobotFileParser()
    rp.set_url(url)
    try:
        rp.parse(text.splitlines())
        return rp, True
    except Exception:
        return None, False


def _is_allowed(rp: Optional[RobotFileParser], path: str) -> bool:
    if rp is None:
        return True
    try:
        return rp.can_fetch("*", path)
    except Exception:
        return True


def discover_emails(
    domain: str,
    *,
    max_pages: int = 12,
    timeout: int = 10,
) -> Dict:
    """Discover emails on ``domain`` by crawling a polite page list.

    Returns a dict with ``domain``, ``contacts`` (each with ``email``,
    ``type``, ``source_url``, ``found_on``, ``claim_status``, ``confidence``),
    ``pages_fetched``, ``robots_respected`` and ``note``.
    """
    target = _normalize_domain(domain)
    if target is None:
        return {
            "domain": domain,
            "contacts": [],
            "pages_fetched": 0,
            "robots_respected": False,
            "mx_checked": False,
            "note": "No usable domain; nothing was fetched.",
        }

    rp, robots_ok = _build_robots(target, timeout)

    paths = []
    for p in _CANDIDATE_PATHS:
        if p not in paths:
            paths.append(p)
        if len(paths) >= max_pages:
            break

    raw_contacts: List[Dict] = []
    pages_fetched = 0

    for path in paths:
        if not _is_allowed(rp, path):
            continue
        url = f"https://{target}{path}"
        try:
            status, html = _fetch(url, timeout=timeout)
        except Exception:
            continue
        if status != 200 or not html:
            continue
        pages_fetched += 1
        raw_contacts.extend(_extract_mailto(html, url, target))
        raw_contacts.extend(_extract_text_emails(html, url, target))

    # Deduplicate case-insensitively, keeping the first (highest-weight) source.
    seen: Dict[str, Dict] = {}
    for c in raw_contacts:
        key = c["email"].lower()
        if key not in seen:
            seen[key] = c

    contacts: List[Dict] = []
    for c in seen.values():
        weight = _page_weight(c["found_on"])
        if c["type"] == "role" and c["found_on"] in (
            "/contact", "/contact-us", "/about", "/about-us",
            "/sustainability", "/esg", "/csr", "/press", "/media",
            "/investor-relations", "/ir",
        ):
            weight = min(0.99, weight + 0.05)
        confidence = round(min(0.99, weight), 2)
        contacts.append({
            "email": c["email"],
            "type": c["type"],
            "source_url": c["source_url"],
            "found_on": c["found_on"],
            "claim_status": c["claim_status"],
            "confidence": confidence,
        })

    contacts.sort(key=lambda x: (-x["confidence"], x["email"]))

    note = (
        "Every contact was extracted from a public page on this domain; "
        "nothing is inferred at this stage."
    )
    if not robots_ok:
        note += " robots.txt could not be fetched or parsed; proceeded politely."

    return {
        "domain": target,
        "contacts": contacts,
        "pages_fetched": pages_fetched,
        "robots_respected": robots_ok,
        "mx_checked": False,
        "note": note,
    }


def infer_patterns(emails: List[str]) -> Optional[Dict]:
    """Infer the dominant personal-email pattern for a domain.

    Requires at least two personal emails that share the same pattern.
    Returns {"pattern": name, "examples": [...], "count": n} or None with a
    reason when no reliable pattern exists.
    """
    def _pattern(email: str) -> Optional[str]:
        if "@" not in email:
            return None
        local = email.split("@")[0].lower()
        if local in _ROLE_LOCALPARTS or local in JUNK_LOCALPARTS:
            return None

        # Evidence counts ONLY from separator-based shapes (first.last,
        # f.last, first.l, f.l). Single-word localparts are indistinguishable
        # from dictionary words, so concatenated shapes (firstl/flast) are
        # never used as evidence — we only infer what we can justify.
        parts = re.split(r"[._-]", local)
        if len(parts) == 2 and all(p.isalpha() for p in parts):
            a, b = parts
            # Dotted role addresses (investor.relations, press.office, …)
            # are not personal patterns either.
            if a in _ROLE_LOCALPARTS or b in _ROLE_LOCALPARTS:
                return None
            if len(a) >= 2 and len(b) >= 2:
                return "first.last"
            if len(a) == 1 and len(b) >= 2:
                return "f.last"
            if len(a) >= 2 and len(b) == 1:
                return "first.l"
            if len(a) == 1 and len(b) == 1:
                return "f.l"
        return None

    counts: Dict[str, int] = {}
    examples: Dict[str, List[str]] = {}
    for email in emails:
        pat = _pattern(email)
        if pat:
            counts[pat] = counts.get(pat, 0) + 1
            examples.setdefault(pat, []).append(email)

    if not counts:
        return None

    best = max(counts.items(), key=lambda kv: kv[1])
    if best[1] < 2:
        return None
    return {
        "pattern": best[0],
        "examples": examples[best[0]],
        "count": best[1],
    }


def _generate_candidate(first_name: str, last_name: str, pattern: str) -> Optional[str]:
    first = first_name.lower().strip()
    last = last_name.lower().strip()
    if pattern == "first.last":
        return f"{first}.{last}"
    if pattern == "f.last":
        return f"{first[0]}.{last}"
    if pattern == "first.l":
        return f"{first}.{last[0]}"
    if pattern == "f.l":
        return f"{first[0]}.{last[0]}"
    return None  # never generate from a pattern we do not implement


def find_for_person(
    domain: str,
    first_name: str,
    last_name: str,
    known_emails: Optional[List[str]] = None,
) -> Dict:
    """Infer an email address for a person from observed domain patterns.

    If ``known_emails`` is not provided the function runs a small discovery
    pass (max 6 pages) to collect observed emails. The returned dict always
    carries a ``claim_status`` of INFERRED or UNKNOWN; an inferred email is
    never returned as OBSERVED.
    """
    target = _normalize_domain(domain)
    if target is None:
        return {
            "email": None,
            "claim_status": "UNKNOWN",
            "reason": "no usable domain",
        }

    emails = known_emails or []
    if not emails:
        result = discover_emails(target, max_pages=6, timeout=10)
        emails = [c["email"] for c in result.get("contacts", [])]

    pattern_info = infer_patterns(emails)
    if pattern_info is None:
        return {
            "email": None,
            "claim_status": "UNKNOWN",
            "reason": "no reliable pattern at this domain",
        }

    local = _generate_candidate(first_name, last_name, pattern_info["pattern"])
    if local is None:
        return {
            "email": None,
            "claim_status": "UNKNOWN",
            "reason": f"pattern '{pattern_info['pattern']}' has no implemented generator",
        }
    email = f"{local}@{target}"
    return {
        "email": email,
        "claim_status": "INFERRED",
        "pattern": pattern_info["pattern"],
        "basis": (
            f"pattern from {pattern_info['count']} observed emails "
            f"at the domain"
        ),
        "confidence": 0.6,
    }
