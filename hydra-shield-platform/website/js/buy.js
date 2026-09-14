/* Talaix — purchase panel (the one reusable conversion block).
 *
 * Why: the intent-heavy pages (Green Finance, Insurance, CSRD, the sample
 * pack) explained the product but offered no way to buy it, so the only
 * purchase route was pricing.html — and a guest who clicked there was
 * bounced to a bare sign-in screen with no explanation of what they were
 * buying or what happens next.
 *
 * This module renders a complete, honest purchase block:
 *   - the live price (from /api/v2/billing/config — never hardcoded),
 *   - exactly what the buyer receives,
 *   - the three steps between clicking and holding the pack,
 *   - an invoice-by-email route for buyers who cannot use a card flow,
 *   - a guest path that remembers the intent and the location, so signing in
 *     resumes the purchase instead of restarting it.
 *
 * Mount (no build step, self-contained — it does not require js/api.js):
 *
 *   <div class="buy-block" data-buy-report="decision"
 *        data-buy-context="green-finance"
 *        data-buy-location-input="assetLocInput"></div>
 *   <div class="buy-block" data-buy-tier="professional" data-buy-interval="monthly"></div>
 *
 * Contract (tests/test_buy_path.py): billing config drives the price, a guest
 * is never silently dropped on a login wall, billing-disabled degrades to the
 * invoice route, and the purchase intent survives the sign-in round trip.
 */
