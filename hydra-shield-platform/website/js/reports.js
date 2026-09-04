/* Talaix — Reports portal (reports.html).
 *
 * Builds generate-links for the classic three-type report flow:
 *   GET /api/report?lat&lon&type=simple|decision|scientific&history=1
 * (place names are passed as ?location=… — the endpoint geocodes through
 * the same real pipeline). No pre-fetching: the report endpoint runs the
 * real cached analysis itself and answers honestly when it cannot.
 */
(function () {
    'use strict';

    var esc = HS.esc, API = HS.API;

    var TYPES = [
        { id: 'simple', label: 'Simple report' },
        { id: 'decision', label: 'Decision-support report' },
        { id: 'scientific', label: 'Scientific report' }
    ];

    function el(id) { return document.getElementById(id); }

    function reportUrl(query, type) {
        var coords = HS.parseLatLon(query);
        var base = coords
            ? API + '/report?lat=' + coords.lat + '&lon=' + coords.lon
            : API + '/report?location=' + encodeURIComponent(query);
        return base + '&type=' + type + '&history=1';
    }

    function refresh() {
        var q = el('legacyLocInput').value.trim();
        var actions = el('legacyReportActions');
        var status = el('legacyReportStatus');
        if (!q) {
            actions.innerHTML = '<span class="muted small">Enter a location, then choose a report type below.</span>';
            status.textContent = '';
            return;
        }
        actions.innerHTML = TYPES.map(function (t) {
            return '<a class="btn-action" href="' + esc(reportUrl(q, t.id)) +
                '" target="_blank" rel="noopener">' + esc(t.label) + ' (PDF)</a>';
        }).join('');
        actions.querySelectorAll('a').forEach(function (a, i) {
            a.addEventListener('click', function () {
                if (window.HSConvert) HSConvert.trackAction('report_generated',
                    { feature: TYPES[i].id });
                else if (window.HS && HS.track) HS.track('report_generated',
                    { feature: TYPES[i].id });
            });
        });
        if (window.HSConvert) HSConvert.show({
            mount: 'legacyReportStatus', context: 'report_account',
            text: 'Reports are free — with an account you keep the full history and can monitor the location.',
            cta: 'Keep my reports', href: 'account.html'
        });
        if (window.HSConvert) HSConvert.evaluate('legacyReportStatus');
        status.textContent = 'Links open the live report endpoint in a new tab. ' +
            'Generation runs the real analysis and can take a minute on a first request; ' +
            'when data is unavailable the endpoint says so instead of rendering invented content.';
    }

    function init() {
        if (window.HS && HS.location) HS.location.enhance('legacyLocInput', 'locAssist');
        el('legacyLocInput').addEventListener('input', refresh);
        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q) {
            el('legacyLocInput').value = q;
        }
        refresh();
    }

    init();
})();
