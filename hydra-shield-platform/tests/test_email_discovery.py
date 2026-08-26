"""Offline tests for the self-hosted email discovery engine.

All network calls are monkeypatched through ``email_discovery._fetch``.
"""

import pytest

from src.dashboard import email_discovery


@pytest.fixture(autouse=True)
def _reset_fetch(monkeypatch):
    """Default fetch returns nothing; tests override as needed."""
    monkeypatch.setattr(email_discovery, "_fetch", lambda url, timeout=10: (0, ""))


def _make_fetch(pages):
    """Build a fake _fetch that serves {url: (status, html)} from pages."""
    def _fetch(url, timeout=10):
        return pages.get(url, (404, ""))
    return _fetch


def test_discover_emails_extracts_mailto_text_and_obfuscated_emails(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (200, "User-agent: *\nDisallow: /private\n"),
        "https://example.com/": (200, """
            <html><body>
            <a href="mailto:Contact@example.com?subject=Hi">email us</a>
            <p>Reach the team at team [at] example [dot] com.</p>
            </body></html>
        """),
        "https://example.com/contact": (200, """
            <html><body>
            <p>General inquiries: info@example.com</p>
            <p>Personal: ada.lovelace@example.com and charles.babbage@example.com</p>
            </body></html>
        """),
        "https://example.com/about": (200, """
            <html><body>
            <p>noreply@example.com should be ignored.</p>
            <p>Off-domain: foo@gmail.com and bar@yahoo.com should be dropped.</p>
            <p>Artifact: icon@2x.png and style@3x.jpg are not emails.</p>
            </body></html>
        """),
    }
    monkeypatch.setattr(email_discovery, "_fetch", _make_fetch(pages))

    result = email_discovery.discover_emails("example.com", max_pages=12)
    assert result["domain"] == "example.com"
    assert result["robots_respected"] is True
    assert result["pages_fetched"] == 3

    emails = {c["email"]: c for c in result["contacts"]}
    assert "contact@example.com" in emails
    assert "team@example.com" in emails
    assert "info@example.com" in emails
    assert "ada.lovelace@example.com" in emails
    assert "charles.babbage@example.com" in emails

    # Junk / off-domain / artifacts filtered out.
    assert "noreply@example.com" not in emails
    assert "foo@gmail.com" not in emails
    assert "bar@yahoo.com" not in emails
    assert "icon@2x.png" not in emails
    assert "style@3x.jpg" not in emails

    # Classification and provenance.
    assert emails["info@example.com"]["type"] == "role"
    assert emails["ada.lovelace@example.com"]["type"] == "personal"
    assert emails["contact@example.com"]["claim_status"] == "OBSERVED"
    assert emails["contact@example.com"]["source_url"].endswith("/")
    assert emails["info@example.com"]["source_url"].endswith("/contact")


def test_discover_emails_respects_robots_txt(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (200, "User-agent: *\nDisallow: /contact\nDisallow: /about\n"),
        "https://example.com/": (200, "<p>hello@example.com</p>"),
        "https://example.com/contact": (200, "<p>info@example.com</p>"),
    }
    monkeypatch.setattr(email_discovery, "_fetch", _make_fetch(pages))

    result = email_discovery.discover_emails("example.com", max_pages=12)
    emails = {c["email"]: c for c in result["contacts"]}
    assert "hello@example.com" in emails
    assert "info@example.com" not in emails
    assert result["robots_respected"] is True


def test_discover_emails_proceeds_when_robots_txt_unavailable(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (500, "error"),
        "https://example.com/": (200, "<p>found@example.com</p>"),
    }
    monkeypatch.setattr(email_discovery, "_fetch", _make_fetch(pages))

    result = email_discovery.discover_emails("example.com", max_pages=12)
    assert result["robots_respected"] is False
    assert any(c["email"] == "found@example.com" for c in result["contacts"])
    assert "proceeded politely" in result["note"]


def test_discover_emails_survives_fetch_errors(monkeypatch):
    def _bad_fetch(url, timeout=10):
        raise RuntimeError("network down")
    monkeypatch.setattr(email_discovery, "_fetch", _bad_fetch)

    result = email_discovery.discover_emails("example.com", max_pages=12)
    assert result["domain"] == "example.com"
    assert result["contacts"] == []
    assert result["pages_fetched"] == 0


def test_infer_patterns_requires_two_matching_personal_emails():
    assert email_discovery.infer_patterns([
        "ada.lovelace@example.com",
        "charles.babbage@example.com",
        "info@example.com",
    ]) == {
        "pattern": "first.last",
        "examples": ["ada.lovelace@example.com", "charles.babbage@example.com"],
        "count": 2,
    }


def test_infer_patterns_returns_none_for_single_email():
    assert email_discovery.infer_patterns(["ada.lovelace@example.com"]) is None


