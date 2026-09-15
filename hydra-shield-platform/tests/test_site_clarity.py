"""Site clarity contract (operator-approved 2026-09-14).

Locks the fixes for the external review that scored product clarity 6.5/10 and
message clarity for a new visitor 6/10:

* the homepage must state what Talaix is and what you get before asking the
  visitor to diagnose themselves;
* the whole product map lives on one page (`capabilities.html`) instead of
  ~30 cards competing on the homepage;
* the site never contradicts itself on the hazard count;
* the deliverable (a PDF evidence pack) is readable without an account;
* a plain-language "who is behind this" page exists and is reachable;
* the nav labels are plain words, not abstract ones.
"""

import glob
import importlib.util
import os

ROOT = os.path.dirname(__file__)
WEBSITE = os.path.join(ROOT, "..", "website")
SAMPLE_PDF = os.path.join(WEBSITE, "assets", "samples",
                          "talaix-sample-evidence-pack.pdf")


def _read(rel):
    with open(os.path.join(ROOT, "..", rel), encoding="utf-8") as fh:
        return fh.read()


def _website_html():
    for path in sorted(glob.glob(os.path.join(WEBSITE, "*.html"))):
        with open(path, encoding="utf-8") as fh:
            yield os.path.basename(path), fh.read()


def _cards(html):
    return html.count("story-card") + html.count("item-card")


# ---------------------------------------------------------------------------
# Homepage: what it is, what you get, what it costs
# ---------------------------------------------------------------------------

def test_homepage_states_the_product_in_plain_words():
    html = _read("website/index.html")
    assert "your auditor can trace" in html
    # The positioning sentence names the input, the output and the frameworks.
    assert "Talaix turns satellite and open Earth-observation data" in html
    assert "evidence packs for EU disclosure" in html
    # The hero is no longer only a question the visitor must answer first.
    assert "What do you need to<br>" not in html


def test_homepage_shows_the_deliverable_and_the_entry_price():
    html = _read("website/index.html")
    assert "€19" in html, "entry price must be visible on the homepage"
    assert "Check your CSRD scope — free" in html
    assert "assets/samples/talaix-sample-evidence-pack.pdf" in html
    assert 'id="how-it-works"' in html


def test_homepage_is_not_a_catalogue_of_everything():
    """The homepage is a decision, not an inventory: the full map moved to
    capabilities.html, so the homepage card count stays small."""
    html = _read("website/index.html")
    assert _cards(html) <= 18, f"homepage still overloaded: {_cards(html)} cards"
    assert 'href="capabilities.html"' in html
    # The three primary entry points stay on the homepage.
    for page in ("sustainability.html", "green-finance.html", "supplychain.html"):
        assert f'href="{page}"' in html, page


def test_homepage_keeps_the_live_monitor_and_audience_links():
    """Guards the elements other tests and the risk-snapshot wiring depend on."""
    html = _read("website/index.html")
    assert 'id="hazardBoard"' in html
    assert "wildfire, flood, heat, drought" in html
    for sector in ("government", "insurance", "real-estate",
                   "consulting", "investors", "banks"):
        assert f"industries.html?sector={sector}" in html, sector


# ---------------------------------------------------------------------------
# One page for the whole product
# ---------------------------------------------------------------------------

def test_capabilities_page_carries_the_full_product_map():
    html = _read("website/capabilities.html")
    for page in ("sustainability.html", "green-finance.html", "supplychain.html",
                 "forensics.html", "insurance.html", "licensing.html",
                 "reports.html", "map.html", "sources.html", "academy.html",
                 "intelligence.html?mode=siting", "intelligence.html?mode=funding"):
        assert page in html, page
    assert 'data-page="capabilities"' in html


def test_every_product_page_is_reachable_from_the_capabilities_map():
    """Nothing may be buried: every public product page is one hop from the
    capability map (the map is itself one hop from the homepage)."""
    html = _read("website/capabilities.html")
    pages = {os.path.basename(p) for p in glob.glob(os.path.join(WEBSITE, "*.html"))}
    buried = [
        page for page in ("compliance.html", "sustainability.html",
                          "green-finance.html", "supplychain.html", "forensics.html",
                          "insurance.html", "intelligence.html", "map.html",
                          "reports.html", "licensing.html", "academy.html",
                          "pricing.html", "sources.html", "sample.html")
        if page in pages and page not in html
    ]
    assert not buried, f"not linked from capabilities.html: {buried}"


