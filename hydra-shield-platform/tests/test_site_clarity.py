"""Site clarity contract (operator-approved 2026-09-14, repositioned 2026-10-18).

Locks the fixes for the external review that scored product clarity 6.5/10 and
message clarity for a new visitor 6/10 — and, since 2026-10-18, the
insurance-first repositioning (operator decision):

* the homepage states what Talaix is — financial risk for insurance — and what
  you get before asking the visitor to diagnose themselves;
* the whole product map lives on one page (`capabilities.html`) instead of
  ~30 cards competing on the homepage;
* the site never contradicts itself on the hazard count;
* the deliverable (a PDF evidence pack) is readable without an account;
* a plain-language "who is behind this" page exists and is reachable;
* the nav labels are plain words, insurance-first;
* periodic monitoring is a first-class, honestly-framed promise.
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
    assert "for insurance" in html
    # The positioning sentence names the input, the output and the audience.
    assert "Talaix turns satellite and open Earth-observation data" in html
    assert "financial-risk intelligence" in html
    assert "periodic reports on the companies, markets" in html
    # The hero is no longer only a question the visitor must answer first.
    assert "What do you need to<br>" not in html


def test_homepage_shows_the_deliverable_and_the_entry_price():
    html = _read("website/index.html")
    assert "€19" in html, "entry price must be visible on the homepage"
    assert "Screen an insured asset — free" in html
    assert "assets/samples/talaix-sample-evidence-pack.pdf" in html
    assert 'id="how-it-works"' in html


def test_homepage_is_not_a_catalogue_of_everything():
    """The homepage is a decision, not an inventory: the full map moved to
    capabilities.html, so the homepage card count stays small."""
    html = _read("website/index.html")
    assert _cards(html) <= 18, f"homepage still overloaded: {_cards(html)} cards"
    assert 'href="capabilities.html"' in html
    # The three primary entry points stay on the homepage (insurance first).
    for page in ("insurance.html", "intelligence.html", "monitoring.html"):
        assert page in html, page


def test_homepage_keeps_the_live_monitor_and_audience_links():
    """Guards the elements other tests and the risk-snapshot wiring depend on."""
    html = _read("website/index.html")
    assert 'id="hazardBoard"' in html
    assert "wildfire, flood, heat, drought" in html
    # Insurance first, financing second; the rest reachable via the industries hub.
    assert "insurance.html" in html
    assert "industries.html?sector=banks" in html
    assert "industries.html?sector=investors" in html
    assert "industries.html" in html


# ---------------------------------------------------------------------------
# One page for the whole product
# ---------------------------------------------------------------------------

def test_capabilities_page_carries_the_full_product_map():
    html = _read("website/capabilities.html")
    for page in ("sustainability.html", "green-finance.html", "supplychain.html",
                 "forensics.html", "insurance.html", "licensing.html",
                 "reports.html", "map.html", "sources.html", "academy.html",
                 "intelligence.html?mode=siting", "intelligence.html?mode=funding",
                 "monitoring.html"):
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
                          "pricing.html", "sources.html", "sample.html",
                          "monitoring.html")
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
    """Operator decision 2026-10-18: the Capabilities dropdown exposes only the
    core doors — insurance risk profile, portfolio & market screening, periodic
    monitoring, EU compliance and maps; specialist tools (incl. the demoted EU
    compliance pages and Agent Access) are marked nav:false but remain declared
    so the footer and the capability map still reach them."""
    js = _read("website/js/chrome.js")
    assert js.count("nav: false") == 10
    for label in ("Forensics", "Green Finance", "Sustainability & CSRD",
                  "Supply Chain & EUDR", "Reports", "Environmental Licensing",
                  "Academy", "Verify a document", "Data sources", "Agent Access"):
        assert f"label: '{label}', nav: false" in js, label
    # The insurance-first doors stay visible in the dropdown (not nav:false).
    for label in ("Insurance risk profile", "Portfolio & market screening",
                  "Periodic monitoring", "EU compliance"):
        assert f"label: '{label}'" in js, label


def test_sitemap_lists_the_new_pages():
    xml = _read("website/sitemap.xml")
    for url in ("https://talaix.com/capabilities.html",
                "https://talaix.com/sample.html",
                "https://talaix.com/about.html",
                "https://talaix.com/monitoring.html"):
        assert url in xml, url


def test_monitoring_page_is_honest_and_reachable():
    """Operator decision 2026-10-18: periodic monitoring is the primary promise,
    honestly framed on a dedicated page — what is live today vs the roadmap."""
    html = _read("website/monitoring.html")
    assert 'data-page="monitoring"' in html
    assert "Periodic" in html and "companies" in html
    # Honest about what is shipped vs planned.
    assert "Live today" in html and "On the roadmap" in html
    assert "claim to have shipped today" in html
    # Reachable from the nav, the capability map, the sitemap and llms.txt.
    js = _read("website/js/chrome.js")
    assert "href: 'monitoring.html'" in js
    assert "monitoring.html" in _read("website/capabilities.html")
    assert "https://talaix.com/monitoring.html" in _read("website/sitemap.xml")
    assert "monitoring.html" in _read("website/llms.txt")


def test_agent_access_window_is_in_the_nav_and_reachable():
    """Operator decision 2026-09-28: the talaiz governance service is offered
    under the Talaix brand as a window inside the platform — one nav item
    and one page. No second product, no redesign, no second login."""
    js = _read("website/js/chrome.js")
    assert "label: 'Agent Access'" in js
    assert "href: 'agent-access.html'" in js
    # The footer reaches it too, so it is never a dead end.
    assert "'agent-access'" in js
    html = _read("website/agent-access.html")
    assert 'data-page="agent-access"' in html
    assert "Agent Access" in html
    assert "window inside" in html
    # Reachable from the capability map, the sitemap and the assistant index.
    assert "agent-access.html" in _read("website/capabilities.html")
    assert "https://talaix.com/agent-access.html" in _read("website/sitemap.xml")
    assert "agent-access.html" in _read("website/llms.txt")


def test_agent_access_is_self_serve_not_email_gated():
    """Operator feedback 2026-09-28: the service must be properly explained and
    tryable, not condensed into one window and not gated behind an email."""
    html = _read("website/agent-access.html")
    assert "mailto:" not in html
    assert "https://talaix.com/api/mcp" in html
    assert "Try the tools now" in html
    # Session-aware CTAs: a signed-in user never sees "Sign in".
    assert "guest-only" in html and "user-only" in html
    # Properly explained, not one condensed window.
    for token in ("How it works", "Features", "Security by design",
                  "Connector", "Gateway", "Audit trail"):
        assert token in html, token


def test_agent_access_setup_guide_is_published():
    """Operator 2026-09-28: the MCP setup guide (how a normal user connects)
    must be a public page, linked from the Agent Access page, the footer, the
    capability map and the sitemap."""
    html = _read("website/agent-access-setup.html")
    assert 'data-page="agent-access-setup"' in html
    assert "https://talaix.com/api/mcp" in html
    for token in ("Claude", "Cursor", "VS Code", "Streamable HTTP"):
        assert token in html, token
    assert "agent-access-setup.html" in _read("website/agent-access.html")
    assert "agent-access-setup.html" in _read("website/js/chrome.js")
    assert "agent-access-setup.html" in _read("website/capabilities.html")
    assert "https://talaix.com/agent-access-setup.html" in _read("website/sitemap.xml")
    assert "agent-access-setup.html" in _read("website/llms.txt")


def test_llms_txt_points_assistants_at_the_start_here_pages():
    txt = _read("website/llms.txt")
    assert "## Start here" in txt
    for url in ("capabilities.html", "sample.html", "about.html"):
        assert url in txt, url


# ---------------------------------------------------------------------------
# Contrast: the white-on-dark variant must not land on a light section
# ---------------------------------------------------------------------------

def test_industries_tabs_are_readable_on_the_light_background():
    """Operator report 2026-09-22: on talaix.com/industries.html the sector tab
    row (Banks & lenders · Government · Insurance · Investors · Real estate ·
    Consultants & auditors) was invisible — the tabs were built with
    `.btn-outline`, the *white-on-dark* variant (white label, 30%-white border,
    transparent fill), while the row sits in a `.content-section` on the light
    body. Five of the six tabs were white-on-white; only the selected one
    (`.btn-primary`) was visible.

    `.btn-outline` stays correct inside the dark `.page-hero`, where the sector
    action buttons live, so the guard is on the `class="btn btn-outline"` HTML
    form — in this file it is only ever injected into a light container."""
    js = _read("website/js/industries.js")
    assert 'class="btn btn-outline"' not in js
    # The tab row: first render and the active/inactive toggle.
    assert 'class="btn btn-outline-dark" data-sector=' in js
    assert "active ? 'btn btn-primary' : 'btn btn-outline-dark'" in js
    # The hub's secondary action sits in a white `.panel` on the light section.
    assert 'class="btn btn-outline-dark">Sign in' in js
    # Every remaining white-on-dark use is a sector action button (dark hero).
    hero_uses = [ln for ln in js.splitlines() if "'btn btn-outline'" in ln]
    assert hero_uses, "the dark hero still needs the white-on-dark variant"
    assert all("['" in ln for ln in hero_uses), hero_uses


def test_the_light_background_outline_variant_still_has_real_contrast():
    """`.btn-outline-dark` is the only outline variant usable on a light
    section, so it must stay dark-on-transparent — readable before hover — and
    `.btn-outline` must stay the white-on-dark one, which is why the tabs broke."""
    css = _read("website/css/style.css")
    on_light = css.split(".btn-outline-dark {", 1)[1].split("}", 1)[0]
    assert "transparent" in on_light
    assert "var(--primary-dark)" in on_light
    on_dark = css.split(".btn-outline {", 1)[1].split("}", 1)[0]
    assert "var(--white)" in on_dark