def test_infer_patterns_returns_none_for_only_role_emails():
    assert email_discovery.infer_patterns(["info@example.com", "support@example.com"]) is None


def test_find_for_person_infers_and_returns_unknown_when_no_pattern(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (404, ""),
        "https://example.com/": (200, "<p>ada.lovelace@example.com</p><p>charles.babbage@example.com</p>"),
    }
    monkeypatch.setattr(email_discovery, "_fetch", _make_fetch(pages))

    verdict = email_discovery.find_for_person("example.com", "Grace", "Hopper")
    assert verdict["claim_status"] == "INFERRED"
    assert verdict["email"] == "grace.hopper@example.com"
    assert verdict["pattern"] == "first.last"
    assert "2 observed" in verdict["basis"]
    assert verdict["confidence"] == 0.6


def test_find_for_person_returns_unknown_without_pattern(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (404, ""),
        "https://example.com/": (200, "<p>info@example.com</p>"),
    }
    monkeypatch.setattr(email_discovery, "_fetch", _make_fetch(pages))

    verdict = email_discovery.find_for_person("example.com", "Grace", "Hopper")
    assert verdict["claim_status"] == "UNKNOWN"
    assert verdict["email"] is None
    assert "no reliable pattern" in verdict["reason"]


def test_find_for_person_uses_known_emails_when_provided():
    known = ["alice.smith@example.com", "bob.miller@example.com"]
    verdict = email_discovery.find_for_person(
        "example.com", "Eve", "Programmer", known_emails=known
    )
    assert verdict["claim_status"] == "INFERRED"
    assert verdict["email"] == "eve.programmer@example.com"


def test_find_for_person_returns_unknown_for_bad_domain():
    verdict = email_discovery.find_for_person("not-a-domain", "Grace", "Hopper")
    assert verdict["claim_status"] == "UNKNOWN"
    assert "no usable domain" in verdict["reason"]


def test_discover_emails_drops_subdomain_off_domain_but_keeps_target_subdomain(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (404, ""),
        "https://example.com/": (200, """
            <p>root@example.com</p>
            <p>sub@www.example.com</p>
            <p>other@different.com</p>
        """),
    }
    monkeypatch.setattr(email_discovery, "_fetch", _make_fetch(pages))

    result = email_discovery.discover_emails("example.com")
    emails = {c["email"] for c in result["contacts"]}
    assert "root@example.com" in emails
    assert "sub@www.example.com" in emails
    assert "other@different.com" not in emails


def test_discover_emails_sorts_by_confidence(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (404, ""),
        "https://example.com/": (200, "<p>home@example.com</p>"),
        "https://example.com/contact": (200, "<p>contact@example.com</p>"),
    }
    monkeypatch.setattr(email_discovery, "_fetch", _make_fetch(pages))

    result = email_discovery.discover_emails("example.com", max_pages=12)
    emails = [c["email"] for c in result["contacts"]]
    # contact page has higher weight than home page.
    assert emails.index("contact@example.com") < emails.index("home@example.com")


# -----------------------------------------------------------------------------
# Pattern-inference honesty regressions
# -----------------------------------------------------------------------------


def test_single_word_role_emails_are_not_pattern_evidence():
    """complaints@/infodesk@/jobs@ must NOT masquerade as a 'firstl' pattern."""
    assert email_discovery.infer_patterns([
        "complaints@eib.org", "infodesk@eib.org", "jobs@eib.org",
        "procurementcomplaints@eib.org", "investigations@eib.org",
    ]) is None


def test_dotted_role_addresses_are_not_pattern_evidence():
    """investor.relations@ is a role address, not a personal first.last."""
    assert email_discovery.infer_patterns([
        "investor.relations@eib.org", "press.office@eib.org",
    ]) is None


def test_separator_patterns_generate_correctly():
    cases = [
        (["john.smith@x.org", "jane.miller@x.org"], "first.last", "jane.doe@x.org"),
        (["j.smith@x.org", "a.miller@x.org"], "f.last", "j.doe@x.org"),
        (["john.s@x.org", "jane.m@x.org"], "first.l", "jane.d@x.org"),
        (["j.s@x.org", "a.m@x.org"], "f.l", "j.d@x.org"),
    ]
    for emails, pattern, expected in cases:
        info = email_discovery.infer_patterns(emails)
        assert info is not None and info["pattern"] == pattern, (emails, info)
        got = email_discovery.find_for_person(
            "x.org", "Jane", "Doe", known_emails=emails)
        assert got["email"] == expected, (pattern, got)
        assert got["claim_status"] == "INFERRED"
        assert got["pattern"] == pattern


def test_find_for_person_unknown_when_only_role_evidence():
    got = email_discovery.find_for_person(
        "eib.org", "Jane", "Doe",
        known_emails=["complaints@eib.org", "infodesk@eib.org", "jobs@eib.org"])
    assert got["email"] is None
    assert got["claim_status"] == "UNKNOWN"