# ---------------------------------------------------------------------------
# No self-contradiction on the hazard count
# ---------------------------------------------------------------------------

def test_no_page_contradicts_the_hazard_count():
    offenders = []
    for name, html in _website_html():
        if "7 hazards" in html:
            offenders.append(f"{name}: claims 7 hazards")
        if "6 of 6 hazards" in html:
            offenders.append(f"{name}: ambiguous '6 of 6 hazards'")
    assert not offenders, offenders


def test_hazard_count_is_consistent_across_the_public_pages():
    """10 hazards is the platform roster; the DNSH subset is named as a subset."""
    for rel in ("website/index.html", "website/pricing.html",
                "website/capabilities.html", "website/about.html"):
        html = _read(rel)
        assert "10 hazards" in html, rel
    green = _read("website/green-finance.html")
    assert "DNSH hazards relevant to this asset" in green
    assert "up to 10 hazards per site" in green


def test_catalogued_vs_integrated_datasets_are_not_conflated():
    html = _read("website/index.html")
    assert "datasets integrated (167 catalogued)" in html
    about = _read("website/about.html")
    assert "25 datasets integrated" in about and "167 catalogued" in about


# ---------------------------------------------------------------------------
# The deliverable: a real sample pack, no account required
# ---------------------------------------------------------------------------

def test_sample_pack_pdf_is_a_real_pdf():
    assert os.path.exists(SAMPLE_PDF), "sample pack PDF missing"
    with open(SAMPLE_PDF, "rb") as fh:
        blob = fh.read()
    assert blob.startswith(b"%PDF")
    assert len(blob) > 4_000, "sample pack looks truncated"


def test_sample_page_embeds_the_pack_and_says_what_it_is():
    html = _read("website/sample.html")
    assert "assets/samples/talaix-sample-evidence-pack.pdf" in html
    assert "not a live run" in html, "the sample must declare what it is"
    assert 'data-page="sample"' in html


def test_sample_pack_builder_reports_healthy():
    spec = importlib.util.spec_from_file_location(
        "build_sample_pack",
        os.path.join(ROOT, "..", "scripts", "build_sample_pack.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check() == 0
    # The source of truth for the figures is the published engine output.
    assert "Clervaux" in module.SAMPLE_MD
    assert "2026-08-25" in module.SAMPLE_MD


# ---------------------------------------------------------------------------
# Who is behind this + plain nav labels
# ---------------------------------------------------------------------------

def test_about_page_answers_who_is_behind_the_evidence():
    html = _read("website/about.html")
    assert 'data-page="about"' in html
    for token in ("Luxembourg", "Motaz Omarien", "info@talaix.com",
                  "github.com/Motaz3d/tore", "What we are not"):
        assert token in html, token


def test_nav_labels_are_plain_and_the_company_page_is_reachable():
    js = _read("website/js/chrome.js")
    assert "label: 'How it works'" in js
    assert "label: 'Start'" not in js
    assert "label: 'All capabilities (one page)'" in js
    assert "about.html" in js and "sample.html" in js
    assert "capabilities.html" in js


def test_capabilities_dropdown_is_trimmed_to_the_core_doors():
    """Operator decision 2026-09-15: the Capabilities dropdown exposes only the
    core doors; specialist tools are demoted out of the menu (marked nav:false)
    but remain declared so the footer and the capability map still reach them."""
    js = _read("website/js/chrome.js")
    assert js.count("nav: false") == 7
    for label in ("Forensics", "Investment & Siting", "Reports",
                  "Environmental Licensing", "Academy",
                  "Verify a document", "Data sources"):
        assert f"label: '{label}', nav: false" in js, label


def test_sitemap_lists_the_new_pages():
    xml = _read("website/sitemap.xml")
    for url in ("https://talaix.com/capabilities.html",
                "https://talaix.com/sample.html",
                "https://talaix.com/about.html"):
        assert url in xml, url


def test_llms_txt_points_assistants_at_the_start_here_pages():
    txt = _read("website/llms.txt")
    assert "## Start here" in txt
    for url in ("capabilities.html", "sample.html", "about.html"):
        assert url in txt, url
