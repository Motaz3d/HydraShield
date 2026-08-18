/* HydraShield — Economic Intelligence (economy.html).
 *
 * Location (+ optional radius + hazard context) →
 *   GET /api/v2/economy?lat&lon&radius_km&hazard=
 *
 * Renders the exposure category table (counts + source + caveat chips),
 * the monetary not-quantified statement prominently (a deliberate answer,
 * never a broken-looking number), the framework slots with their honest
 * labels, and the hazard context block when requested.
 *
 * Endpoints used:
 *   GET /api/v2/hazards            (hazard-context selector)
 *   GET /api/analyze?location=…    (place-name geocoding)
 *   GET /api/v2/economy            (exposure profile)
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function loadHazards() {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) return;
            var sel = el('hazardSelect');
            res.body.hazards.forEach(function (h) {
                if (!h.analysis.available) return;
                var opt = document.createElement('option');
                opt.value = h.id;
                opt.textContent = h.name;
                sel.appendChild(opt);
            });
        }).catch(function () { /* selector stays "None" — honestly optional */ });
    }

    function renderStatus(kind, html) {
        el('statusArea').innerHTML = '<div class="notice notice-' + kind + '">' + html + '</div>';
    }

    function search() {
        var q = el('locInput').value.trim();
        if (!q) {
            renderStatus('error', 'Enter a location — a place name or lat,lon coordinates.');
            return;
        }
        el('searchBtn').disabled = true;
        el('economyArea').innerHTML = '';
        renderStatus('info', 'Resolving location…');

        HS.resolveLocation(q).then(function (loc) {
            if (!loc.ok) {
                el('searchBtn').disabled = false;
                renderStatus('error', esc(loc.error || 'Location could not be resolved.'));
                return;
            }
            HS.rememberLocation({ name: loc.name, lat: loc.lat, lon: loc.lon });
            renderStatus('info', 'Building the exposure profile for ' + esc(loc.name) + '…');
            var radius = parseFloat(el('radiusInput').value) || 5;
            var hazard = el('hazardSelect').value;
            var url = API + '/v2/economy?lat=' + loc.lat.toFixed(4) +
                '&lon=' + loc.lon.toFixed(4) + '&radius_km=' + encodeURIComponent(radius) +
                (hazard ? '&hazard=' + encodeURIComponent(hazard) : '');
            return fetchJSON(url).then(function (res) {
                el('searchBtn').disabled = false;
                renderEconomy(res.body || {}, res.ok, loc);
            });
        }).catch(function () {
            el('searchBtn').disabled = false;
            renderStatus('error', 'The economy service could not be reached.');
        });
    }

    function categoryRows(categories) {
        return Object.keys(categories).map(function (name) {
            var c = categories[name] || {};
            var status = c.status || 'not_mapped';
            var count = (c.count !== null && c.count !== undefined) ? c.count : null;
            var detail = [];
            if (c.proxy_basis) detail.push(c.proxy_basis);
            if (c.reason) detail.push(c.reason);
            if (c.description) detail.push(c.description);
            if (c.breakdown) {
                detail.push(Object.keys(c.breakdown).map(function (k) {
                    return k.replace(/_/g, ' ') + ': ' + c.breakdown[k];
                }).join(', '));
            }
            if (c.major_roads_mapped !== undefined) {
                detail.push('of which major: ' + c.major_roads_mapped);
            }
            if (c.buildings_mapped !== undefined && status === 'proxy') {
                detail.push('buildings mapped: ' + c.buildings_mapped);
            }
            return '<tr>' +
                '<td><strong>' + esc(name.replace(/_/g, ' ')) + '</strong></td>' +
                '<td>' + chip(status, status.replace(/_/g, ' ').toUpperCase()) + '</td>' +
                '<td>' + (count !== null ? esc(count) : '—') + '</td>' +
                '<td class="muted small">' + (detail.length ? detail.map(esc).join('<br>') : '—') + '</td>' +
                '<td class="muted small">' + esc(c.source || '—') +
                (c.completeness_caveat ? '<br><span style="color:#b45309;">' + esc(c.completeness_caveat) + '</span>' : '') +
                '</td></tr>';
        }).join('');
    }

    function renderEconomy(body, ok, loc) {
        var area = el('economyArea');
        if (!ok || body.error) {
            renderStatus('error', 'Exposure profile unavailable: ' + esc(body.error || 'request failed'));
            return;
        }

        renderStatus('info', 'Exposure profile for ' + esc(loc.name) + ' · ' +
            esc(body.radius_km) + ' km radius · ' + esc(body.analysis_window || 'current conditions') + '.');

        if (window.HSConvert) HSConvert.show({
            mount: 'statusArea', context: 'economy_save',
            text: 'This exposure profile is computed live — save it and monitor this place with a free account.',
            cta: 'Save this exposure profile', href: 'account.html'
        });

        var html = '';

        // ---- Exposure categories ------------------------------------------
        var categories = body.exposure || {};
        if (Object.keys(categories).length) {
            html += '<div class="panel"><h2>Exposure categories</h2>' +
                '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Category</th><th>Status</th><th>Count</th><th>Basis / notes</th><th>Source &amp; caveats</th>' +
                '</tr></thead><tbody>' +
                categoryRows(categories) +
                '</tbody></table></div></div>';
        }

        // ---- Monetary quantification: a deliberate answer, not a gap ------
        var mon = body.monetary_quantification || {};
        if (mon.statement || mon.status) {
            html += '<div class="panel" style="border-left:4px solid var(--accent);">' +
                '<h2>Monetary quantification ' +
                chip(mon.status || 'not_quantified', (mon.status || 'not_quantified').replace(/_/g, ' ').toUpperCase()) +
                '</h2>' +
                '<p style="font-size:1.05rem;margin:6px 0;"><strong>' + esc(mon.statement || '') + '</strong></p>' +
                (mon.note ? '<p class="muted" style="margin:0;">' + esc(mon.note) + '</p>' : '') +
                '<p class="muted small" style="margin-top:8px;">This is a declared answer, not a missing ' +
                'value: HydraShield does not fabricate losses, premiums or valuations.</p>' +
                '</div>';
        }

        // ---- Framework slots ------------------------------------------------
        var fw = body.framework || {};
        var fwKeys = Object.keys(fw);
        if (fwKeys.length) {
            html += '<div class="panel"><h2>Framework slots</h2>' +
                '<p class="muted small">Declared analytical slots with their current, honest fill state — ' +
                'framework slots are never populated with invented content.</p>' +
                '<div class="table-scroll"><table class="kv-table">' +
                fwKeys.map(function (k) {
                    return '<tr><th>' + esc(k.replace(/_/g, ' ')) + '</th><td>' + esc(fw[k]) + '</td></tr>';
                }).join('') + '</table></div></div>';
        }

        // ---- Hazard context --------------------------------------------------
        var hc = body.hazard_context;
        if (hc && hc.status !== 'not_provided') {
            html += '<div class="panel"><h2>Hazard context</h2>';
            if (hc.status === 'unavailable') {
                html += '<div class="notice notice-warn">' + esc(hc.hazard || 'Hazard') +
                    ' context unavailable: ' + esc(hc.reason || hc.unavailable_reason || 'unknown reason') + '</div>';
            } else {
                html += '<div class="badge-row">' + chip(hc.status || 'ok', (hc.status || '').toUpperCase()) +
                    (hc.level && hc.level.label
                        ? '<span class="level-label level-' + esc(hc.level.label) + '">' + esc(hc.level.label.toUpperCase()) + '</span>'
                        : '') + '</div>';
                if (hc.summary) html += '<p style="margin-top:8px;">' + esc(hc.summary) + '</p>';
                if (hc.level && hc.level.basis) {
                    html += '<p class="muted small">' + esc(hc.level.basis) + '</p>';
                }
            }
            html += '</div>';
        }

        // ---- Provenance / evidence ------------------------------------------
        var prov = body.provenance || {};
        if (prov.source) {
            html += '<div class="panel"><h2>Provenance</h2>' +
                '<div class="table-scroll"><table class="kv-table">' +
                '<tr><th>Source</th><td>' + esc(prov.source) + '</td></tr>' +
                (prov.quality ? '<tr><th>Quality</th><td>' + esc(prov.quality) + '</td></tr>' : '') +
                (prov.limitations ? '<tr><th>Limitations</th><td>' + esc(prov.limitations) + '</td></tr>' : '') +
                '</table></div>';
            if (prov.evidence && prov.evidence.length) {
                html += '<details class="expander"><summary>Evidence records (' + prov.evidence.length + ')</summary>' +
                    prov.evidence.map(function (rec) {
                        return '<div class="sub-block"><div class="badge-row">' +
                            chip(rec.claim_status || 'UNKNOWN') + ' ' + chip(rec.temporal || 'OBSERVED') +
                            '</div><div style="margin-top:6px;"><strong>' + esc(rec.source || '') + '</strong>' +
                            (rec.dataset ? ' · ' + esc(rec.dataset) : '') + '</div>' +
                            '<div class="muted small">' +
                            [rec.method && 'Method: ' + rec.method,
                             rec.resolution && 'Resolution: ' + rec.resolution,
                             rec.limitations && 'Limitations: ' + rec.limitations]
                                .filter(Boolean).map(esc).join('<br>') + '</div></div>';
                    }).join('') + '</details>';
            }
            html += '</div>';
        }

        area.innerHTML = html;
    }

    function init() {
        loadHazards();
        el('searchBtn').addEventListener('click', search);
        el('locInput').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') search();
        });
        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q) {
            el('locInput').value = q;
            search();
        }
    }

    init();
})();
