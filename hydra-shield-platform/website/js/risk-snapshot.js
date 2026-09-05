/* Talaix — public wildfire risk intelligence bar.
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

    /* Homepage shows only the top entries; the full ranking lives on the
     * live map/dashboard. */
    var MAX_ENTRIES = 5;

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

    /* Multi-hazard board: one row per hazard with its top monitored areas,
     * each linked to the live map. Levels stay labelled as screening
     * indicators — the basis text comes from the hazard module itself. */
    function renderHazardBoard(multi) {
        var board = el('hazardBoard');
        if (!board) return;
        var hazards = (multi && multi.hazards) || [];
        if (!multi || multi.status !== 'ok' || !hazards.length) {
            board.innerHTML = '';
            return;
        }
        var rows = hazards.map(function (h) {
            if (!h.entries || !h.entries.length) {
                return '<div class="hazard-board-row">' +
                    '<span class="hazard-board-name">' + esc(h.name) + '</span>' +
                    '<span class="hazard-board-empty">No elevated reading at the monitored areas right now.</span>' +
                    '</div>';
            }
            var chips = h.entries.map(function (e) {
                var score = (e.level_score === null || e.level_score === undefined)
                    ? ''
                    : ' <b>' + esc(Number(e.level_score).toFixed(0)) +
                      (e.level_score_max ? '/' + esc(Number(e.level_score_max).toFixed(0)) : '') + '</b>';
                return '<a class="hazard-chip" href="map.html?hazard=' + encodeURIComponent(h.hazard) +
                    '&location=' + encodeURIComponent(e.latitude + ',' + e.longitude) + '">' +
                    '<span class="hazard-chip-level">' + esc(e.level_label || '—') + '</span> ' +
                    esc(e.name) + score + '</a>';
            }).join('');
            return '<div class="hazard-board-row">' +
                '<span class="hazard-board-name">' + esc(h.name) + '</span>' +
                '<span class="hazard-board-chips">' + chips + '</span></div>';
        }).join('');
        board.innerHTML =
            '<div class="hazard-board-title">All hazards at the monitored areas — live levels</div>' +
            rows +
            '<div class="risk-intel-disclaimer">' +
            esc((multi.model && multi.model.note) ||
                'Levels are screening indicators from real analyses, not validated local ratings.') +
            '</div>';
    }

    function render(snap) {
        var scopeEl = el('riskIntelScope');
        if (snap.scope) scopeEl.textContent = snap.scope;
        scopeEl.title = 'The ranking covers only the areas Talaix is configured to monitor.';

        el('riskIntelFreshness').textContent = fmtAgo(snap.generated_at);

        var rows = (snap.entries || []).slice(0, MAX_ENTRIES).map(function (e, idx) {
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

            // "Why?" expander: factor levels from the real model inputs.
            var whyId = 'riskWhy' + idx;
            var whyBtn = '';
            var whyBlock = '';
            if (e.factors && e.factors.length) {
                whyBtn = '<button type="button" class="risk-why-btn" data-target="' + whyId + '">Why?</button>';
                whyBlock = '<div class="risk-why" id="' + whyId + '" hidden>' +
                    e.factors.map(function (f) {
                        var val = (f.value === null || f.value === undefined) ? ''
                            : ' <b>' + esc(f.value) + (f.unit ? ' ' + esc(f.unit) : '') + '</b>';
                        var lvl = f.level ? ' <span class="risk-lvl risk-lvl-' + f.level_rank + '">' +
                            esc(f.level) + '</span>' : '';
                        return '<span class="risk-factor">' + esc(f.label) + ':' + val + lvl + '</span>';
                    }).join('') +
                    (e.top_recommendation && e.top_recommendation.what
                        ? '<div class="risk-why-rec">→ ' + esc(e.top_recommendation.what) +
                          ' <span class="risk-lvl risk-lvl-prio">' + esc(e.top_recommendation.priority) + '</span></div>'
                        : '') +
                    '</div>';
            }

            return '<div class="risk-intel-item">' +
                '<div class="risk-intel-row">' +
                '<span class="risk-intel-rank">' + esc(e.rank) + '.</span>' +
                '<span class="risk-intel-name">' + esc(e.name) + '</span>' +
                '<span class="risk-badge risk-badge-' + esc(e.risk_class) + '">' +
                    esc((e.risk_class || '').toUpperCase()) + '</span>' +
                '<span class="risk-intel-score">' + esc(Number(e.risk).toFixed(0)) + '</span>' +
                '<span class="risk-intel-detail">' + detail.join(' · ') + '</span>' +
                whyBtn +
                '</div>' + whyBlock + '</div>';
        });

        el('riskIntelList').innerHTML = rows.length
            ? rows.join('')
            : '<div class="risk-intel-unavailable">No monitored area has a computable real risk score right now.</div>';

        var disclaimer = (snap.model && snap.model.disclaimer) ||
            (snap.entries && snap.entries[0] && snap.entries[0].score_disclaimer);
        var sourcesHtml = '';
        if (snap.sources && snap.sources.length) {
            sourcesHtml = 'Data sources: ' + snap.sources.map(function (s) {
                return s.url
                    ? '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.name) + '</a>'
                    : esc(s.name);
            }).join(' · ');
        }
        el('riskIntelSources').innerHTML = sourcesHtml +
            (disclaimer ? '<div class="risk-intel-disclaimer">' + esc(disclaimer) + '</div>' : '');

        // Wire the "Why?" expanders.
        Array.prototype.forEach.call(document.querySelectorAll('.risk-why-btn'), function (btn) {
            btn.addEventListener('click', function () {
                var block = document.getElementById(btn.getAttribute('data-target'));
                if (block) block.hidden = !block.hidden;
            });
        });
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
                    renderHazardBoard(snap.multi_hazard);
                } else {
                    renderUnavailable(snap.message);
                    renderHazardBoard(snap.multi_hazard);
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
