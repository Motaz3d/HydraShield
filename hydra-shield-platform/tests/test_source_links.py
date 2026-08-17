"""
Offline integrity tests for the source registry and UI source links.

Norms (docs/EVIDENCE_ARCHITECTURE.md + the platform source policy):
every source entry must carry name, provider, official URL, purpose,
resolution, license, limitations and a normalised status; URLs must be
official https locations — never news/blog/marketing domains.
"""

import json
import os
import re

import pytest

REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "source_registry.json"
)
DATA_REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "data_registry.json"
)
KB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "solutions_knowledge.json"
)

#: Domains that must never appear as scientific/official evidence sources.
_FORBIDDEN_DOMAIN_HINTS = (
    "blogspot.", "wordpress.", "medium.com", "substack.com",
    "bbc.", "cnn.", "reuters.", "theguardian.", "nytimes.",
    "forbes.", "wikipedia.org",
)

_HTTPS_RE = re.compile(r"^https://[a-z0-9.-]+\.[a-z]{2,}(/|$)", re.IGNORECASE)


@pytest.fixture()
def registry():
    with open(REGISTRY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def data_registry_doc():
    with open(DATA_REGISTRY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_registry_every_entry_complete(registry):
    required = ("name", "provider", "url", "purpose", "resolution",
                "license", "limitations", "status", "hydrashield_use")
    for entry in registry["sources"]:
        for field in required:
            assert entry.get(field), f"{entry.get('name')}: missing {field}"


def test_data_registry_every_entry_complete(data_registry_doc):
    """The Data Observatory schema (config/data_registry.json): every field
    of the §1 entry schema must be present on every record."""
    required = ("id", "name", "provider", "provider_class", "url", "license",
                "geographic_coverage", "temporal_coverage",
                "spatial_resolution", "temporal_resolution",
                "update_frequency", "variables", "hazard_relevance",
                "provenance", "quality", "access_method",
                "api_or_download_url", "commercial_use", "status",
                "status_note")
    ids = set()
    for entry in data_registry_doc["datasets"]:
        for field in required:
            assert field in entry, f"{entry.get('id')}: missing {field}"
        assert entry["id"] not in ids, f"duplicate dataset id {entry['id']}"
        ids.add(entry["id"])


def test_data_registry_urls_official_https(data_registry_doc):
    for entry in data_registry_doc["datasets"]:
        url = entry["url"]
        assert _HTTPS_RE.match(url), f"{entry['id']}: not an https URL: {url}"
        for hint in _FORBIDDEN_DOMAIN_HINTS:
            assert hint not in url.lower(), \
                f"{entry['id']}: forbidden source domain in {url}"


def test_data_registry_status_vocabulary(data_registry_doc):
    for entry in data_registry_doc["datasets"]:
        assert entry["status"] in {"integrated", "candidate", "rejected"}


def test_registry_urls_official_https(registry):
    for entry in registry["sources"]:
        url = entry["url"]
        assert _HTTPS_RE.match(url), f"{entry['name']}: not an https URL: {url}"
        for hint in _FORBIDDEN_DOMAIN_HINTS:
            assert hint not in url.lower(), \
                f"{entry['name']}: forbidden source domain in {url}"


def test_registry_status_vocabulary(registry):
    for entry in registry["sources"]:
        assert entry["status"] in {"integrated", "candidate", "rejected"}


def test_registry_integrated_entries_have_integration_points(registry):
    for entry in registry["sources"]:
        if entry["status"] == "integrated":
            assert entry.get("integrated_in"), \
                f"{entry['name']}: integrated without integration point"


def test_map_layers_carry_official_urls():
    from src.climate import registry as hazard_registry

    hazard_registry.reset_for_tests()
    layers = []
    for module in hazard_registry.all_modules():
        layers.extend(module.map_layers())
    assert layers, "no map layers registered"
    for layer in layers:
        assert layer.get("url"), f"{layer['layer_id']}: missing official URL"
        assert _HTTPS_RE.match(layer["url"]), \
            f"{layer['layer_id']}: bad URL {layer['url']}"
    hazard_registry.reset_for_tests()


def test_snapshot_source_links_https():
    from src.dashboard.snapshot import _SOURCE_REGISTRY

    for key, (name, url) in _SOURCE_REGISTRY.items():
        assert _HTTPS_RE.match(url), f"snapshot source {key}: bad URL {url}"


def test_solutions_kb_sources_https():
    with open(KB_PATH, "r", encoding="utf-8") as fh:
        kb = json.load(fh)
    for sol in kb["solutions"]:
        assert sol.get("sources"), f"{sol['solution_id']}: no sources"
        for src in sol["sources"]:
            assert _HTTPS_RE.match(src.get("url", "")), \
                f"{sol['solution_id']}: bad source URL {src.get('url')}"
