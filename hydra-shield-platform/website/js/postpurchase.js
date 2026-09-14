/* Talaix — post-purchase and interrupted-purchase handling.
 *
 * The Stripe checkout flow already redirects back to account.html with
 * query flags (purchased=report, subscribed=1, checkout=cancelled) — but
 * nothing on the site reacted to them, so a buyer who had just paid landed
 * on a plain account page with no confirmation, no next step and no way to
 * collect what they bought. This module closes that loop, and also resumes
 * a purchase that was interrupted by the sign-in step.
 *
 * Loaded by account.html only. Reads the flags, never invents a payment:
 * it reports exactly what the URL says, and if the flag is absent it does
 * nothing at all.
 */
(function () {
    'use strict';

    var INTENT_KEY = 'hs_buy_intent';
    var LOCATION_KEY = 'hs_buy_location';

    var LABELS = {
        decision: 'decision-ready evidence pack (€19)',
        scientific: 'scientific / technical evidence pack (€39)',
        professional: 'Professional subscription',
        business: 'Business subscription'
    };

    function readStore(key) {
        try { return JSON.parse(localStorage.getItem(key) || 'null'); }
        catch (e) { return null; }
    }

    function clearIntent() {
        try {
            localStorage.removeItem(INTENT_KEY);
            localStorage.removeItem(LOCATION_KEY);
        } catch (e) { /* ignore */ }
    }

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function panel(id) {
        var existing = document.getElementById(id);
        if (existing) return existing;
        var anchor = document.getElementById('statusArea');
        var node = el('div', 'panel postpurchase');
        node.id = id;
        if (anchor && anchor.parentNode) {
            anchor.parentNode.insertBefore(node, anchor.nextSibling);
        } else {
            var main = document.querySelector('main .container') || document.body;
            main.insertBefore(node, main.firstChild);
        }
        return node;
    }

    function storedLocation() {
        var stored = readStore(LOCATION_KEY);
        return (stored && stored.value) ? stored.value : '';
    }

    function intentLabel() {
        var intent = readStore(INTENT_KEY);
        if (!intent) return '';
        if (intent.kind && LABELS[intent.kind]) return LABELS[intent.kind];
        if (intent.tier && LABELS[intent.tier]) return LABELS[intent.tier];
        return '';
    }

    /* ---------------------------------------------------------------- */

    function renderSignInNotice(params) {
        var label = intentLabel();
        if (!label) return;
        var box = panel('buyResume');
        var h = el('h2', null, 'Your purchase is waiting');
        h.style.marginTop = '0';
        box.appendChild(h);

        var p = el('p', null,
            'You were buying the ' + label + '. Purchases are delivered to your ' +
            'account, so sign in (or create a free account) below — your choice ' +
            'and your location are kept.');
        box.appendChild(p);

        var loc = storedLocation();
        if (loc) {
            box.appendChild(el('p', 'muted small', 'Location kept: ' + loc));
        }

        var actions = el('div', 'card-actions');
        var next = params.get('next');
        if (next) {
            var back = el('a', 'btn-action btn-quiet', 'Back to where I was');
            back.href = next + '#buy';
            actions.appendChild(back);
        }
        box.appendChild(actions);
    }

    function renderPurchased() {
        var box = panel('buyComplete');
        var h = el('h2', null, 'Payment received — thank you');
        h.style.marginTop = '0';
        box.appendChild(h);

        var label = intentLabel();
        box.appendChild(el('p', null,
            'Your ' + (label || 'report purchase') + ' is confirmed. Your card ' +
            'receipt is sent by email by our payment processor.'));

        var loc = storedLocation();
        box.appendChild(el('p', null,
            loc
                ? 'Generate the pack for your location now — it is pre-filled:'
                : 'Generate your pack now and enter the location to analyse:'));

        var actions = el('div', 'card-actions');
        var go = el('a', 'btn-action', 'Generate my evidence pack');
        go.href = loc
            ? 'reports.html?location=' + encodeURIComponent(loc) + '#builder'
            : 'reports.html#builder';
        actions.appendChild(go);
        var all = el('a', 'btn-action btn-quiet', 'All report types');
        all.href = 'reports.html';
        actions.appendChild(all);
        box.appendChild(actions);

        box.appendChild(el('p', 'muted small',
            'A pack you cannot generate immediately — portfolio scope, extra ' +
            'locations, custom annexes — is delivered by us within one business day. ' +
            'Reply to your receipt email and we take it from there.'));
    }

    function renderSubscribed() {
        var box = panel('buyComplete');
        var h = el('h2', null, 'Subscription active');
        h.style.marginTop = '0';
        box.appendChild(h);
        box.appendChild(el('p', null,
            'Your subscription is live. Higher rate limits, saved locations, ' +
            'portfolios and API access are enabled on this account.'));

        var actions = el('div', 'card-actions');
        var a1 = el('a', 'btn-action', 'Open reports');
        a1.href = 'reports.html';
        actions.appendChild(a1);
        var a2 = el('a', 'btn-action btn-quiet', 'Map & monitoring');
        a2.href = 'map.html';
        actions.appendChild(a2);
        box.appendChild(actions);

        box.appendChild(el('p', 'muted small',
            'Manage or cancel the subscription any time from the billing portal ' +
            'on this page.'));
    }

    function renderCancelled() {
        var box = panel('buyComplete');
        var h = el('h2', null, 'Checkout cancelled — nothing was charged');
        h.style.marginTop = '0';
        box.appendChild(h);
        box.appendChild(el('p', null,
            'No payment was taken. Your selection was kept, so you can pick it ' +
            'up again whenever you are ready.'));
        var actions = el('div', 'card-actions');
        var a = el('a', 'btn-action btn-quiet', 'See pricing');
        a.href = 'pricing.html';
        actions.appendChild(a);
        box.appendChild(actions);
    }

    /* ---------------------------------------------------------------- */

    function init() {
        var params = new URLSearchParams(location.search);
        if (params.get('purchased') === 'report') {
            renderPurchased();
            clearIntent();
            return;
        }
        if (params.get('subscribed') === '1') {
            renderSubscribed();
            clearIntent();
            return;
        }
        if (params.get('checkout') === 'cancelled') {
            renderCancelled();
            return;
        }
        if (params.get('reason') === 'signin' || params.get('buy') === '1') {
            renderSignInNotice(params);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
