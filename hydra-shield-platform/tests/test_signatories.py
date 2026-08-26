"""
Tests for the permanent signatory-list acquisition system.

All tests are offline: the PCAF page is stubbed with synthetic HTML fixtures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.dashboard.signatories import (
    _WIKIDATA_CACHE,

    SOURCES,
    SignatorySourceError,
    build_lead,
    category_to_segment,
    fetch_pcaf_signatories,
    merge_signatory,
    normalise_org,
    parse_pcaf_table,
    resolve_official_website,
    resolve_websites,
)


def _pcaf_html(rows: int, with_download: bool = True, self_hosted: bool = True) -> str:
    """Build a synthetic PCAF table with the requested number of data rows."""
    header = (
        '<table class="table sortable" id="instTable">'
        '<thead><tr>'
        '<th class="inst_name">Institution</th>'
        '<th class="hq">HQ</th>'
        '<th class="region">Region</th>'
        '<th class="category">Category</th>'
        '<th class="assets">Assets</th>'
        '<th class="status">Status</th>'
        '<th class="inst_date">Joined</th>'
        '<th class="inst_date">First disclosure</th>'
        '<th class="inst_date">Most recent disclosure</th>'
        '<th class="download">Download</th>'
        '</tr></thead><tbody>'
    )
    body = ""
    for i in range(rows):
        name = f"Test Bank {i}"
        assets = "644,938" if i % 2 == 0 else ""
        status = "Disclosed" if i == 0 else "Committed"
        if self_hosted:
            href = f"https://bank{i}.example.com/disclosure.pdf"
        else:
            href = f"/disclosure/{i}.pdf"
        download = (
            f'<td class="download"><a href="{href}">Download</a></td>'
            if with_download
            else '<td class="download"></td>'
        )
        body += (
            f'<tr>'
            f'<td class="inst_name"><a href="/org/{i}">{name}</a></td>'
            f'<td class="hq">NL</td>'
            f'<td class="region">Europe</td>'
            f'<td class="category">Commercial bank</td>'
            f'<td class="assets">{assets}</td>'
            f'<td class="status">{status}</td>'
            f'<td class="inst_date">2019</td>'
            f'<td class="inst_date">2021</td>'
            f'<td class="inst_date">2023</td>'
            f'{download}'
            f'</tr>'
        )
    footer = "</tbody></table>"
    return header + body + footer


SAMPLE_HTML = _pcaf_html(2)


@pytest.fixture(autouse=True)
def _clear_wikidata_cache():
    """The in-process Wikidata cache must not leak between offline tests."""
    _WIKIDATA_CACHE.clear()
    yield
    _WIKIDATA_CACHE.clear()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_pcaf_table_extracts_all_fields():
    rows = parse_pcaf_table(SAMPLE_HTML)
    assert len(rows) == 2
    first = rows[0]
    assert first["organization"] == "Test Bank 0"
    assert first["country"] == "NL"
    assert first["region"] == "Europe"
    assert first["category"] == "Commercial bank"
    assert first["assets_usd_m"] == 644938
    assert first["status"] == "Disclosed"
    assert first["date_joined"] == "2019"
    assert first["first_disclosure"] == "2021"
    assert first["most_recent_disclosure"] == "2023"
    assert first["disclosure_url"] == "https://bank0.example.com/disclosure.pdf"
    assert first["source"] == "pcaf"
    assert first["source_url"] == "https://carbonaccountingfinancials.com/en/signatories"

    second = rows[1]
    assert second["organization"] == "Test Bank 1"
    assert second["assets_usd_m"] is None
    assert second["status"] == "Committed"


def test_parse_pcaf_table_skips_header_row():
    rows = parse_pcaf_table(SAMPLE_HTML)
    assert all("Institution" not in r["organization"] for r in rows)


def test_fetch_pcaf_guard_raises_on_too_few_rows():
    def stub_fetch(_url: str) -> str:
        return _pcaf_html(150)

    with pytest.raises(SignatorySourceError) as exc_info:
        fetch_pcaf_signatories(fetch=stub_fetch)
    assert "parsed 150 rows" in str(exc_info.value)
    assert "refusing to import" in str(exc_info.value)


def test_fetch_pcaf_guard_passes_with_enough_rows():
    def stub_fetch(_url: str) -> str:
        return _pcaf_html(250)

    rows = fetch_pcaf_signatories(fetch=stub_fetch)
    assert len(rows) == 250


# ---------------------------------------------------------------------------
# Classification / normalisation
# ---------------------------------------------------------------------------


def test_category_to_segment_mapping():
    assert category_to_segment("Commercial bank") == "banking"
    assert category_to_segment("Insurance") == "insurance"
    assert category_to_segment("Asset owner/managers") == "investment"
    assert category_to_segment("Export credit agency") == "banking"
    assert category_to_segment("Some other category") == "investment"


def test_normalise_org_strips_suffixes_and_matches():
    assert normalise_org("ABN AMRO BANK N.V.") == "abn amro"
    assert normalise_org("abn amro bank n.v.") == "abn amro"
    assert normalise_org("ABN AMRO") == "abn amro"
    # Do not strip "bank" when it is the whole name.
    assert normalise_org("Bank") == "bank"


def test_normalise_org_empty_for_noise():
    assert normalise_org("S.A.") == ""


# ---------------------------------------------------------------------------
# Lead building / merging
# ---------------------------------------------------------------------------


def test_build_lead_schema():
    row = {
        "organization": "Example Bank",
        "country": "DE",
        "region": "Europe",
        "category": "Commercial bank",
        "assets_usd_m": 123456,
        "status": "Committed",
        "date_joined": "2020",
        "first_disclosure": "",
        "most_recent_disclosure": "",
        "disclosure_url": "https://example.com/disclosure.pdf",
        "source": "pcaf",
        "source_url": "https://carbonaccountingfinancials.com/en/signatories",
    }
    lead = build_lead(row, "pcaf")
    required = ("organization", "segment", "country", "website",
                "source", "date_checked")
    for field in required:
        assert lead.get(field), f"missing {field}"
    assert lead["segment"] == "banking"
    assert lead["website"] == "https://example.com"
    assert lead["website_source"] == "self-disclosure"
    assert lead["signatory_of"] == ["pcaf"]
    assert lead["priority"] == "medium"


def test_merge_signatory_appends_and_upgrades_priority():
    lead = build_lead(
        {
            "organization": "Merged Org",
            "country": "FR",
            "category": "Insurance",
            "status": "Committed",
            "disclosure_url": "https://merged.example/d.pdf",
            "source": "pcaf",
            "source_url": "https://carbonaccountingfinancials.com/en/signatories",
        },
        "pcaf",
    )
    assert lead["priority"] == "medium"
    merge_signatory(
        lead,
        "unepfi",
        {
            "status": "Disclosed",
            "assets_usd_m": None,
            "date_joined": "",
            "first_disclosure": "",
            "most_recent_disclosure": "",
            "disclosure_url": None,
            "category": "Insurance",
            "source_url": "https://www.unepfi.org/members/",
        },
    )
    assert lead["signatory_of"] == ["pcaf", "unepfi"]
    assert lead["priority"] == "high"
    assert "unepfi" in lead["signatory_meta"]


def test_merge_signatory_is_idempotent():
    lead = build_lead(
        {
            "organization": "Merged Org",
            "country": "FR",
            "category": "Insurance",
            "status": "Committed",
            "disclosure_url": "https://merged.example/d.pdf",
            "source": "pcaf",
            "source_url": "https://carbonaccountingfinancials.com/en/signatories",
        },
        "pcaf",
    )
    fields = {
        "status": "Committed",
        "assets_usd_m": None,
        "date_joined": "",
        "first_disclosure": "",
        "most_recent_disclosure": "",
        "disclosure_url": None,
        "category": "Insurance",
        "source_url": "https://www.unepfi.org/members/",
    }
    merge_signatory(lead, "unepfi", fields)
    interactions_before = len(lead["interactions"])
    merge_signatory(lead, "unepfi", fields)
    assert lead["signatory_of"] == ["pcaf", "unepfi"]
    assert len(lead["interactions"]) == interactions_before


# ---------------------------------------------------------------------------
# CLI import script
# ---------------------------------------------------------------------------


def _write_seed(tmp_path: Path, html: str, name: str = "pcaf_fixture.html") -> Path:
    path = tmp_path / name
    path.write_text(html, encoding="utf-8")
    return path


def _patch_pcaf_html(monkeypatch, html: str):
    def stub_get(_url: str, timeout: float = 30.0) -> str:
        return html

    monkeypatch.setattr("src.dashboard.signatories._requests_get", stub_get)


def test_import_script_creates_and_merges_leads(tmp_path, monkeypatch):
    from scripts.import_signatories import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()

    # Pre-seed an existing lead that matches one of the fixture rows.
    existing = build_lead(
        {
            "organization": "Test Bank 0",
            "country": "NL",
            "category": "Commercial bank",
            "status": "Committed",
            "disclosure_url": "https://old.example/0.pdf",
            "source": "pcaf",
            "source_url": "https://carbonaccountingfinancials.com/en/signatories",
        },
        "pcaf",
    )
    existing_path = leads_dir / "test-bank-0.json"
    existing_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    _patch_pcaf_html(monkeypatch, _pcaf_html(250))

    rc = main(["--dir", str(leads_dir)])
    assert rc == 0

    files = list(leads_dir.glob("*.json"))
    assert len(files) == 250

    merged = json.loads(existing_path.read_text(encoding="utf-8"))
    assert merged["signatory_of"] == ["pcaf"]
    assert merged["signatory_meta"]["pcaf"]["status"] == "Disclosed"
    assert merged["priority"] == "high"

    created_path = leads_dir / "test-bank-1.json"
    assert created_path.exists()
    created = json.loads(created_path.read_text(encoding="utf-8"))
    assert created["organization"] == "Test Bank 1"
    assert created["website"] == "https://bank1.example.com"
    assert created["website_source"] == "self-disclosure"


def test_import_script_dry_run_writes_nothing(tmp_path, monkeypatch):
    from scripts.import_signatories import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()

    _patch_pcaf_html(monkeypatch, _pcaf_html(250))

    rc = main(["--dir", str(leads_dir), "--dry-run"])
    assert rc == 0
    assert list(leads_dir.glob("*.json")) == []


def test_import_script_idempotent_rerun(tmp_path, monkeypatch):
    from scripts.import_signatories import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()

    _patch_pcaf_html(monkeypatch, _pcaf_html(250))

    assert main(["--dir", str(leads_dir)]) == 0
    first_files = sorted(leads_dir.glob("*.json"))
    first_content = {p.name: p.read_text(encoding="utf-8") for p in first_files}

    assert main(["--dir", str(leads_dir)]) == 0
    second_files = sorted(leads_dir.glob("*.json"))
    second_content = {p.name: p.read_text(encoding="utf-8") for p in second_files}

    assert first_files == second_files
    assert first_content == second_content


def test_import_script_aborts_source_on_guard_failure(tmp_path, monkeypatch):
    from scripts.import_signatories import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()

    _patch_pcaf_html(monkeypatch, _pcaf_html(150))

    rc = main(["--dir", str(leads_dir)])
    assert rc == 2
    assert list(leads_dir.glob("*.json")) == []


# ---------------------------------------------------------------------------
# Website resolution
# ---------------------------------------------------------------------------


def test_self_hosted_disclosure_domain_used():
    row = {
        "organization": "Zuger Kantonalbank",
        "country": "CH",
        "category": "Commercial bank",
        "status": "Disclosed",
        "disclosure_url": "https://www.zugerkb.ch/x.pdf",
        "source": "pcaf",
        "source_url": "https://carbonaccountingfinancials.com/en/signatories",
    }
    resolved, pending = resolve_websites([row], fetch=None, sleep_s=0)
    assert len(resolved) == 1
    assert resolved[0]["website"] == "https://www.zugerkb.ch"
    assert resolved[0]["website_source"] == "self-disclosure"
    assert len(pending) == 0


def test_pcaf_hosted_pdf_not_used_as_website():
    row = {
        "organization": "ABN AMRO BANK N.V.",
        "country": "NL",
        "category": "Commercial bank",
        "status": "Disclosed",
        "disclosure_url": "https://carbonaccountingfinancials.com/files/institutions_downloads/abn.pdf",
        "source": "pcaf",
        "source_url": "https://carbonaccountingfinancials.com/en/signatories",
    }
    # Force an empty Wikidata response so the row stays pending offline.
    empty_fetch = _wikidata_fetch_stub({"ABN+AMRO+BANK+N.V.": {"search": []}})
    resolved, pending = resolve_websites([row], fetch=empty_fetch, sleep_s=0)
    assert len(resolved) == 0
    assert len(pending) == 1
    assert pending[0]["pending_reason"].startswith("no official website found")


class _FakeResponse:
    def __init__(self, payload: dict, raise_on_call: bool = False):
        self._payload = payload
        self._raise = raise_on_call

    def raise_for_status(self):
        if self._raise:
            raise RuntimeError("network error")

    def json(self):
        return self._payload


def _wikidata_fetch_stub(mapping: dict):
    def fetch(url: str, timeout: float = 15.0) -> _FakeResponse:
        if "wbsearchentities" in url:
            query = url.split("search=")[1].split("&")[0]
            return _FakeResponse(mapping.get(query, {"search": []}))
        if "wbgetclaims" in url:
            qid = url.split("entity=")[1].split("&")[0]
            return _FakeResponse(mapping.get(qid, {"claims": {}}))
        return _FakeResponse({})

    return fetch


def test_resolve_official_website_good_entity():
    mapping = {
        "ABN+AMRO+BANK+N.V.": {
            "search": [
                {"id": "Q287471", "label": "ABN AMRO"},
            ]
        },
        "Q287471": {
            "claims": {
                "P856": [
                    {
                        "mainsnak": {
                            "datavalue": {"value": "https://www.abnamro.com"}
                        }
                    }
                ]
            }
        },
    }
    result = resolve_official_website("ABN AMRO BANK N.V.", fetch=_wikidata_fetch_stub(mapping))
    assert result == {
        "website": "https://www.abnamro.com",
        "wikidata_id": "Q287471",
        "source": "wikidata",
    }


def test_resolve_official_website_mismatched_label():
    mapping = {
        "Weird+Name+Bank": {
            "search": [
                {"id": "Q123", "label": "Totally Different Company"},
            ]
        },
    }
    result = resolve_official_website("Weird Name Bank", fetch=_wikidata_fetch_stub(mapping))
    assert result is None


def test_resolve_official_website_no_claims():
    mapping = {
        "No+Site+Bank": {
            "search": [
                {"id": "Q999", "label": "No Site Bank"},
            ]
        },
        "Q999": {"claims": {}},
    }
    result = resolve_official_website("No Site Bank", fetch=_wikidata_fetch_stub(mapping))
    assert result is None


def test_resolve_official_website_fetch_error():
    def broken_fetch(_url: str, _timeout: float = 15.0) -> _FakeResponse:
        return _FakeResponse({}, raise_on_call=True)

    result = resolve_official_website("Any Bank", fetch=broken_fetch)
    assert result is None


def test_resolve_websites_uses_wikidata_when_pcaf_hosted():
    row = {
        "organization": "ABN AMRO BANK N.V.",
        "country": "NL",
        "category": "Commercial bank",
        "status": "Disclosed",
        "disclosure_url": "https://carbonaccountingfinancials.com/files/abn.pdf",
        "source": "pcaf",
        "source_url": "https://carbonaccountingfinancials.com/en/signatories",
    }
    mapping = {
        "ABN+AMRO+BANK+N.V.": {
            "search": [{"id": "Q287471", "label": "ABN AMRO"}]
        },
        "Q287471": {
            "claims": {
                "P856": [
                    {"mainsnak": {"datavalue": {"value": "https://www.abnamro.com"}}}
                ]
            }
        },
    }
    resolved, pending = resolve_websites([row], fetch=_wikidata_fetch_stub(mapping), sleep_s=0)
    assert len(resolved) == 1
    assert resolved[0]["website"] == "https://www.abnamro.com"
    assert resolved[0]["website_source"] == "wikidata"
    assert resolved[0]["wikidata_id"] == "Q287471"
    assert len(pending) == 0


# ---------------------------------------------------------------------------
# CLI import script (two-stage)
# ---------------------------------------------------------------------------


def test_import_script_two_stage_resolved_and_pending(tmp_path, monkeypatch):
    from scripts.import_signatories import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()

    # Lower the structural guard so a tiny fixture is enough.
    monkeypatch.setattr("src.dashboard.signatories._MIN_PCAF_ROWS", 2)

    # Stub Wikidata so that rows with PCAF-hosted PDFs resolve.
    wd_mapping = {
        "Test+Bank+0": {"search": [{"id": "Q1", "label": "Test Bank 0"}]},
        "Q1": {"claims": {"P856": [{"mainsnak": {"datavalue": {"value": "https://www.testbank0.com"}}}]}}
    }
    monkeypatch.setattr(
        "src.dashboard.signatories._wikidata_requests_get",
        _wikidata_fetch_stub(wd_mapping),
    )

    html = _pcaf_html(2, self_hosted=False)
    _patch_pcaf_html(monkeypatch, html)

    # Redirect marketing/imports path to tmp_path.
    monkeypatch.setattr("scripts.import_signatories.IMPORTS_DIR", imports_dir)

    rc = main(["--dir", str(leads_dir)])
    assert rc == 0

    created = json.loads((leads_dir / "test-bank-0.json").read_text(encoding="utf-8"))
    assert created["website"] == "https://www.testbank0.com"
    assert created["website_source"] == "wikidata"
    assert created["wikidata_id"] == "Q1"

    pending_path = imports_dir / "signatory_pending.json"
    assert pending_path.exists()
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    assert pending["source"] == "pcaf"
    assert len(pending["rows"]) == 1
    assert pending["rows"][0]["organization"] == "Test Bank 1"
    assert pending["rows"][0]["pending_reason"].startswith("no official website found")


def test_import_script_purge_bad_removes_wrong_domain(tmp_path, monkeypatch):
    from scripts.import_signatories import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()

    # Seed a bad lead (buggy PCAF domain) and an unrelated lead.
    bad = build_lead(
        {
            "organization": "Bad Lead Bank",
            "country": "NL",
            "category": "Commercial bank",
            "status": "Committed",
            "disclosure_url": "https://carbonaccountingfinancials.com/files/x.pdf",
            "source": "pcaf",
            "source_url": "https://carbonaccountingfinancials.com/en/signatories",
        },
        "pcaf",
    )
    bad["website"] = "https://carbonaccountingfinancials.com"
    (leads_dir / "bad-lead-bank.json").write_text(json.dumps(bad, indent=2), encoding="utf-8")

    good = build_lead(
        {
            "organization": "Good Lead Bank",
            "country": "DE",
            "category": "Commercial bank",
            "status": "Committed",
            "disclosure_url": "https://good.example/disclosure.pdf",
            "source": "pcaf",
            "source_url": "https://carbonaccountingfinancials.com/en/signatories",
        },
        "pcaf",
    )
    (leads_dir / "good-lead-bank.json").write_text(json.dumps(good, indent=2), encoding="utf-8")

    _patch_pcaf_html(monkeypatch, _pcaf_html(250))

    rc = main(["--dir", str(leads_dir), "--purge-bad"])
    assert rc == 0
    assert not (leads_dir / "bad-lead-bank.json").exists()
    assert (leads_dir / "good-lead-bank.json").exists()


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------


def test_source_registry():
    by_id = {s["id"]: s for s in SOURCES}
    assert by_id["pcaf"]["live"] is True
    assert by_id["pcaf"]["adapter"] is not None
    assert by_id["unepfi"]["live"] is False
    assert "AJAX-rendered" in by_id["unepfi"]["pending_reason"]
    assert by_id["icma"]["live"] is False
    assert "JS-rendered" in by_id["icma"]["pending_reason"]
    assert by_id["gfanz"]["live"] is False
    assert "no public member list" in by_id["gfanz"]["pending_reason"]


def test_header_row_is_not_parsed_as_data():
    """PCAF uses <td> inside <thead> — the header must never become a row."""
    html = (
        '<table class="table sortable" id="instTable"><thead><tr>'
        '<td class="inst_name">Financial institution</td><td class="hq">Headquarters</td>'
        '<td class="region">Region</td><td class="category">Category</td>'
        '<td class="assets">Total financial assets</td><td class="status">Status</td>'
        '<td class="inst_date">Date joined</td><td class="inst_date">First</td>'
        '<td class="inst_date">Recent</td><td class="download">Download</td></tr></thead>'
        '<tbody><tr>'
        '<td class="inst_name">Real Bank AG</td><td class="hq">Germany</td>'
        '<td class="region">Europe</td><td class="category">Commercial bank</td>'
        '<td class="assets">1,234</td><td class="status">Committed</td>'
        '<td class="inst_date">20250101Jan, 2025</td><td class="inst_date">--</td>'
        '<td class="inst_date">--</td><td class="download"></td></tr></tbody></table>'
    )
    rows = parse_pcaf_table(html)
    assert [r["organization"] for r in rows] == ["Real Bank AG"]
