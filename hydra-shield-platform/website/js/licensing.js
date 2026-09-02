/* Talaix — Environmental Licensing Advisory page (licensing.html).
 *
 * Builds a pre-draft environmental licensing evidence dossier via the
 * licensing engine (POST /api/v2/licensing/dossier) — the same engine
 * registered as the TX-2 product "licensing" in the TX engine.
 * Conventions match forensics.js / insurance.js.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function renderStatus(mountId, kind, html) {
        el(mountId).innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function clearStatus(mountId) {
        el(mountId).innerHTML = '';
    }

    function levelChip(level) {
        if (!level || !level.label) return chip('unknown', 'UNKNOWN');
        var map = { Low: 'observed', Moderate: 'reported', High: 'error', Extreme: 'error' };
        return '<span class="chip chip-' + esc(map[level.label] || 'unknown') + '">' +
            esc(level.label) + '</span>';
    }

    function severityChip(severity) {
        var map = { high: 'error', medium: 'reported', info: 'documented' };
        return '<span class="chip chip-' + esc(map[severity] || 'unknown') + '">' +
            esc(String(severity || 'info').toUpperCase()) + '</span>';
    }

    function buildPayload() {
        var radius = parseFloat(el('licRadiusInput').value);
        if (isNaN(radius) || radius < 1 || radius > 200) {
            return { error: 'Radius must be between 1 and 200 km.' };
        }
        var siteInput = el('licSiteInput').value.trim();
        if (!siteInput) return { error: 'Enter a site location.' };

        var site = null;
        var parts = siteInput.split(',').map(function (s) { return s.trim(); });
        if (parts.length === 2 && !isNaN(parseFloat(parts[0])) && !isNaN(parseFloat(parts[1]))) {
            site = { lat: parseFloat(parts[0]), lon: parseFloat(parts[1]) };
        } else {
            site = { address: siteInput };
        }

        return {
            site: site,
            radius_km: radius,
            side: el('licSide').value,
            typology: el('licTypology').value,
            permit_type: el('licPermitType').value,
            project_title: el('licTitle').value.trim() || undefined,
            description: el('licDescription').value.trim() || undefined,
            jurisdiction: el('licJurisdiction').value.trim() || undefined,
        };
    }

    function renderHeader(data) {
        var req = data.request || {};
        var site = data.site || {};
        var html = '<div class="panel"><h3>Dossier</h3>';
        html += '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Dossier ID</th><td><code>' + esc(data.dossier_id) + '</code></td></tr>' +
            (req.project_title ? '<tr><th>Project</th><td>' + esc(req.project_title) + '</td></tr>' : '') +
            '<tr><th>Site</th><td>' + esc(site.name) + ' (' + esc(site.lat) + ', ' + esc(site.lon) + ')</td></tr>' +
            '<tr><th>Screening radius</th><td>' + esc(site.radius_km) + ' km</td></tr>' +
            '<tr><th>Prepared for</th><td>' + esc(req.side_label) + '</td></tr>' +
            '<tr><th>Typology</th><td>' + esc(req.typology_label) + '</td></tr>' +
            '<tr><th>Permit / consent</th><td>' + esc(req.permit_type_label) + '</td></tr>' +
            (req.jurisdiction ? '<tr><th>Jurisdiction</th><td>' + esc(req.jurisdiction) + '</td></tr>' : '') +
            '<tr><th>Generated</th><td>' + esc(data.generated_at) + '</td></tr>' +
            '<tr><th>Engine version</th><td>' + esc(data.engine_version) + '</td></tr>' +
            '</table></div>';
        html += '<p class="muted small">' + esc(req.framing) + '</p>';
        html += '<p class="muted small"><strong>Screening summary:</strong> ' + esc(data.summary) + '</p>';
        html += '</div>';
        return html;
    }

    function renderHazardExposure(checks) {
        var html = '<div class="panel"><h3>Multi-hazard exposure ' + chip('modelled', 'MODELLED') + '</h3>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Hazard</th><th>Level</th><th>Summary</th>' +
            '</tr></thead><tbody>';
        (checks || []).forEach(function (c) {
            html += '<tr><td>' + esc(c.permit_label) + '</td><td>';
            if (c.status === 'unavailable') {
                html += chip('unknown', 'UNKNOWN');
            } else {
                html += levelChip(c.level);
            }
            html += '</td><td>' + esc(c.summary);
            if (c.reason) {
                html += '<br><span class="muted small">Declared: ' + esc(c.reason) + '</span>';
            }
            html += '</td></tr>';
        });
        html += '</tbody></table></div></div>';
        return html;
    }

    function renderContextEvidence(base) {
        var html = '<div class="panel"><h3>Site evidence</h3>';

        var lc = base.landcover || {};
        html += '<details class="expander"><summary><strong>Land cover</strong> ' +
            chip(lc.evidence_label || 'unknown') + '</summary><div style="padding:10px 0;">';
        if (lc.status === 'ok') {
            html += '<p class="muted small">Dominant: ' + esc(lc.dominant_label) +
                ' (fraction ' + esc(lc.dominant_fraction) + ') · source ' + esc(lc.source) +
                ' · resolution ' + esc(lc.resolution) + '</p>';
        } else {
            html += '<p class="muted small">Unavailable: ' + esc(lc.reason || 'no data') + '</p>';
        }
        html += '</div></details>';

        var sat = base.satellite || {};
        html += '<details class="expander"><summary><strong>Satellite imagery &amp; spectral evidence</strong> ' +
            chip(sat.evidence_label || 'unknown') + '</summary><div style="padding:10px 0;">';
        if (sat.status === 'ok') {
            html += '<p class="muted small">NDVI ' + esc(sat.ndvi) + ' · NDMI ' + esc(sat.ndmi) +
                ' · observation ' + esc(sat.observation_date) + ' · source ' + esc(sat.source) +
                (sat.resolution_m ? ' · ' + esc(sat.resolution_m) + ' m' : '') + '</p>';
        } else {
            html += '<p class="muted small">Unavailable: ' + esc(sat.reason || 'no data') + '</p>';
        }
        html += '</div></details>';

        var ev = base.historical_events || {};
        html += '<details class="expander"><summary><strong>Historical environmental events</strong> ' +
            chip(ev.evidence_label || 'unknown') + '</summary><div style="padding:10px 0;">';
        var fires = ev.recent_fire_detections || {};
        if (fires.status === 'ok') {
            html += '<p class="muted small">' + esc(fires.count || 0) +
                ' recent fire detection(s) within ' + esc(fires.radius_km) + ' km / ' +
                esc(fires.days) + ' days · sensor ' + esc(fires.sensor || '—') + '</p>';
        } else if (fires.reason) {
            html += '<p class="muted small">Fire detections unavailable: ' + esc(fires.reason) + '</p>';
        }
        (ev.hazard_events || []).forEach(function (block) {
            if (block.status === 'ok' && (block.count || 0) > 0) {
                html += '<p class="muted small"><strong>' + esc(block.hazard) + '</strong>: ' +
                    esc(block.count) + ' recorded event(s) in the screening radius.</p>';
            } else if (block.status === 'unavailable') {
                html += '<p class="muted small"><strong>' + esc(block.hazard) + '</strong>: unavailable — ' +
                    esc(block.reason || 'no data') + '</p>';
            }
        });
        html += '</div></details>';

        html += '</div>';
        return html;
    }

    function renderConstraints(constraints) {
        var html = '<div class="panel"><h3>Constraints &amp; risk flags ' + chip('inferred', 'INFERRED') + '</h3>';
        if (!constraints || !constraints.length) {
            html += '<div class="notice notice-info">No site-specific constraints were ' +
                'inferred from the available evidence.</div></div>';
            return html;
        }
        constraints.forEach(function (c) {
            html += '<div class="notice notice-warn" style="margin-bottom:10px;">' +
                severityChip(c.severity) + ' <strong>' + esc(c.title) + '</strong>' +
                '<br><span class="muted small">' + esc(c.basis) + '</span></div>';
        });
        html += '</div>';
        return html;
    }

    function renderFrameworks(frameworks) {
        var html = '<div class="panel"><h3>Framework references ' + chip('documented', 'DOCUMENTED') + '</h3>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Framework</th><th>Role</th><th>Relevance</th>' +
            '</tr></thead><tbody>';
        (frameworks || []).forEach(function (f) {
            html += '<tr><td>' + esc(f.name) + '</td><td>' + esc(f.role) + '</td>' +
                '<td class="muted small">' + esc(f.note) + '</td></tr>';
        });
        html += '</tbody></table></div></div>';
        return html;
    }

    function renderGaps(gaps) {
        var html = '<div class="panel"><h3>Declared data gaps ' + chip('unknown', 'UNKNOWN') + '</h3>';
        if (!gaps || !gaps.length) {
            html += '<div class="notice notice-info">No declared data gaps.</div></div>';
            return html;
        }
        html += '<div class="notice notice-warn">';
        gaps.forEach(function (g) {
            html += '<strong>' + esc(g.layer) + '</strong> — ' + esc(g.reason) + '<br>';
        });
        html += '</div></div>';
        return html;
    }

    function renderDossier(data) {
        var base = data.evidence_base || {};
        var html = '';
        html += renderHeader(data);
        html += renderHazardExposure(base.hazard_exposure);
        html += renderContextEvidence(base);
        html += renderConstraints(data.constraints);
        html += renderFrameworks(data.frameworks);
        html += renderGaps(data.declared_gaps);
        html += '<div class="panel notice notice-warn"><h3>Disclaimer</h3>' +
            '<p>' + esc(data.disclaimer) + '</p>' +
            '<p class="muted small">' + esc(data.honesty_contract) + '</p></div>';
        el('licResult').innerHTML = html;
    }

    function buildDossier() {
        var payload = buildPayload();
        if (payload.error) {
            renderStatus('licStatus', 'error', esc(payload.error));
            return;
        }
        clearStatus('licStatus');
        renderStatus('licStatus', 'info',
            'Building the evidence base — cross-matching the site against satellite, ' +
            'land-cover, hazard and historical-event layers…');
        el('buildDossierBtn').disabled = true;

        fetchJSON(API + '/v2/licensing/dossier', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('buildDossierBtn').disabled = false;
            if (!res.ok || res.body.error) {
                renderStatus('licStatus', 'error',
                    esc(res.body.error || 'Dossier generation failed'));
                return;
            }
            clearStatus('licStatus');
            renderDossier(res.body);
        }).catch(function () {
            el('buildDossierBtn').disabled = false;
            renderStatus('licStatus', 'error', 'The service could not be reached.');
        });
    }

    function fillSelect(selectEl, items, defaultId) {
        items.forEach(function (item) {
            var opt = document.createElement('option');
            opt.value = item.id;
            opt.textContent = item.label;
            selectEl.appendChild(opt);
        });
        if (defaultId) selectEl.value = defaultId;
    }

    function loadFrameworks() {
        fetchJSON(API + '/v2/licensing/frameworks').then(function (res) {
            if (!res.ok || !res.body) return;
            var data = res.body;
            fillSelect(el('licSide'), data.applicant_sides || [], 'applicant');
            fillSelect(el('licTypology'), data.typologies || [], 'other');
            fillSelect(el('licPermitType'), data.permit_types || [], 'eia_screening');
        });
    }

    function init() {
        el('buildDossierBtn').addEventListener('click', buildDossier);
        if (window.HS && HS.location) {
            HS.location.enhance('licSiteInput', 'licSiteAssist');
        }

        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q && el('licSiteInput')) el('licSiteInput').value = q;

        loadFrameworks();
    }

    init();
})();
