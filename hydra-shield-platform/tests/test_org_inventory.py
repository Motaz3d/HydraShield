"""
Tests for the Wikidata organization inventory engine and CLI.

All Wikidata calls are stubbed so the suite stays offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.dashboard.org_inventory as org_inventory_module
from src.dashboard.org_inventory import (
    COUNTRIES,
    TARGETS,
    inventory_query,
    run_inventory,
    to_lead,
)
from src.dashboard.signatories import normalise_org


class _FakeResponse:
    def __init__(self, payload: dict, raise_on_call: bool = False):
        self._payload = payload
        self._raise = raise_on_call

    def raise_for_status(self):
        if self._raise:
            raise RuntimeError("network error")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_entity_qid_cache():
    """Prevent in-process Q-id cache from making tests order-dependent."""
    org_inventory_module._ENTITY_QID_CACHE.clear()
    yield


def _search_fetch_stub(mapping: dict):
    """mapping: search term (quoted) -> list of {id, label} entities."""
    def fetch(url: str, timeout: float = 15.0) -> _FakeResponse:
        import urllib.parse
        query = urllib.parse.unquote_plus(url.split("search=")[1].split("&")[0])
        return _FakeResponse({"search": mapping.get(query, [])})
    return fetch


def _sparql_fetch_stub(rows_by_query: dict):
    """rows_by_query: SPARQL query substring -> list of binding dicts.

    Keys may be strings (matched as substrings) or tuples of strings
    (all substrings must be present).  Tuple keys make it easy to
    differentiate results by concept and country.
    """
    def fetch(url: str, timeout: float = 60.0) -> _FakeResponse:
        import urllib.parse
        query = urllib.parse.unquote_plus(url.split("query=")[1].split("&")[0])
        for key, rows in rows_by_query.items():
            if isinstance(key, tuple):
                if all(k in query for k in key):
                    return _FakeResponse({"results": {"bindings": rows}})
            elif key in query:
                return _FakeResponse({"results": {"bindings": rows}})
        return _FakeResponse({"results": {"bindings": []}})
    return fetch


def _combined_fetch_stub(search_mapping: dict, sparql_rows: dict):
    """Dispatch _FakeResponses for both wbsearchentities and SPARQL calls."""
    search = _search_fetch_stub(search_mapping)
    sparql = _sparql_fetch_stub(sparql_rows)

    def fetch(url: str, timeout: float = 15.0) -> _FakeResponse:
        if "wbsearchentities" in url:
            return search(url, timeout)
        if "sparql" in url:
            return sparql(url, timeout)
        return _FakeResponse({})

    return fetch


def test_resolve_entity_qid_good_match(monkeypatch):
    mapping = {
        "bank": [{"id": "Q806066", "label": "bank"}],
    }
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _search_fetch_stub(mapping),
    )
    from src.dashboard.org_inventory import resolve_entity_qid
    assert resolve_entity_qid("bank") == "Q806066"


def test_resolve_entity_qid_mismatched_label(monkeypatch):
    mapping = {
        "xyzzy": [{"id": "Q1", "label": "Totally Different"}],
    }
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _search_fetch_stub(mapping),
    )
    from src.dashboard.org_inventory import resolve_entity_qid
    assert resolve_entity_qid("xyzzy") is None


def test_resolve_entity_qid_fetch_error(monkeypatch):
    def broken_fetch(_url: str, _timeout: float = 15.0) -> _FakeResponse:
        return _FakeResponse({}, raise_on_call=True)
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get", broken_fetch
    )
    from src.dashboard.org_inventory import resolve_entity_qid
    assert resolve_entity_qid("bank") is None


def test_inventory_query_contains_expected_fragments():
    q = inventory_query("Q806066", "Q148", limit=200)
    assert "wd:Q806066" in q
    assert "wd:Q148" in q
    assert "P856" in q
    assert "LIMIT 200" in q
    assert "?org ?orgLabel ?website" in q


def test_run_inventory_merges_cross_concept_and_counts(monkeypatch):
    search_mapping = {
        "bank": [{"id": "Q806066", "label": "bank"}],
        "insurance company": [{"id": "Q/Q2", "label": "insurance company"}],
        "China": [{"id": "Q148", "label": "China"}],
        "Japan": [{"id": "Q17", "label": "Japan"}],
    }
    sparql_rows = {
        ("wd:Q806066", "wd:Q148"): [
            {
                "org": {"value": "http://www.wikidata.org/entity/Q12345"},
                "orgLabel": {"value": "Asia Bank Corp"},
                "website": {"value": "https://asiabank.example"},
            },
            {
                "org": {"value": "http://www.wikidata.org/entity/Q12346"},
                "orgLabel": {"value": "Pacific Bank Ltd"},
                "website": {"value": ""},
            },
        ],
        ("wd:Q/Q2", "wd:Q148"): [
            {
                "org": {"value": "http://www.wikidata.org/entity/Q12345"},
                "orgLabel": {"value": "Asia Bank Corp"},
                "website": {"value": "https://asiabank.example"},
            },
        ],
        ("wd:Q806066", "wd:Q17"): [],
        ("wd:Q/Q2", "wd:Q17"): [],
    }
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _combined_fetch_stub(search_mapping, sparql_rows),
    )

    result = run_inventory(
        countries=["CN", "JP"],
        concepts=["bank", "insurance company"],
        limit_per_query=200,
        sleep_s=0,
    )

    assert result["counts"]["queries"] == 4  # 2 concepts × 2 countries
    rows = result["rows"]
    asia = next(r for r in rows if r["organization"] == "Asia Bank Corp")
    # Asia Bank appears under both bank and insurance company concepts.
    assert set(asia["concepts"]) == {"bank", "insurance company"}
    assert asia["website"] == "https://asiabank.example"
    assert asia["country_code"] == "CN"

    # Pacific Bank has no website and is still in rows but flagged without_website.
    pacific = next(r for r in rows if r["organization"] == "Pacific Bank Ltd")
    assert pacific["website"] is None
    assert result["counts"]["with_website"] == 1
    assert result["counts"]["without_website"] == 1
    assert result["counts"]["unique_orgs"] == 2


def test_run_inventory_skips_unresolvable_and_continues(monkeypatch):
    search_mapping = {
        "bank": [{"id": "Q806066", "label": "bank"}],
        "China": [{"id": "Q148", "label": "China"}],
    }
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _search_fetch_stub(search_mapping),
    )
    monkeypatch.setattr(
        "src.dashboard.org_inventory.sparql",
        lambda _query, fetch=None: [],
    )
    result = run_inventory(
        countries=["CN", "JP"],
        concepts=["bank", "insurance company"],
        sleep_s=0,
    )
    assert result["counts"]["queries"] == 1  # only CN+bank (JP unresolved, insurance unresolved)
    skipped_kinds = {s["kind"] for s in result["skipped"]}
    assert "concept" in skipped_kinds
    assert "country" in skipped_kinds


def test_run_inventory_records_capped_queries(monkeypatch):
    search_mapping = {
        "bank": [{"id": "Q806066", "label": "bank"}],
        "China": [{"id": "Q148", "label": "China"}],
    }
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _search_fetch_stub(search_mapping),
    )
    rows = [
        {
            "org": {"value": f"http://www.wikidata.org/entity/Q{i}"},
            "orgLabel": {"value": f"Bank {i}"},
            "website": {"value": "https://example.com"},
        }
        for i in range(5)
    ]
    monkeypatch.setattr(
        "src.dashboard.org_inventory.sparql",
        lambda _query, fetch=None: rows,
    )
    result = run_inventory(
        countries=["CN"],
        concepts=["bank"],
        limit_per_query=5,
        sleep_s=0,
    )
    assert len(result["capped_queries"]) == 1


def test_to_lead_matches_workspace_required_fields():
    row = {
        "organization": "Test Bank AG",
        "country_code": "DE",
        "segment": "banking",
        "website": "https://testbank.example",
        "wikidata_id": "Q999",
        "concepts": ["bank"],
        "source_url": "https://www.wikidata.org/wiki/Q999",
    }
    lead = to_lead(row)
    required = (
        "organization", "segment", "country", "website",
        "source", "date_checked"
    )
    for field in required:
        assert lead.get(field), f"missing {field}"
    assert lead["website"] == "https://testbank.example"
    assert lead["wikidata_id"] == "Q999"
    assert lead["concepts"] == ["bank"]
    assert lead["inventory_meta"]["concept_label"] == "bank"


def test_cli_creates_lead_and_pending_and_merges_existing(tmp_path, monkeypatch):
    from scripts.run_org_inventory import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    # Pre-seed an existing lead matching one of the rows.
    existing = to_lead(
        {
            "organization": "Asia Bank Corp",
            "country_code": "CN",
            "segment": "banking",
            "website": "https://old.example",
            "wikidata_id": "",
            "concepts": [],
            "source_url": "https://www.wikidata.org/wiki/Q12345",
        }
    )
    (leads_dir / "asia-bank-corp.json").write_text(
        json.dumps(existing, indent=2), encoding="utf-8"
    )

    search_mapping = {
        "bank": [{"id": "Q806066", "label": "bank"}],
        "China": [{"id": "Q148", "label": "China"}],
    }
    sparql_rows = {
        "wd:Q806066": [
            {
                "org": {"value": "http://www.wikidata.org/entity/Q12345"},
                "orgLabel": {"value": "Asia Bank Corp"},
                "website": {"value": "https://asiabank.example"},
            },
            {
                "org": {"value": "http://www.wikidata.org/entity/Q12346"},
                "orgLabel": {"value": "Pacific Bank Ltd"},
                "website": {"value": ""},
            },
        ],
    }

    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _combined_fetch_stub(search_mapping, sparql_rows),
    )
    monkeypatch.setattr("scripts.run_org_inventory.IMPORTS_DIR", imports_dir)
    monkeypatch.setattr("scripts.run_org_inventory.REPORTS_DIR", reports_dir)

    rc = main(["--countries", "CN", "--concepts", "bank", "--dir", str(leads_dir), "--sleep", "0"])
    assert rc == 0

    # Existing lead merged, website preserved (not overwritten).
    merged = json.loads((leads_dir / "asia-bank-corp.json").read_text(encoding="utf-8"))
    assert merged["website"] == "https://old.example"
    assert "https://www.wikidata.org/wiki/Q12345" in merged.get("inventory_of", [])
    assert "Q12345" in merged.get("wikidata_id", "")

    # New lead with website created.
    # Pacific Bank has no website -> pending.
    pending_path = imports_dir / "inventory_pending.json"
    assert pending_path.exists()
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    assert any(r["organization"] == "Pacific Bank Ltd" for r in pending["rows"])

    # Report written.
    report = json.loads((reports_dir / "inventory_latest.json").read_text(encoding="utf-8"))
    assert report["totals"]["queries"] == 1


def test_cli_dry_run_writes_nothing(tmp_path, monkeypatch):
    from scripts.run_org_inventory import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    search_mapping = {
        "bank": [{"id": "Q806066", "label": "bank"}],
        "China": [{"id": "Q148", "label": "China"}],
    }
    sparql_rows = {
        "wd:Q806066": [
            {
                "org": {"value": "http://www.wikidata.org/entity/Q12345"},
                "orgLabel": {"value": "Asia Bank Corp"},
                "website": {"value": "https://asiabank.example"},
            },
        ],
    }
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _combined_fetch_stub(search_mapping, sparql_rows),
    )
    monkeypatch.setattr("scripts.run_org_inventory.IMPORTS_DIR", imports_dir)
    monkeypatch.setattr("scripts.run_org_inventory.REPORTS_DIR", reports_dir)

    rc = main(["--countries", "CN", "--concepts", "bank", "--dir", str(leads_dir), "--sleep", "0", "--dry-run"])
    assert rc == 0
    assert list(leads_dir.glob("*.json")) == []
    assert not (imports_dir / "inventory_pending.json").exists()
    assert not (reports_dir / "inventory_latest.json").exists()


def test_cli_honesty_no_website_lead(tmp_path, monkeypatch):
    from scripts.run_org_inventory import main

    leads_dir = tmp_path / "leads"
    leads_dir.mkdir()
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    search_mapping = {
        "bank": [{"id": "Q806066", "label": "bank"}],
        "China": [{"id": "Q148", "label": "China"}],
    }
    sparql_rows = {
        "wd:Q806066": [
            {
                "org": {"value": "http://www.wikidata.org/entity/Q12346"},
                "orgLabel": {"value": "Pacific Bank Ltd"},
                "website": {"value": ""},
            },
        ],
    }
    monkeypatch.setattr(
        "src.dashboard.org_inventory._wikidata_requests_get",
        _combined_fetch_stub(search_mapping, sparql_rows),
    )
    monkeypatch.setattr("scripts.run_org_inventory.IMPORTS_DIR", imports_dir)
    monkeypatch.setattr("scripts.run_org_inventory.REPORTS_DIR", reports_dir)

    main(["--countries", "CN", "--concepts", "bank", "--dir", str(leads_dir), "--sleep", "0"])
    assert list(leads_dir.glob("*.json")) == []
    pending = json.loads((imports_dir / "inventory_pending.json").read_text(encoding="utf-8"))
    assert len(pending["rows"]) == 1
