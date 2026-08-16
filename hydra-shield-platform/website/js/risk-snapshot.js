/* HydraShield — public wildfire risk intelligence bar.
 *
 * Fetches GET /api/risk-snapshot (real, cached analyses of the configured
 * monitored areas) and renders a compact ranking on the homepage. When the
 * snapshot cannot be produced from real data the bar says so honestly —
 * it never displays placeholder or invented values.
 */
(function () {
    'use strict';

    var API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8051/api'
        : '/api';

    var RETRY_MS = 30000;
    var retried = false;

    function el(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function fmtAgo(iso) {
        var t = Date.parse(iso);
        if (isNaN(t)) return '';
        var mins = Math.max(0, Math.round((Date.now() - t) / 60000));
        if (mins < 1) return 'Updated just now';
        if (mins === 1) return 'Updated 1 min ago';
        if (mins < 60) return 'Updated ' + mins + ' min ago';
        var h = Math.round(mins / 60);
        return 'Updated ' + h + (h === 1 ? ' hour ago' : ' hours ago');
    }

    function trendLabel(t) {
        return { rising: 'Rising', falling: 'Falling', steady: 'Steady' }[t] || null;
    }

    function renderUnavailable(message) {
        el('riskIntelList').innerHTML =
            '<div class="risk-intel-unavailable">' +
            '<strong>Risk snapshot temporarily unavailable.</strong><br>' +
            esc(message || 'Current monitored-area data could not be retrieved. ') +
            ' You can still run a live analysis for any location below.' +
            '</div>';
        el('riskIntelSources').textContent = '';
    }

    function render(snap) {
        var scopeEl = el('riskIntelScope');
        if (snap.scope) scopeEl.textContent = snap.scope;
        scopeEl.title = 'The ranking covers only the areas HydraShield is configured to monitor.';

        el('riskIntelFreshness').textContent = fmtAgo(snap.generated_at);

        var rows = (snap.entries || []).map(function (e) {
            var detail = [];
            if (e.fwi !== null && e.fwi !== undefined) {
                detail.push('FWI ' + Number(e.fwi).toFixed(1) +
                    (e.fwi_date ? ' · ' + esc(e.fwi_date) : ''));
            }
            var trend = trendLabel(e.trend);
            if (trend) detail.push(trend);
            if (e.active_fires && typeof e.active_fires.count === 'number') {
                detail.push(e.active_fires.count + ' active fire' +
                    (e.active_fires.count === 1 ? '' : 's') +
                    ' (' + e.active_fires.days + ' d)');
            }
            if (e.satellite_date) detail.push('Satellite: ' + esc(e.satellite_date));

            return '<div class="risk-intel-row">' +
                '<span class="risk-intel-rank">' + esc(e.rank) + '.</span>' +
                '<span class="risk-intel-name">' + esc(e.name) + '</span>' +
                '<span class="risk-badge risk-badge-' + esc(e.risk_class) + '">' +
                    esc((e.risk_class || '').toUpperCase()) + '</span>' +
                '<span class="risk-intel-score">' + esc(Number(e.risk).toFixed(0)) + '</span>' +
                '<span class="risk-intel-detail">' + detail.join(' · ') + '</span>' +
                '</div>';
        });

        el('riskIntelList').innerHTML = rows.length
            ? rows.join('')
            : '<div class="risk-intel-unavailable">No monitored area has a computable real risk score right now.</div>';

        if (snap.sources && snap.sources.length) {
            el('riskIntelSources').innerHTML = 'Data sources: ' + snap.sources.map(function (s) {
                return s.url
                    ? '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.name) + '</a>'
                    : esc(s.name);
            }).join(' · ');
        } else {
            el('riskIntelSources').textContent = '';
        }
    }

    function load() {
        fetch(API + '/risk-snapshot')
            .then(function (r) {
                return r.json().then(function (body) { return { ok: r.ok, body: body }; });
            })
            .then(function (res) {
                var snap = res.body || {};
                if (res.ok && snap.status === 'ok') {
                    render(snap);
                } else {
                    renderUnavailable(snap.message);
                    if (!retried) { retried = true; setTimeout(load, RETRY_MS); }
                }
            })
            .catch(function () {
                renderUnavailable('The risk snapshot service could not be reached.');
                if (!retried) { retried = true; setTimeout(load, RETRY_MS); }
            });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', load);
    } else {
        load();
    }
})();
