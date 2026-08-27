"""The TALAIX identity lockup (T + teal dot + wordmark + domain) across chrome."""

import os

ROOT = os.path.dirname(__file__)


def _read(rel):
    with open(os.path.join(ROOT, "..", rel), encoding="utf-8") as fh:
        return fh.read()


def test_chrome_lockup_and_teal_dot():
    chrome = _read("website/js/chrome.js")
    assert ">TALAIX<" in chrome
    assert "logo-domain" in chrome
    assert "talaix.com" in chrome
    assert "#47B3A8" in chrome
    assert "currentColor" in chrome


def test_css_lockup_styles_and_brand_vars():
    css = _read("website/css/style.css")
    assert "--brand-teal: #47B3A8" in css
    assert "--brand-navy" in css
    assert ".logo-lockup" in css
    assert "letter-spacing: 0.30em" in css
    assert ".logo-domain" in css


def test_registry_pages_brand_matches_identity():
    pages = _read("src/dashboard/registry_pages.py")
    assert "TALAIX<span>" in pages
    assert "letter-spacing: 0.28em" in pages
    assert "#47B3A8" in pages
