/* Talaix — Supply Chain Origin Evidence page (supplychain.html).
 *
 * Screens origin/green claims against ESA WorldCover and Sentinel-2 data.
 * Conventions match insurance.js / sustainability.js.
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

    function parsePlots(text) {
        var plots = [];
        var lines = text.split(/\r?\n/);
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (!line) continue;
            var parts = line.split(',').map(function (s) { return s.trim(); });
            var name, lat, lon;
            if (parts.length >= 3) {
                name = parts[0];
                lat = parseFloat(parts[1]);
                lon = parseFloat(parts[2]);
            } else if (parts.length === 2) {
                lat = parseFloat(parts[0]);
                lon = parseFloat(parts[1]);
                name = null;
            } else {
                return { error: 'Line ' + (i + 1) + ' must be name,lat,lon or lat,lon' };
            }
            if (isNaN(lat) || isNaN(lon)) {
                return { error: 'Line ' + (i + 1) + ' has invalid lat/lon' };
            }
            plots.push({ name: name, lat: lat, lon: lon });
        }
        return { plots: plots };
    }

    function buildPayload() {
        var parsed = parsePlots(el('plotsText').value);
        if (parsed.error) return { error: parsed.error };
        return {
            supplier: el('supplierInput').value.trim() || null,
            commodity: el('commodityInput').value.trim() || null,
            country: el('countryInput').value.trim() || null,
            plots: parsed.plots,
        };
    }

    function renderEvidenceRecords(records) {
        if (!records || !records.length) return '<p class="muted small">No evidence records.</p>';
        var html = '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Source</th><th>Dataset</th><th>Status</th>' +
            '</tr></thead><tbody>';
        records.forEach(function (rec) {
            html += '<tr>' +
                '<td>' + esc(rec.source || '—') + '</td>' +
                '<td>' + esc(rec.dataset || '—') + '</td>' +
                '<td>' + chip(rec.claim_status) + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    function renderClaim(data) {
        var claim = data.claim || {};
        var html = '';

        html += '<div class="panel"><h3>Claim result</h3>';
        html += '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Claim ID</th><td>' + esc(data.claim_id) + '</td></tr>' +
            '<tr><th>Supplier</th><td>' + esc(claim.supplier || '—') + '</td></tr>' +
            '<tr><th>Commodity</th><td>' + esc(claim.commodity || '—') + '</td></tr>' +
            '<tr><th>Country</th><td>' + esc(claim.country || '—') + '</td></tr>' +
            '<tr><th>Generated</th><td>' + esc(claim.generated_at) + '</td></tr>' +
            '<tr><th>Claim verdict</th><td>' + chip(claim.claim_verdict) + '</td></tr>' +
            '<tr><th>Deforestation assessment</th><td>' + chip((claim.deforestation_assessment || {}).status) + '</td></tr>' +
            '<tr><th>EUDR cutoff</th><td>' + esc(claim.eudr_cutoff_date) + '</td></tr>' +
            '</table></div>';
        if (claim.commodity_advisory) {
            html += '<div class="notice notice-warn" style="margin-top:8px;">' + esc(claim.commodity_advisory) + '</div>';
        }
        html += '<p class="muted small">' + esc(claim.eudr_timeline_note) + '</p>';
        if (claim.supplier_declaration) {
            html += '<p class="muted small"><em>' + esc(claim.supplier_declaration) + '</em></p>';
        }
        html += '</div>';

        html += '<div class="panel"><h3>Per-plot overview</h3>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Plot</th><th>Coordinates</th><th>Verdict</th><th>Land cover</th><th>NDVI</th>' +
            '</tr></thead><tbody>';
        (claim.plots || []).forEach(function (p) {
            var lc = p.landcover || {};
            var sat = p.satellite || {};
            var lcLabel = lc.dominant_label || lc.error || '—';
            var ndvi = sat.ndvi !== undefined && sat.ndvi !== null ? sat.ndvi.toFixed(3) : (sat.error || '—');
            html += '<tr>' +
                '<td>' + esc(p.name) + '</td>' +
                '<td>' + esc(p.lat) + ', ' + esc(p.lon) + '</td>' +
                '<td>' + chip(p.verdict) + '</td>' +
                '<td>' + esc(lcLabel) + '</td>' +
                '<td>' + esc(ndvi) + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div></div>';

        html += '<div class="panel"><h3>Per-plot details</h3>';
        (claim.plots || []).forEach(function (p) {
            html += '<details class="expander">';
            html += '<summary><strong>' + esc(p.name) + '</strong> ' + chip(p.verdict) + '</summary>';
            html += '<div style="padding:10px 0;">';
            html += renderEvidenceRecords(p.evidence);
            if ((p.limitations || []).length) {
                html += '<div class="notice notice-warn" style="margin-top:8px;">';
                p.limitations.forEach(function (lim) { html += esc(lim) + '<br>'; });
                html += '</div>';
            }
            html += '</div></details>';
        });
        html += '</div>';

        html += '<div class="panel"><h3>Declared data gaps</h3>';
        if ((claim.declared_gaps || []).length) {
            html += '<div class="notice notice-warn">';
            claim.declared_gaps.forEach(function (g) {
                html += '<strong>' + esc(g.dataset || g.type) + '</strong> — ' + esc(g.reason) + '<br>';
            });
            html += '</div>';
        } else {
            html += '<div class="notice notice-info">No declared data gaps.</div>';
        }
        html += '</div>';

        html += '<div class="panel notice notice-warn"><h3>Disclaimer</h3>' +
            '<p>' + esc(claim.disclaimer) + '</p></div>';

        el('claimResult').innerHTML = html;
    }

    function handleAuthError(res) {
        var upgrade = (res.body || {}).upgrade;
        var msg = 'Please <a class="text-link" href="account.html">sign in</a>';
        if (upgrade && upgrade.required_role) {
            msg += ' or upgrade to the <strong>' + esc(upgrade.required_role) + '</strong> tier';
        }
        msg += ' to screen supply-chain claims.';
        renderStatus('claimStatus', 'warn', msg);
    }

    function evaluateClaim() {
        var payload = buildPayload();
        if (payload.error) {
            renderStatus('claimStatus', 'error', esc(payload.error));
            return;
        }
        if (!payload.plots.length) {
            renderStatus('claimStatus', 'error', 'Enter at least one plot.');
            return;
        }

        clearStatus('claimStatus');
        renderStatus('claimStatus', 'info', 'Screening claim…');
        el('evaluateClaimBtn').disabled = true;

        fetchJSON(API + '/v2/supplychain/claims', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('evaluateClaimBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                handleAuthError(res);
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('claimStatus', 'error', esc(res.body.error || 'Claim screening failed'));
                return;
            }
            clearStatus('claimStatus');
            renderClaim(res.body);
        }).catch(function () {
            el('evaluateClaimBtn').disabled = false;
            renderStatus('claimStatus', 'error', 'The service could not be reached.');
        });
    }

    function downloadPdf() {
        var payload = buildPayload();
        if (payload.error) {
            renderStatus('claimStatus', 'error', esc(payload.error));
            return;
        }
        if (!payload.plots.length) {
            renderStatus('claimStatus', 'error', 'Enter at least one plot.');
            return;
        }

        clearStatus('claimStatus');
        renderStatus('claimStatus', 'info', 'Building PDF…');
        el('downloadClaimPdfBtn').disabled = true;

        fetch(API + '/v2/supplychain/claims/pdf', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('downloadClaimPdfBtn').disabled = false;
            if (!res.ok) {
                return res.json().then(function (body) {
                    renderStatus('claimStatus', 'error', esc(body.error || 'PDF generation failed'));
                }, function () {
                    renderStatus('claimStatus', 'error', 'PDF generation failed');
                });
            }
            return res.blob().then(function (blob) {
                clearStatus('claimStatus');
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                a.download = 'talaix_supplychain_claim.pdf';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
            });
        }).catch(function () {
            el('downloadClaimPdfBtn').disabled = false;
            renderStatus('claimStatus', 'error', 'The service could not be reached.');
        });
    }

    function init() {
        el('evaluateClaimBtn').addEventListener('click', evaluateClaim);
        el('downloadClaimPdfBtn').addEventListener('click', downloadPdf);
    }

    init();
})();
