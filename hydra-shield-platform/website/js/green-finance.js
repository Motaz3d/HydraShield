/* Talaix — Green Finance Verification page (green-finance.html).
 *
 * Single-asset verification and portfolio batch checks against the
 * /api/v2/verification endpoints. Follows the same honest-rendering
 * conventions as intelligence.js: unavailable data is declared, never
 * invented.
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

    // ------------------------------------------------------------------
    // Asset verification
    // ------------------------------------------------------------------

    function verifyAsset() {
        var input = el('assetLocInput').value.trim();
        if (!input) {
            renderStatus('assetStatus', 'error', 'Enter a location — a place name or lat,lon coordinates.');
            return;
        }
        el('verifyAssetBtn').disabled = true;
        clearStatus('assetStatus');
        renderStatus('assetStatus', 'info', 'Resolving location…');

        HS.resolveLocation(input).then(function (loc) {
            if (!loc.ok) {
                el('verifyAssetBtn').disabled = false;
                renderStatus('assetStatus', 'error', esc(loc.error || 'Location could not be resolved.'));
                return;
            }
            var url = API + '/v2/verification/asset?lat=' + loc.lat.toFixed(4) +
                '&lon=' + loc.lon.toFixed(4) +
                '&name=' + encodeURIComponent(loc.name);
            return fetchJSON(url).then(function (res) {
                el('verifyAssetBtn').disabled = false;
                if (!res.ok || res.body.error) {
                    renderStatus('assetStatus', 'error', esc(res.body.error || 'Verification failed'));
                    return;
                }
                renderAssetResult(res.body, loc);
            });
        }).catch(function () {
            el('verifyAssetBtn').disabled = false;
            renderStatus('assetStatus', 'error', 'The verification service could not be reached.');
        });
    }

    function renderAssetResult(v, loc) {
        var asset = v.asset || {};
        var html = '';

        // Asset metadata
        html += '<div class="panel"><h3>Asset</h3>';
        html += '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Name</th><td>' + esc(asset.name || '—') + '</td></tr>' +
            '<tr><th>Coordinates</th><td>' + esc(asset.lat) + ', ' + esc(asset.lon) + '</td></tr>' +
            '<tr><th>Verification ID</th><td>' + esc(v.verification_id) + '</td></tr>' +
            '<tr><th>Generated</th><td>' + esc(v.generated_at) + '</td></tr>' +
            '<tr><th>Engine version</th><td>' + esc(v.engine_version) + '</td></tr>' +
            '</table></div>';
        html += '<p class="muted small" style="margin-top:10px;">' + esc(v.honesty_contract) + '</p>';
        html += '</div>';

        // DNSH checklist
        html += '<div class="panel"><h3>DNSH hazard checklist</h3>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Taxonomy hazard</th><th>Class</th><th>Status</th><th>Level</th><th>Confidence</th>' +
            '</tr></thead><tbody>';
        (v.hazard_checks || []).forEach(function (c) {
            var level = (c.level || {}).label || '—';
            html += '<tr>' +
                '<td>' + esc(c.taxonomy_label) + '</td>' +
                '<td>' + esc((c.risk_class || []).map(function (x) { return x.charAt(0).toUpperCase() + x.slice(1); }).join(' & ')) + '</td>' +
                '<td>' + chip(c.claim_status) + '</td>' +
                '<td>' + esc(level) + '</td>' +
                '<td>' + esc(c.confidence) + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div></div>';

        // Per-hazard evidence details
        html += '<div class="panel"><h3>Per-hazard evidence</h3>';
        (v.hazard_checks || []).forEach(function (c) {
            var level = c.level || {};
            html += '<details class="expander">';
            html += '<summary><strong>' + esc(c.taxonomy_label) + '</strong> ' +
                chip(c.claim_status) + ' ' + chip(c.confidence) + '</summary>';
            html += '<div style="padding:10px 0;">';
            if (c.summary) html += '<p>' + esc(c.summary) + '</p>';
            if (level.basis) html += '<p class="muted small"><strong>Level basis:</strong> ' + esc(level.basis) + '</p>';
            if ((c.evidence || []).length) {
                html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                    '<th>Source</th><th>Dataset</th><th>Period</th><th>Status</th><th>Link</th>' +
                    '</tr></thead><tbody>';
                c.evidence.forEach(function (rec) {
                    var period = '—';
                    if (rec.reference_period && (rec.reference_period.start || rec.reference_period.end)) {
                        period = (rec.reference_period.start || '') + ' → ' + (rec.reference_period.end || '');
                        period = period.replace(/^ → | → $/g, '');
                    }
                    var link = rec.link || rec.provider_url || '';
                    html += '<tr>' +
                        '<td>' + esc(rec.source || '—') + '</td>' +
                        '<td>' + esc(rec.dataset || '—') + '</td>' +
                        '<td>' + esc(period) + '</td>' +
                        '<td>' + chip(rec.claim_status) + '</td>' +
                        '<td>' + (link
                            ? '<a class="text-link" href="' + esc(link) + '" target="_blank" rel="noopener">Source →</a>'
                            : '—') + '</td>' +
                        '</tr>';
                });
                html += '</tbody></table></div>';
            }
            if ((c.limitations || []).length) {
                html += '<div class="notice notice-warn" style="margin-top:8px;">';
                c.limitations.forEach(function (lim) { html += esc(lim) + '<br>'; });
                html += '</div>';
            }
            html += '</div></details>';
        });
        html += '</div>';

        // Declared gaps
        html += '<div class="panel"><h3>Declared data gaps</h3>';
        if ((v.declared_gaps || []).length) {
            html += '<div class="notice notice-warn">';
            v.declared_gaps.forEach(function (g) {
                html += '<strong>' + esc(g.taxonomy_label) + '</strong>: ' + esc(g.reason) + '<br>';
            });
            html += '</div>';
        } else {
            html += '<div class="notice notice-info">No declared data gaps for this asset.</div>';
        }
        html += '</div>';

        // PDF + monitoring hint
        var pdfUrl = API + '/v2/verification/report?lat=' + asset.lat.toFixed(4) +
            '&lon=' + asset.lon.toFixed(4) +
            '&name=' + encodeURIComponent(asset.name || '');
        html += '<div class="panel">' +
            '<a class="btn-action" href="' + esc(pdfUrl) + '" target="_blank" rel="noopener">Download evidence PDF</a>' +
            '<p class="muted small" style="margin-top:10px;">' + esc(v.monitoring_hint) +
            ' <a class="text-link" href="account.html">Set up alerts →</a></p>' +
            '</div>';

        el('assetResult').innerHTML = html;
    }

    // ------------------------------------------------------------------
    // Portfolio batch check
    // ------------------------------------------------------------------

    function parsePortfolio(text) {
        var assets = [];
        var lines = text.split(/\r?\n/);
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (!line) continue;
            var parts = line.split(',').map(function (s) { return s.trim(); });
            var lat, lon, name;
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
            if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
                return { error: 'Line ' + (i + 1) + ' has invalid lat/lon' };
            }
            assets.push({ name: name, lat: lat, lon: lon });
        }
        return { assets: assets };
    }

    function verifyPortfolio() {
        var parsed = parsePortfolio(el('portfolioText').value);
        if (parsed.error) {
            renderStatus('portfolioStatus', 'error', esc(parsed.error));
            return;
        }
        if (!parsed.assets.length) {
            renderStatus('portfolioStatus', 'error', 'Enter at least one asset.');
            return;
        }
        el('verifyPortfolioBtn').disabled = true;
        clearStatus('portfolioStatus');
        renderStatus('portfolioStatus', 'info', 'Running portfolio check…');

        var payload = { assets: parsed.assets };
        var name = el('portfolioName').value.trim();
        if (name) payload.name = name;

        fetchJSON(API + '/v2/verification/portfolio', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('verifyPortfolioBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                var upgrade = (res.body || {}).upgrade;
                var msg = 'Please <a class="text-link" href="account.html">sign in</a>';
                if (upgrade && upgrade.required_role) {
                    msg += ' or upgrade to the <strong>' + esc(upgrade.required_role) + '</strong> tier';
                }
                msg += ' to run portfolio checks.';
                renderStatus('portfolioStatus', 'warn', msg);
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('portfolioStatus', 'error', esc(res.body.error || 'Portfolio check failed'));
                return;
            }
            renderPortfolioResult(res.body);
        }).catch(function () {
            el('verifyPortfolioBtn').disabled = false;
            renderStatus('portfolioStatus', 'error', 'The verification service could not be reached.');
        });
    }

    function renderPortfolioResult(data) {
        var html = '<div class="panel"><h3>Portfolio result</h3>';
        html += '<p class="muted small">Portfolio ID: <code>' + esc(data.portfolio_id) + '</code> · ' +
            esc(data.ok_count) + ' of ' + esc(data.count) + ' assets OK</p>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Asset</th><th>OK</th><th>Top hazard levels</th><th>Verification id</th>' +
            '</tr></thead><tbody>';
        (data.results || []).forEach(function (r) {
            var levels = Object.keys(r.hazard_levels || {}).map(function (h) {
                return esc(h) + ': ' + esc(r.hazard_levels[h]);
            }).join(', ') || '—';
            html += '<tr>' +
                '<td>' + esc((r.asset && r.asset.name) ? r.asset.name : ((r.asset && r.asset.lat) ? r.asset.lat + ', ' + r.asset.lon : '—')) + '</td>' +
                '<td>' + (r.ok ? '<span class="chip chip-observed">YES</span>' : '<span class="chip chip-error">NO</span>') + '</td>' +
                '<td>' + levels + '</td>' +
                '<td>' + esc(r.verification_id || '—') + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        html += '<p class="muted small" style="margin-top:10px;">' +
            'Full record: <a class="text-link" href="' + esc(API + '/v2/verification/portfolio/' + data.portfolio_id) + '" target="_blank" rel="noopener">JSON →</a>' +
            '</p>';
        html += '</div>';
        el('portfolioResult').innerHTML = html;
    }

    // ------------------------------------------------------------------
    // Init
    // ------------------------------------------------------------------

    function init() {
        el('verifyAssetBtn').addEventListener('click', verifyAsset);
        el('verifyPortfolioBtn').addEventListener('click', verifyPortfolio);

        if (window.HS && HS.location) {
            HS.location.enhance('assetLocInput', 'assetLocAssist');
        }

        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q && el('assetLocInput')) el('assetLocInput').value = q;
    }

    init();
})();
