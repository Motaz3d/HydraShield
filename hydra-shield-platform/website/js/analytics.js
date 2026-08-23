/* Talaix — first-party product analytics beacon (privacy-conscious).
 *
 * What this is: a tiny first-party event sender for product questions
 * (which pages/hazards/solutions are used, where the funnel converts).
 *
 * What it is NOT: no third-party tracker, no cookies, no fingerprinting,
 * no cross-site anything. Data goes only to this site's own API.
 *
 * Privacy rules (docs/PRODUCT_ANALYTICS.md):
 * - Pseudonymous session id generated locally, kept in localStorage; the
 *   server stores only its HMAC hash.
 * - Do Not Track is honoured: with DNT enabled nothing is sent.
 * - Coordinates are rounded to 1 decimal (~11 km) before sending.
 * - Referrer is reduced to origin + path (query strings are stripped).
 * - Nothing here collects names, emails, phone numbers or free text.
 */
(function () {
    'use strict';

    var DNT = navigator.doNotTrack === '1' || window.doNotTrack === '1';

    var API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8051/api'
        : '/api';

    function sessionId() {
        try {
            var sid = localStorage.getItem('hs_sid');
            if (!sid) {
                var buf = new Uint8Array(16);
                (window.crypto || window.msCrypto).getRandomValues(buf);
                sid = Array.prototype.map.call(buf, function (b) {
                    return ('0' + b.toString(16)).slice(-2);
                }).join('');
                localStorage.setItem('hs_sid', sid);
            }
            return sid;
        } catch (e) {
            return null; // storage unavailable — events go without a session id
        }
    }

    function deviceCategory() {
        var ua = navigator.userAgent || '';
        if (/Mobi|Android|iPhone|iPad/i.test(ua)) {
            return /iPad|Tablet/i.test(ua) ? 'tablet' : 'mobile';
        }
        return 'desktop';
    }

    function coarseReferrer() {
        try {
            if (!document.referrer) return null;
            var u = new URL(document.referrer);
            return (u.origin + u.pathname).slice(0, 200);
        } catch (e) {
            return null;
        }
    }

    function roundCoord(v) {
        var n = parseFloat(v);
        if (!isFinite(n)) return undefined;
        return Math.round(n * 10) / 10;
    }

    /* track(event, props) — whitelisted server-side; unknown fields dropped. */
    function track(event, props) {
        if (DNT) return;
        props = props || {};
        var payload = {
            event: event,
            session_id: sessionId(),
            page: location.pathname.replace(/^\//, '') || 'index.html',
            device: deviceCategory(),
            language: navigator.language || null,
            referrer: coarseReferrer()
        };
        if (props.hazard) payload.hazard = String(props.hazard).slice(0, 40);
        if (props.feature) payload.feature = String(props.feature).slice(0, 120);
        if (props.lat !== undefined) payload.lat = roundCoord(props.lat);
        if (props.lon !== undefined) payload.lon = roundCoord(props.lon);

        var body = JSON.stringify(payload);
        try {
            if (navigator.sendBeacon) {
                var blob = new Blob([body], { type: 'application/json' });
                if (navigator.sendBeacon(API + '/v2/analytics/event', blob)) return;
            }
            fetch(API + '/v2/analytics/event', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body,
                keepalive: true,
                credentials: 'omit'
            }).catch(function () { /* analytics must never break the page */ });
        } catch (e) { /* ignore */ }
    }

    // Expose for page scripts (HS namespace exists on platform pages).
    window.HS = window.HS || {};
    window.HS.track = track;

    if (!DNT) track('page_view');
})();
