/* Talaix — Map Check page (mapcheck.html).
 *
 * Cross-checks open map data against satellite observation and renders
 * per-check verdicts with possible causes, evidence details and honest
 * cannot-assess states.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function renderStatus(kind, html) {
        el('mapcheckStatus').innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function clearStatus() {
        el('mapcheckStatus').innerHTML = '';
    }

    function resultChip(result) {
        if (result === 'consistent') return chip('observed', 'consistent');
        if (result === 'discrepancy_detected') return chip('partial', 'discrepancy');
        return chip('unknown', 'cannot assess');
    }

    function renderFeatureSummary(summary) {
        var parts = [];
        if (summary.kind) parts.push(esc(summary.kind));
        if (summary.name) parts.push(esc(summary.name));
        if (summary.edit_year) parts.push('edited ' + esc(summary.edit_year));
        return '<span class="muted small">' + (parts.join(' · ') || 'feature') + '</span>';
    }

    function renderEvidence(evidence) {
        if (!evidence || !evidence.length) return '';
        var rows = evidence.map(function (rec) {
            var period = '—';
            if (rec.reference_period && (rec.reference_period.start || rec.reference_period.end)) {
                period = (rec.reference_period.start || '') + ' → ' + (rec.reference_period.end || '');
                period = period.replace(/^ → | → $/g, '');
            }
            var link = rec.link || rec.provider_url || '';
            return '<tr>' +
                '<td>' + esc(rec.source || '—') + '</td>' +
                '<td>' + esc(rec.dataset || '—') + '</td>' +
                '<td>' + esc(period) + '</td>' +
                '<td>' + chip(rec.claim_status) + '</td>' +
                '<td>' + (link
                    ? '<a class="text-link" href="' + esc(link) + '" target="_blank" rel="noopener">Source →</a>'
                    : '—') + '</td>' +
                '</tr>';
        }).join('');
        return '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Source</th><th>Dataset</th><th>Period</th><th>Status</th><th>Link</th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    }

    function renderCheck(c) {
        var mapLabel = c.id === 'green_mapped_vs_satellite' ? 'Map says' : 'Satellite shows';
        var satLabel = c.id === 'green_mapped_vs_satellite' ? 'Satellite shows' : 'Map says';

        var mapHtml = '';
        if (c.id === 'green_mapped_vs_satellite') {
            if ((c.map_claim.feature_summaries || []).length) {
                mapHtml = '<ul class="muted small">' +
                    c.map_claim.feature_summaries.map(function (s) {
                        return '<li>' + renderFeatureSummary(s) + '</li>';
                    }).join('') +
                    '</ul>';
            } else {
                mapHtml = '<p class="muted small">No mapped green features within the radius.</p>';
            }
        } else {
            mapHtml = '<p class="muted small">' +
                (c.satellite_observation.green_by_ndvi
                    ? 'NDVI = ' + esc(HS.fmt(c.satellite_observation.ndvi, '', 3)) + ' (green). '
                    : 'NDVI does not indicate green. ') +
                (c.satellite_observation.green_by_landcover
                    ? 'WorldCover = ' + esc(c.satellite_observation.landcover_label) + ' (green).'
                    : 'WorldCover = ' + esc(c.satellite_observation.landcover_label || '—') + '.') +
                '</p>';
        }

        var satHtml = '';
        if (c.id === 'green_mapped_vs_satellite') {
            satHtml = '<p class="muted small">' +
                (c.satellite_observation.green_by_ndvi
                    ? 'NDVI = ' + esc(HS.fmt(c.satellite_observation.ndvi, '', 3)) + ' (green). '
                    : 'NDVI does not indicate green. ') +
                (c.satellite_observation.green_by_landcover
                    ? 'WorldCover = ' + esc(c.satellite_observation.landcover_label) + ' (green).'
                    : 'WorldCover = ' + esc(c.satellite_observation.landcover_label || '—') + '.') +
                '</p>';
        } else {
            if ((c.map_claim.feature_summaries || []).length) {
                satHtml = '<ul class="muted small">' +
                    c.map_claim.feature_summaries.map(function (s) {
                        return '<li>' + renderFeatureSummary(s) + '</li>';
                    }).join('') +
                    '</ul>';
            } else {
                satHtml = '<p class="muted small">No mapped green features within the radius.</p>';
            }
        }

        var causesHtml = '';
        if ((c.possible_causes || []).length) {
            causesHtml = '<div class="notice notice-warn" style="margin-top:8px;">' +
                '<strong>Possible causes:</strong><ul>' +
                c.possible_causes.map(function (cause) {
                    return '<li>' + esc(cause) + '</li>';
                }).join('') +
                '</ul></div>';
        }

        return '<div class="panel">' +
            '<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">' +
            '<h3 style="margin:0;">' + (c.id === 'green_mapped_vs_satellite'
                ? 'Mapped green vs satellite'
                : 'Satellite green vs map') + '</h3>' +
            resultChip(c.result) +
            '</div>' +
            '<div class="card-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px;">' +
            '<div class="item-card" style="padding:14px;">' +
            '<h4 style="margin-top:0;">' + esc(mapLabel) + '</h4>' + mapHtml +
            '</div>' +
            '<div class="item-card" style="padding:14px;">' +
            '<h4 style="margin-top:0;">' + esc(satLabel) + '</h4>' + satHtml +
            '</div>' +
            '</div>' +
            '<p class="muted small" style="margin-top:10px;"><strong>Basis:</strong> ' + esc(c.basis) + '</p>' +
            causesHtml +
            '<details class="expander" style="margin-top:10px;">' +
            '<summary>Evidence details</summary>' + renderEvidence(c.evidence) + '</details>' +
            '</div>';
    }

    function renderResult(body, ok) {
        if (!ok || body.error) {
            renderStatus('error', 'Map Check unavailable: ' + esc(body.error || 'request failed'));
            return;
        }
        var html = '';
        html += '<div class="panel">' +
            '<h3>Location</h3>' +
            '<p class="muted small">' + esc(body.location.lat) + ', ' + esc(body.location.lon) +
            ' · radius ' + esc(body.location.radius_m) + ' m · ' + esc(body.generated_at) + '</p>' +
            '<p class="muted small"><strong>Check ID:</strong> <code>' + esc(body.check_id) + '</code></p>' +
            '</div>';

        if (body.status === 'unavailable') {
            renderStatus('warn', 'Map Check cannot assess this location: both map and satellite inputs are unavailable.');
        } else if (body.status === 'degraded') {
            renderStatus('warn', 'Map Check is running in degraded mode: one input source is unavailable.');
        } else {
            var disc = body.discrepancies_count || 0;
            if (disc === 0) {
                renderStatus('info', 'No discrepancies detected between mapped and satellite green signals.');
            } else {
                renderStatus('warn', disc + ' discrepancy' + (disc === 1 ? '' : 's') + ' detected. Review possible causes before relying on any single map.');
            }
        }

        (body.checks || []).forEach(function (c) {
            html += renderCheck(c);
        });

        if ((body.declared_gaps || []).length) {
            html += '<div class="panel"><h3>Declared data gaps</h3><div class="notice notice-warn">' +
                body.declared_gaps.map(function (g) {
                    return '<strong>' + esc(g.component) + ':</strong> ' + esc(g.reason) + '<br>';
                }).join('') +
                '</div></div>';
        }

        if ((body.recommendations || []).length) {
            html += '<div class="panel"><h3>Recommendations</h3><ul class="muted">' +
                body.recommendations.map(function (r) {
                    return '<li>' + esc(r) + '</li>';
                }).join('') +
                '</ul></div>';
        }

        html += '<div class="disclaimer-box">' + esc(body.disclaimer) + '</div>';

        el('mapcheckResult').innerHTML = html;
        el('mapcheckExplainer').style.display = '';

        if (window.HSConvert) HSConvert.trackAction('mapcheck_viewed', {});
    }

    function runMapCheck() {
        var input = el('mapcheckLocInput').value.trim();
        if (!input) {
            renderStatus('error', 'Enter a location — a place name or lat,lon coordinates.');
            return;
        }
        var radiusVal = parseInt(el('radiusInput').value, 10);
        if (isNaN(radiusVal) || radiusVal < 50 || radiusVal > 2000) {
            renderStatus('error', 'Radius must be between 50 and 2000 metres.');
            return;
        }

        el('runMapcheckBtn').disabled = true;
        clearStatus();
        renderStatus('info', 'Resolving location and fetching open map / satellite data…');
        el('mapcheckResult').innerHTML = '';

        HS.resolveLocation(input).then(function (loc) {
            if (!loc.ok) {
                el('runMapcheckBtn').disabled = false;
                renderStatus('error', esc(loc.error || 'Location could not be resolved.'));
                return;
            }
            var url = API + '/v2/mapcheck/?lat=' + loc.lat.toFixed(4) +
                '&lon=' + loc.lon.toFixed(4) +
                '&radius_m=' + radiusVal;
            return fetchJSON(url).then(function (res) {
                el('runMapcheckBtn').disabled = false;
                renderResult(res.body || {}, res.ok);
            });
        }).catch(function () {
            el('runMapcheckBtn').disabled = false;
            renderStatus('error', 'The Map Check service could not be reached.');
        });
    }

    function init() {
        el('runMapcheckBtn').addEventListener('click', runMapCheck);
        if (window.HS && HS.location) {
            HS.location.enhance('mapcheckLocInput', 'mapcheckLocAssist');
        }
        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q && el('mapcheckLocInput')) el('mapcheckLocInput').value = q;
    }

    init();
})();