(function () {
    'use strict';

    var API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8051/api'
        : '/api';

    var INTENT_KEY = 'hs_buy_intent';
    var LOCATION_KEY = 'hs_buy_location';
    var CONTACT = 'info@talaix.com';

    /* What the buyer receives — stated plainly, and only what is true. */
    var REPORT_COPY = {
        decision: {
            title: 'Decision-ready evidence pack',
            priceKey: 'report_decision',
            fallbackPrice: '€19',
            lead: 'One location. The pack a credit, underwriting or sustainability reviewer can follow end to end.',
            includes: [
                'Every hazard screened for this site, with its level and evidence status',
                'The dataset behind each figure, with version and date range covered',
                'Declared gaps — where data is missing, the pack says so',
                'Methodology, engine version and the reproducibility ID',
                'Delivered as a PDF in your account, plus the evidence annex'
            ],
            subject: 'Decision-ready evidence pack (€19)'
        },
        scientific: {
            title: 'Scientific / technical evidence pack',
            priceKey: 'report_scientific',
            fallbackPrice: '€39',
            lead: 'One location, full depth — for reviewers who need the method, not just the number.',
            includes: [
                'Everything in the decision pack',
                'Full methods, parameters and the daily time series behind each level',
                'Complete provenance table (source, version, retrieval date, limitations)',
                'Fire-danger grid and the historical event record for the location',
                'Reproducibility ID so a third party can re-run the analysis'
            ],
            subject: 'Scientific evidence pack (€39)'
        }
    };

    var TIER_COPY = {
        professional: {
            title: 'Professional subscription',
            priceKey: 'professional_monthly',
            fallbackPrice: '€49',
            lead: 'For practitioners who need this repeatedly — portfolios, monitoring and API access.',
            includes: [
                'All report types with full provenance, unlimited',
                'Portfolios and multi-location monitoring',
                'API key, Python/JS SDKs and the QGIS plugin',
                '25 saved locations and 25 alert rules'
            ],
            subject: 'Professional subscription enquiry'
        },
        business: {
            title: 'Business subscription',
            priceKey: 'business_monthly',
            fallbackPrice: '€249',
            lead: 'For teams: shared workspace, more locations, scheduled reporting.',
            includes: [
                'Everything in Professional, for 5 seats',
                'Up to 100 monitored locations and team dashboards',
                'Scheduled and custom reports (report builder)',
                'Priority support'
            ],
            subject: 'Business subscription enquiry'
        }
    };

    /* ------------------------------------------------------------------ */
    /* tiny helpers (no dependency on js/api.js)                           */
    /* ------------------------------------------------------------------ */

    function getJSON(path) {
        return fetch(API + path, { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            });
    }

    function postJSON(path, payload) {
        return fetch(API + path, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (r) {
            return r.json().catch(function () { return {}; })
                .then(function (body) { return { ok: r.ok, status: r.status, body: body }; });
        });
    }

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function readStore(key) {
        try { return JSON.parse(localStorage.getItem(key) || 'null'); }
        catch (e) { return null; }
    }

    function writeStore(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ }
    }

    function mailto(subject, body) {
        return 'mailto:' + CONTACT +
            '?subject=' + encodeURIComponent(subject) +
            (body ? '&body=' + encodeURIComponent(body) : '');
    }

    /* ------------------------------------------------------------------ */
    /* state                                                              */
    /* ------------------------------------------------------------------ */

    var state = { enabled: false, products: {}, loaded: false };

    function priceLabel(spec) {
        var p = state.products[spec.priceKey] || {};
        var amount = p.amount_eur;
        if (amount === undefined || amount === null || amount === '') {
            return spec.fallbackPrice;
        }
        return '€' + amount;
    }

    function loadBilling() {
        if (state.loaded) return Promise.resolve(state);
        return getJSON('/v2/billing/config').then(function (body) {
            state.enabled = !!body.billing_enabled;
            state.products = body.products || {};
            state.loaded = true;
            return state;
        }).catch(function () {
            state.enabled = false;
            state.loaded = true;
            return state;
        });
    }

    /* ------------------------------------------------------------------ */
    /* rendering                                                          */
    /* ------------------------------------------------------------------ */

    function render(mount) {
        if (mount.dataset.buyRendered === '1') return;
        mount.dataset.buyRendered = '1';

        var reportKind = mount.getAttribute('data-buy-report');
        var tier = mount.getAttribute('data-buy-tier');
        var interval = mount.getAttribute('data-buy-interval') || 'monthly';
        var context = mount.getAttribute('data-buy-context') || 'site';
        var spec = reportKind ? REPORT_COPY[reportKind] : TIER_COPY[tier];
        if (!spec) return;

        mount.classList.add('buy-panel');
        mount.innerHTML = '';

        var head = el('div', 'buy-head');
        head.appendChild(el('span', 'chip chip-observed', 'Buy directly'));
        head.appendChild(el('h2', null, spec.title));
        mount.appendChild(head);

        var price = el('p', 'buy-price', priceLabel(spec) +
            (reportKind ? ' · one location, one-off' : ' / month'));
        price.setAttribute('data-buy-price', spec.priceKey);
        mount.appendChild(price);

        mount.appendChild(el('p', 'buy-lead', spec.lead));

        var list = el('ul', 'buy-includes');
        spec.includes.forEach(function (item) { list.appendChild(el('li', null, item)); });
        mount.appendChild(list);

        var steps = el('ol', 'buy-steps');
        [
            'Create a free account (about a minute) — needed to deliver and store your pack.',
            'Pay securely by card. We never see your card details.',
            'Your pack is generated for your location and appears in your account.'
        ].forEach(function (s) { steps.appendChild(el('li', null, s)); });
        mount.appendChild(steps);

        var actions = el('div', 'buy-actions');
        var buyBtn = el('button', 'btn-action', 'Buy ' + priceLabel(spec) + ' — ' + spec.title);
        buyBtn.type = 'button';
        buyBtn.setAttribute('data-buy-go', '1');
        actions.appendChild(buyBtn);

        var invoice = el('a', 'text-link', 'Prefer an invoice? Email us');
        invoice.href = mailto(spec.subject, invoiceBody(spec, mount));
        actions.appendChild(invoice);
        mount.appendChild(actions);

        var status = el('div', 'buy-status');
        status.setAttribute('role', 'status');
        mount.appendChild(status);

        var honest = el('p', 'muted small buy-honest',
            'Screening-level evidence, not assurance, not actuarial pricing, ' +
            'not legal or investment advice. Loss is never quantified. ' +
            'Card payments are processed by Stripe; the receipt comes by email.');
        mount.appendChild(honest);

        buyBtn.addEventListener('click', function () {
            onBuy(buyBtn, status, { kind: reportKind, tier: tier, interval: interval,
                                    context: context, mount: mount });
        });
    }

    function invoiceBody(spec, mount) {
        var loc = currentLocation(mount);
        return [
            'Hello Talaix,',
            '',
            'I would like to order: ' + spec.title + ' (' + priceLabel(spec) + ').',
            loc ? 'Location(s) to analyse: ' + loc : 'Location(s) to analyse: ',
            '',
            'Please send an invoice and payment instructions.',
            '',
            'Organisation:',
            'VAT / billing details:'
        ].join('\n');
    }

    function currentLocation(mount) {
        var id = mount.getAttribute('data-buy-location-input');
        if (!id) return '';
        var input = document.getElementById(id);
        var value = input && input.value ? input.value.trim() : '';
        if (!value) {
            var stored = readStore(LOCATION_KEY);
            if (stored && stored.value) value = stored.value;
        }
        return value;
    }

    function status(statusEl, kind, msg) {
        statusEl.innerHTML = '';
        if (!msg) return;
        var box = el('div', 'notice notice-' + kind, msg);
        statusEl.appendChild(box);
    }

    /* ------------------------------------------------------------------ */
    /* the purchase itself                                                */
    /* ------------------------------------------------------------------ */

    function rememberIntent(intent, locationValue) {
        writeStore(INTENT_KEY, intent);
        if (locationValue) writeStore(LOCATION_KEY, { value: locationValue });
    }

    function onBuy(btn, statusEl, ctx) {
        var locationValue = currentLocation(ctx.mount);
        var intent = { kind: ctx.kind, tier: ctx.tier, interval: ctx.interval,
                       context: ctx.context };
        rememberIntent(intent, locationValue);

        if (!state.enabled) {
            status(statusEl, 'warn',
                'Card checkout is not enabled on this deployment yet — ' +
                'email us and we will invoice you and deliver the pack manually.');
            return;
        }

        btn.disabled = true;
        status(statusEl, 'info', 'Checking your session…');

        /* Guest path: explain, then send them to sign in *with the intent kept*. */
        getJSON('/v2/account').then(function () {
            startCheckout(btn, statusEl, ctx);
        }).catch(function () {
            btn.disabled = false;
            status(statusEl, 'warn',
                'Purchases are delivered to your account, so we need a quick free ' +
                'sign-in first — we keep your choice and location, and bring you ' +
                'straight back here.');
            var back = location.pathname.split('/').pop() || 'index.html';
            setTimeout(function () {
                location.href = 'account.html?reason=signin&next=' +
                    encodeURIComponent(back) + '&buy=1';
            }, 1400);
        });
    }

    function startCheckout(btn, statusEl, ctx) {
        var url, payload;
        if (ctx.kind) {
            url = '/v2/billing/checkout/report';
            payload = { kind: ctx.kind };
        } else {
            url = '/v2/billing/checkout';
            payload = { tier: ctx.tier, interval: ctx.interval };
        }
        status(statusEl, 'info', 'Starting secure checkout…');
        postJSON(url, payload).then(function (res) {
            btn.disabled = false;
            if (res.status === 401) {
                status(statusEl, 'warn', 'Please sign in first — we kept your selection.');
                return;
            }
            if (!res.ok) {
                status(statusEl, 'error',
                    (res.body && res.body.error) || 'Checkout could not start.');
                return;
            }
            if (res.body && res.body.url) {
                location.href = res.body.url;
                return;
            }
            status(statusEl, 'error', 'Checkout did not return a payment link.');
        }).catch(function () {
            btn.disabled = false;
            status(statusEl, 'error', 'Checkout request failed — please try again or email us.');
        });
    }

    /* ------------------------------------------------------------------ */
    /* boot                                                               */
    /* ------------------------------------------------------------------ */

    function init() {
        var mounts = document.querySelectorAll('[data-buy-report], [data-buy-tier]');
        if (!mounts.length) return;
        loadBilling().then(function () {
            Array.prototype.forEach.call(mounts, render);
        });
    }

    window.HSBuy = {
        init: init,
        loadBilling: loadBilling,
        _state: state,
        _copy: { reports: REPORT_COPY, tiers: TIER_COPY },
        INTENT_KEY: INTENT_KEY,
        LOCATION_KEY: LOCATION_KEY
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
