"""The purchase path contract (operator goal 2026-09-14: a site that can sell).

Locks the gap that made the site unsellable: the intent-heavy pages explained
the product but offered no way to buy it, a guest who tried was bounced to a
bare sign-in screen, and a buyer who *had* paid landed on an account page that
ignored Stripe's return flags — so nothing told them what they had bought or
how to collect it.

These tests pin the whole path, and cross-check it against the live backend so
the front end cannot drift from the API it calls.
"""

import os

ROOT = os.path.dirname(__file__)


def _read(rel):
    with open(os.path.join(ROOT, "..", rel), encoding="utf-8") as fh:
        return fh.read()


BUY_JS = "website/js/buy.js"
POST_JS = "website/js/postpurchase.js"
BILLING_PY = "src/dashboard/billing.py"

# page -> expected mount attribute
MOUNTED_PAGES = {
    "website/green-finance.html": 'data-buy-report="decision"',
    "website/insurance.html": 'data-buy-report="scientific"',
    "website/sample.html": 'data-buy-report="decision"',
    "website/sustainability.html": 'data-buy-tier="professional"',
}


# ---------------------------------------------------------------------------
# The mount points: buy where the intent is
# ---------------------------------------------------------------------------

def test_purchase_mounts_exist_on_the_intent_pages():
    for page, attribute in MOUNTED_PAGES.items():
        html = _read(page)
        assert 'class="buy-block"' in html, page
        assert attribute in html, f"{page} missing {attribute}"


def test_the_free_tool_pages_carry_the_location_into_the_purchase():
    """The visitor already told us which asset they care about — the purchase
    must not ask again."""
    for page in ("website/green-finance.html", "website/insurance.html"):
        html = _read(page)
        assert 'data-buy-location-input="assetLocInput"' in html, page
        assert 'id="assetLocInput"' in html, page


def test_buy_panel_is_loaded_site_wide():
    chrome = _read("website/js/chrome.js")
    assert "js/buy.js" in chrome, "the purchase panel must load from the shared chrome"


# ---------------------------------------------------------------------------
# The panel itself
# ---------------------------------------------------------------------------

def test_buy_panel_is_self_contained():
    """It must work on pages that do not load js/api.js (e.g. sample.html)."""
    js = _read(BUY_JS)
    assert "window.HSBuy" in js
    assert "HS.fetchJSON" not in js
    assert "HS.API" not in js
    assert "function getJSON(" in js and "function postJSON(" in js


def test_prices_come_from_the_live_billing_config():
    js = _read(BUY_JS)
    assert "'/v2/billing/config'" in js
    assert "amount_eur" in js
    assert "fallbackPrice" in js, "a fallback is needed while config loads or fails"
    # The published prices are the fallback, never the primary source.
    assert "€19" in js and "€39" in js and "€49" in js


def test_the_panel_says_what_the_buyer_gets_and_what_happens_next():
    js = _read(BUY_JS)
    for token in ("includes:", "buy-includes", "buy-steps",
                  "Create a free account", "Pay securely by card",
                  "Your pack is generated"):
        assert token in js, token
    # Honesty: the purchase block repeats the scope limits.
    assert "not assurance" in js and "Loss is never quantified" in js


def test_a_guest_is_told_why_there_is_a_sign_in_step():
    js = _read(BUY_JS)
    assert "'/v2/account'" in js, "session must be probed before checkout"
    assert "account.html?reason=signin&next=" in js
    assert "keep your choice and location" in js
    assert "INTENT_KEY" in js and "LOCATION_KEY" in js


def test_billing_disabled_degrades_to_the_invoice_route():
    js = _read(BUY_JS)
    assert "Card checkout is not enabled" in js
    assert "mailto:info@talaix.com" in js or "'mailto:' + CONTACT" in js
    assert "Prefer an invoice? Email us" in js


def test_the_checkout_endpoints_match_the_backend():
    """The front end may not invent an endpoint: both must exist server-side."""
    js = _read(BUY_JS)
    backend = _read(BILLING_PY)
    assert "'/v2/billing/checkout/report'" in js
    assert "'/v2/billing/checkout'" in js
    assert '@billing_bp.post("/checkout/report")' in backend
    assert '@billing_bp.post("/checkout")' in backend
    # The kinds the panel offers are the kinds the backend accepts.
    assert "kind not in _REPORT_KINDS" in backend
    assert "_REPORT_KINDS" in backend


# ---------------------------------------------------------------------------
# After the money: Stripe returns, the site must react
# ---------------------------------------------------------------------------

def test_account_page_loads_the_post_purchase_module():
    html = _read("website/account.html")
    assert "js/postpurchase.js" in html


def test_post_purchase_understands_every_stripe_return_flag():
    js = _read(POST_JS)
    backend = _read(BILLING_PY)
    # Whatever the backend sends the buyer back with, the page must handle it.
    for flag in ("purchased=report", "subscribed=1", "checkout=cancelled"):
        assert flag in backend, f"backend no longer returns {flag}"
    assert "params.get('purchased')" in js
    assert "params.get('subscribed')" in js
    assert "params.get('checkout')" in js


def test_a_paid_buyer_is_told_how_to_collect_the_pack():
    js = _read(POST_JS)
    assert "Payment received" in js
    assert "Generate my evidence pack" in js
    # The location chosen before sign-in survives to the report builder, which
    # accepts ?location= (js/reports.js).
    assert "reports.html?location=" in js
    assert "params.get('location')" in _read("website/js/reports.js")
    # Manual scope is a promise the operator must be able to keep.
    assert "one business day" in js


def test_an_interrupted_purchase_resumes_instead_of_restarting():
    js = _read(POST_JS)
    assert "Your purchase is waiting" in js
    assert "hs_buy_intent" in js
    assert "Back to where I was" in js


def test_post_purchase_never_claims_a_payment_it_cannot_see():
    """No flag in the URL must mean no panel at all."""
    js = _read(POST_JS)
    init = js.split("function init()", 1)[1]
    assert "return;" in init
    # Every panel is behind an explicit flag check.
    assert init.count("params.get(") >= 4


# ---------------------------------------------------------------------------
# Pricing page: what a buyer needs to know before paying
# ---------------------------------------------------------------------------

def test_pricing_page_explains_how_buying_works():
    html = _read("website/pricing.html")
    assert "How buying works" in html
    for token in ("Create a free account", "Pay by card", "Generate your pack",
                  "Stripe", "exclude VAT", "cancelled any time", "Invoice"):
        assert token in html, token


def test_pricing_page_keeps_the_live_checkout_buttons():
    """The pre-existing Stripe wiring must not be replaced by the new panel."""
    html = _read("website/pricing.html")
    assert 'data-checkout-report="decision"' in html
    assert 'data-checkout-report="scientific"' in html
    assert 'data-checkout-tier="professional"' in html
    assert "js/pricing.js" in html


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

def test_purchase_panel_styles_exist():
    css = _read("website/css/style.css")
    for selector in (".buy-panel", ".buy-price", ".buy-includes", ".buy-steps",
                     ".buy-actions", ".postpurchase"):
        assert selector in css, selector
