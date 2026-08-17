/* HydraShield — Solutions Intelligence (solutions.html).
 *
 * Location + caller-selected hazards of interest →
 *   GET /api/v2/solutions?lat&lon&hazards=wildfire,drought
 *
 * Renders recommendations_by_hazard as grouped solution cards: name,
 * class chips, why_it_fits, expected benefit (mechanism + quantified
 * flag), limitations, complexity / maintenance / maturity, sources, and
 * the no-guarantee disclaimer visibly repeated per card. The
 * insufficient_data block is shown when present.
 *
 * Endpoints used:
 *   GET /api/v2/hazards            (hazard checkboxes)
 *   GET /api/analyze?location=…    (place-name geocoding)
 *   GET /api/v2/solutions          (recommendations)
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function loadHazards() {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) {
                el('hazardChecks').innerHTML =
                    '<span class="muted small">Hazard registry unavailable.</span>';
                return;
            }
            el('hazardChecks').innerHTML = res.body.hazards.map(function (h) {
                return '<label style="display:inline-flex;align-items:center;gap:6px;' +
                    'border:1px solid rgba(0,0,0,0.12);border-radius:999px;padding:6px 14px;' +
                    'font-size:0.85rem;cursor:pointer;background:var(--white);">' +
                    '<input type="checkbox" value="' + esc(h.id) + '"' +
                    (h.id === 'wildfire' ? ' checked' : '') + '> ' + esc(h.name) + '</label>';
            }).join('');
        }).catch(function () {
            el('hazardChecks').innerHTML =
                '<span class="muted small">Hazard registry could not be reached.</span>';
        });
    }

    function selectedHazards() {
        return Array.prototype.map.call(
            document.querySelectorAll('#hazardChecks input[type=checkbox]:checked'),
            function (cb) { return cb.value; });
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
        el('solutionsArea').innerHTML = '';
        renderStatus('info', 'Resolving location…');

        HS.resolveLocation(q).then(function (loc) {
            if (!loc.ok) {
                el('searchBtn').disabled = false;
                renderStatus('error', esc(loc.error || 'Location could not be resolved.'));
                return;
            }
            HS.rememberLocation({ name: loc.name, lat: loc.lat, lon: loc.lon });
            renderStatus('info', 'Matching solutions for ' + esc(loc.name) + '…');
            var hazards = selectedHazards();
            var url = API + '/v2/solutions?lat=' + loc.lat.toFixed(4) +
                '&lon=' + loc.lon.toFixed(4) +
                (hazards.length ? '&hazards=' + encodeURIComponent(hazards.join(',')) : '');
            return fetchJSON(url).then(function (res) {
                el('searchBtn').disabled = false;
                renderSolutions(res.body || {}, res.ok, loc);
            });
        }).catch(function () {
            el('searchBtn').disabled = false;
            renderStatus('error', 'The solutions service could not be reached.');
        });
    }

    function renderSolutions(body, ok, loc) {
        var area = el('solutionsArea');
        if (!ok || body.error) {
            renderStatus('error', 'Solutions unavailable: ' + esc(body.error || 'request failed'));
            return;
        }

        var byHazard = body.recommendations_by_hazard || {};
        var hazardIds = Object.keys(byHazard);

        var statusHtml = '';
        if (body.status === 'insufficient_data') {
            statusHtml = '<div class="notice notice-warn"><strong>Insufficient data for matched recommendations.</strong><br>' +
                esc(body.message || 'Active hazard levels were not available for this location.') + '</div>';
        } else {
            var total = hazardIds.reduce(function (n, h) { return n + byHazard[h].length; }, 0);
            statusHtml = total
                ? '<div class="notice notice-info">' + total + ' solution(s) matched for ' +
                  esc(loc.name) + ' across ' + hazardIds.length + ' hazard(s).</div>'
                : '<div class="notice notice-empty">No solutions matched the selected hazards and verified site conditions at ' +
                  esc(loc.name) + '.</div>';
        }
        el('statusArea').innerHTML = statusHtml;

        var html = '';

        // Grouped solution cards.
        hazardIds.forEach(function (hid) {
            var list = byHazard[hid];
            html += '<h2 style="font-family:var(--font-display);font-size:1.2rem;margin:26px 0 12px;">' +
                esc(hid.charAt(0).toUpperCase() + hid.slice(1)) + '</h2>';
            if (!list.length) {
                html += '<div class="notice notice-empty">No solutions matched ' + esc(hid) +
                    ' for the verified site conditions here.</div>';
                return;
            }
            html += '<div class="card-grid">' + list.map(solutionCardHTML).join('') + '</div>';
        });

        // insufficient_data block — shown when present, never hidden.
        var ins = body.insufficient_data;
        if (ins && ins.missing_inputs && ins.missing_inputs.length) {
            html += '<div class="panel" style="margin-top:24px;"><h2>Data that would sharpen these recommendations</h2>' +
                '<div class="table-scroll"><table class="data-table"><thead><tr><th>Missing input</th><th>Would sharpen</th></tr></thead><tbody>' +
                ins.missing_inputs.map(function (m) {
                    return '<tr><td>' + esc(m.input) + '</td><td>' + esc(m.would_sharpen) + '</td></tr>';
                }).join('') + '</tbody></table></div>' +
                (ins.note ? '<p class="muted small" style="margin-top:8px;">' + esc(ins.note) + '</p>' : '') +
                '</div>';
        }

        if (body.guarantee_disclaimer) {
            html += '<div class="disclaimer-box" style="margin-top:20px;"><strong>' +
                esc(body.guarantee_disclaimer) + '</strong> Recommendations are screening-level ' +
                'matches from real site conditions and a curated knowledge base; local expert ' +
                'verification is required before implementation.</div>';
        }

        area.innerHTML = html;
    }

    function solutionCardHTML(s) {
        var eb = s.expected_benefit || {};
        var fit = s.fit || {};
        var html = '<div class="item-card">';

        html += '<h3>' + esc(s.name) + '</h3>';

        if (s.classes && s.classes.length) {
            html += '<div class="badge-row">' + s.classes.map(function (c) {
                return '<span class="chip chip-inferred">' + esc(c.replace(/_/g, ' ')) + '</span>';
            }).join('') + '</div>';
        }

        if (s.why_it_fits) {
            html += '<p class="muted" style="margin:0;">' + esc(s.why_it_fits) + '</p>';
        }

        // Expected benefit: mechanism + honest quantified flag.
        if (eb.mechanism || eb.quantification_note) {
            html += '<div class="sub-block sub-modelled"><div class="sub-block-title">Expected benefit ' +
                chip(eb.quantified ? 'DOCUMENTED' : 'MODELLED', eb.quantified ? 'QUANTIFIED' : 'NOT QUANTIFIED') +
                '</div>' +
                (eb.mechanism ? '<div>' + esc(eb.mechanism) + '</div>' : '') +
                (eb.quantification_note ? '<div class="muted small">' + esc(eb.quantification_note) + '</div>' : '') +
                '</div>';
        }

        // Fit + confidence.
        var meta = [];
        if (fit.conditions_matched !== undefined && fit.conditions_relevant) {
            meta.push('Site-fit: ' + fit.conditions_matched + '/' + fit.conditions_relevant +
                ' declared conditions verified');
        }
        if (s.data_confidence) meta.push('Data confidence: ' + s.data_confidence);
        if (s.implementation_complexity) meta.push('Complexity: ' + s.implementation_complexity);
        if (s.maintenance) meta.push('Maintenance: ' + s.maintenance);
        if (s.technology_maturity) meta.push('Maturity: ' + s.technology_maturity);
        if (s.cost_basis) meta.push('Cost basis: ' + s.cost_basis);
        if (meta.length) {
            html += '<div class="muted small">' + meta.map(esc).join(' · ') + '</div>';
        }

        if (s.limitations && s.limitations.length) {
            html += '<details class="expander"><summary>Limitations (' + s.limitations.length + ')</summary>' +
                '<ul style="margin:6px 0 0 18px;" class="muted">' +
                s.limitations.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') +
                '</ul></details>';
        }
        if (s.environmental_considerations && s.environmental_considerations.length) {
            html += '<details class="expander"><summary>Environmental considerations (' +
                s.environmental_considerations.length + ')</summary>' +
                '<ul style="margin:6px 0 0 18px;" class="muted">' +
                s.environmental_considerations.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') +
                '</ul></details>';
        }
        if (fit.unverified && fit.unverified.length) {
            html += '<details class="expander"><summary>Unverified site conditions (' +
                fit.unverified.length + ')</summary>' +
                '<ul style="margin:6px 0 0 18px;" class="muted">' +
                fit.unverified.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') +
                '</ul></details>';
        }

        if (s.sources && s.sources.length) {
            html += '<div class="card-actions">' + s.sources.map(function (src) {
                var url = typeof src === 'object' ? (src.url || src.link) : src;
                var label = typeof src === 'object' ? (src.label || src.title || src.url || src.link) : src;
                return url
                    ? '<a class="text-link" href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(label) + ' →</a>'
                    : '<span class="muted small">' + esc(label) + '</span>';
            }).join('') + '</div>';
        }

        // No-guarantee disclaimer repeated per card — visibly.
        if (s.guarantee_disclaimer) {
            html += '<div class="disclaimer-box">' + esc(s.guarantee_disclaimer) + '</div>';
        }

        html += '</div>';
        return html;
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
