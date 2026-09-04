/* Talaix — Pricing page checkout wiring.
 *
 * Fetches the public billing config, updates visible price labels, and turns
 * subscribe / report buttons into Stripe Checkout flows when billing is enabled.
 * When billing is disabled or unreachable, buttons fall back to mailto CTAs.
 */
(function () {
    'use strict';

    var fetchJSON = HS.fetchJSON, API = HS.API;

    function postJSON(url, payload) {
        return fetchJSON(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    }

    function el(id) { return document.getElementById(id); }

    function status(kind, msg) {
        var area = el('statusArea');
        if (!area) return;
        area.innerHTML = msg
            ? '<div class="notice notice-' + kind + '">' + HS.esc(msg) + '</div>'
            : '';
        if (msg) area.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    var billingState = { enabled: false, products: {} };

    function priceLabel(key) {
        var p = billingState.products[key] || {};
        var amount = p.amount_eur;
        if (amount === undefined || amount === null) return '';
        return '€' + amount;
    }

    function updatePriceLabels() {
        Array.prototype.forEach.call(document.querySelectorAll('[data-price]'), function (span) {
            var key = span.getAttribute('data-price');
            var label = priceLabel(key);
            if (label) span.textContent = label;
        });
    }

    function contactHref(subject) {
        return 'mailto:info@talaix.com?subject=' + encodeURIComponent(subject);
    }

    function setButtonContact(btn, subject) {
        var oldLabel = btn.getAttribute('data-default-label') || btn.textContent.trim();
        btn.removeAttribute('data-checkout-tier');
        btn.removeAttribute('data-checkout-interval');
        btn.removeAttribute('data-checkout-report');
        if (btn.tagName.toLowerCase() === 'button') {
            var a = document.createElement('a');
            a.className = btn.className;
            a.href = contactHref(subject);
            a.textContent = 'Contact to activate';
            if (btn.parentNode) btn.parentNode.replaceChild(a, btn);
        } else {
            btn.href = contactHref(subject);
            btn.textContent = 'Contact to activate';
        }
    }

    function fallbackToContact() {
        Array.prototype.forEach.call(document.querySelectorAll('[data-checkout-tier]'), function (btn) {
            setButtonContact(btn, 'Activate subscription');
        });
        Array.prototype.forEach.call(document.querySelectorAll('[data-checkout-report]'), function (btn) {
            setButtonContact(btn, 'Activate report purchase');
        });
    }

    function loadBillingConfig() {
        return fetchJSON(API + '/v2/billing/config').then(function (res) {
            if (res.ok && res.body) {
                billingState.enabled = !!res.body.billing_enabled;
                billingState.products = res.body.products || {};
            } else {
                billingState.enabled = false;
            }
        }).catch(function () {
            billingState.enabled = false;
        });
    }

    function startCheckout(tier, interval, btn) {
        status('info', 'Starting secure checkout…');
        btn.disabled = true;
        postJSON(API + '/v2/billing/checkout', { tier: tier, interval: interval })
            .then(function (res) {
                btn.disabled = false;
                if (res.status === 401) {
                    status('warn', 'Please sign in or create an account first.');
                    setTimeout(function () { location.href = 'account.html?reason=signin'; }, 800);
                    return;
                }
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Checkout failed.');
                    return;
                }
                if (res.body && res.body.url) {
                    window.location.href = res.body.url;
                } else {
                    status('error', 'Checkout did not return a redirect URL.');
                }
            }).catch(function () {
                btn.disabled = false;
                status('error', 'Checkout request failed.');
            });
    }

    function startReportCheckout(kind, btn) {
        status('info', 'Starting secure checkout…');
        btn.disabled = true;
        postJSON(API + '/v2/billing/checkout/report', { kind: kind })
            .then(function (res) {
                btn.disabled = false;
                if (res.status === 401) {
                    status('warn', 'Please sign in or create an account first.');
                    setTimeout(function () { location.href = 'account.html?reason=signin'; }, 800);
                    return;
                }
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Checkout failed.');
                    return;
                }
                if (res.body && res.body.url) {
                    window.location.href = res.body.url;
                } else {
                    status('error', 'Checkout did not return a redirect URL.');
                }
            }).catch(function () {
                btn.disabled = false;
                status('error', 'Checkout request failed.');
            });
    }

    function wireButtons() {
        document.body.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-checkout-tier]');
            if (btn) {
                e.preventDefault();
                startCheckout(
                    btn.getAttribute('data-checkout-tier'),
                    btn.getAttribute('data-checkout-interval'),
                    btn
                );
                return;
            }
            var rbtn = e.target.closest('[data-checkout-report]');
            if (rbtn) {
                e.preventDefault();
                startReportCheckout(rbtn.getAttribute('data-checkout-report'), rbtn);
            }
        });
    }

    function init() {
        wireButtons();
        loadBillingConfig().then(function () {
            updatePriceLabels();
            if (!billingState.enabled) {
                fallbackToContact();
            }
        });
    }

    init();
})();
