/* Talaix — Insurance & Environmental Risk page (insurance.html).
 *
 * Combines current per-peril hazard levels with long-term event records.
 * Conventions match green-finance.js / sustainability.js.
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

    function parseAssets(text) {
        var assets = [];
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
            assets.push({ name: name, lat: lat, lon: lon });
        }
        return { assets: assets };
    }

    function getRadius(inputId) {
        var v = parseFloat(el(inputId).value);
        if (isNaN(v) || v < 1 || v > 500) return null;
        return v;
    }

    function renderEvidenceRecords(records) {
        if (!records || !records.length) return '<p class="muted small">No evidence records.</p>';
        var html = '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Source</th><th>Dataset</th><th>Status</th><th>Link</th>' +
            '</tr></thead><tbody>';
        records.forEach(function (rec) {
            var link = rec.link || rec.provider_url || '';
            html += '<tr>' +
                '<td>' + esc(rec.source || '—') + '</td>' +
                '<td>' + esc(rec.dataset || '—') + '</td>' +
                '<td>' + chip(rec.claim_status) + '</td>' +
                '<td>' + (link
                    ? '<a class="text-link" href="' + esc(link) + '" target="_blank" rel="noopener">Source →</a>'
                    : '—') + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    function renderEventSummary(p) {
        if (p.events_status !== 'ok') {
            return '<p class="muted small">Events unavailable: ' + esc(p.events_reason || 'No reason provided.') + '</p>';
        }
        if (!p.events_summary || !p.events_summary.length) {
            return '<p class="muted small">No events found in the selected radius/time coverage.</p>';
        }
        var html = '<ul class="muted small">';
        p.events_summary.forEach(function (ev) {
            var parts = Object.keys(ev).map(function (k) { return esc(k) + ': ' + esc(ev[k]); });
            html += '<li>' + parts.join('; ') + '</li>';
        });
        html += '</ul>';
        return html;
    }

    function renderProfile(profile, loc) {
        var asset = profile.asset || {};
        var html = '';

        html += '<div class="panel"><h3>Asset</h3>';
        html += '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Name</th><td>' + esc(asset.name || '—') + '</td></tr>' +
            '<tr><th>Coordinates</th><td>' + esc(asset.lat) + ', ' + esc(asset.lon) + '</td></tr>' +
            '<tr><th>Search radius</th><td>' + esc(profile.radius_km) + ' km</td></tr>' +
            '<tr><th>Profile ID</th><td>' + esc(profile.profile_id) + '</td></tr>' +
            '<tr><th>Generated</th><td>' + esc(profile.generated_at) + '</td></tr>' +
            '</table></div>';
        html += '<p class="muted small">' + esc(profile.exposure_summary) + '</p>';
        html += '</div>';

        html += '<div class="panel"><h3>Per-peril overview</h3>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Peril</th><th>Current level</th><th>Status</th><th>Confidence</th><th>Events status</th><th>Events count</th>' +
            '</tr></thead><tbody>';
        (profile.perils || []).forEach(function (p) {
            html += '<tr>' +
                '<td>' + esc(p.peril) + '</td>' +
                '<td>' + esc(p.current_level) + '</td>' +
                '<td>' + chip(p.claim_status) + '</td>' +
                '<td>' + esc(p.confidence) + '</td>' +
                '<td>' + chip(p.events_status) + '</td>' +
                '<td>' + esc(p.events_count) + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div></div>';

        html += '<div class="panel"><h3>Per-peril details</h3>';
        (profile.perils || []).forEach(function (p) {
            html += '<details class="expander">';
            html += '<summary><strong>' + esc(p.peril) + '</strong> ' +
                chip(p.claim_status) + ' / events: ' + chip(p.events_status) + '</summary>';
            html += '<div style="padding:10px 0;">';
            if (p.summary) html += '<p>' + esc(p.summary) + '</p>';
            if (p.level_basis) html += '<p class="muted small"><strong>Level basis:</strong> ' + esc(p.level_basis) + '</p>';
            html += renderEvidenceRecords(p.evidence);
            html += '<p class="muted small" style="margin-top:8px;"><strong>Long-term events:</strong></p>';
            html += renderEventSummary(p);
            if (p.temporal_coverage) {
                html += '<p class="muted small"><strong>Temporal coverage:</strong> ' + esc(JSON.stringify(p.temporal_coverage)) + '</p>';
            }
            if ((p.limitations || []).length) {
                html += '<div class="notice notice-warn" style="margin-top:8px;">';
                p.limitations.forEach(function (lim) { html += esc(lim) + '<br>'; });
                html += '</div>';
            }
            html += '</div></details>';
        });
        html += '</div>';

        html += '<div class="panel"><h3>Declared data gaps</h3>';
        if ((profile.declared_gaps || []).length) {
            html += '<div class="notice notice-warn">';
            profile.declared_gaps.forEach(function (g) {
                html += '<strong>' + esc(g.peril) + '</strong> (' + esc(g.type) + '): ' + esc(g.reason) + '<br>';
            });
            html += '</div>';
        } else {
            html += '<div class="notice notice-info">No declared data gaps for this asset.</div>';
        }
        html += '</div>';

        html += '<div class="panel notice notice-warn"><h3>Loss quantification</h3>' +
            '<p><strong>' + esc(profile.loss_quantification).toUpperCase() + '</strong> — ' + esc(profile.loss_quantification_note) + '</p>' +
            '</div>';

        var pdfUrl = API + '/v2/insurance/profile/report?lat=' + asset.lat.toFixed(4) +
            '&lon=' + asset.lon.toFixed(4) +
            '&radius_km=' + encodeURIComponent(profile.radius_km) +
            '&name=' + encodeURIComponent(asset.name || '');
        html += '<div class="panel">' +
            '<a class="btn-action" href="' + esc(pdfUrl) + '" target="_blank" rel="noopener">Download profile PDF</a>' +
            '</div>';

        el('profileResult').innerHTML = html;
    }

    function assessAsset() {
        var input = el('assetLocInput').value.trim();
        var radius = getRadius('radiusInput');
        if (!input) {
            renderStatus('profileStatus', 'error', 'Enter a location.');
            return;
        }
        if (radius === null) {
            renderStatus('profileStatus', 'error', 'Radius must be between 1 and 500 km.');
            return;
        }
        el('assessAssetBtn').disabled = true;
        clearStatus('profileStatus');
        renderStatus('profileStatus', 'info', 'Resolving location…');

        HS.resolveLocation(input).then(function (loc) {
            if (!loc.ok) {
                el('assessAssetBtn').disabled = false;
                renderStatus('profileStatus', 'error', esc(loc.error || 'Location could not be resolved.'));
                return;
            }
            var url = API + '/v2/insurance/profile?lat=' + loc.lat.toFixed(4) +
                '&lon=' + loc.lon.toFixed(4) +
                '&radius_km=' + radius +
                '&name=' + encodeURIComponent(loc.name);
            return fetchJSON(url).then(function (res) {
                el('assessAssetBtn').disabled = false;
                if (!res.ok || res.body.error) {
                    renderStatus('profileStatus', 'error', esc(res.body.error || 'Profile failed'));
                    return;
                }
                clearStatus('profileStatus');
                renderProfile(res.body, loc);
            });
        }).catch(function () {
            el('assessAssetBtn').disabled = false;
            renderStatus('profileStatus', 'error', 'The service could not be reached.');
        });
    }

    function handleAuthError(res, mountId) {
        var upgrade = (res.body || {}).upgrade;
        var msg = 'Please <a class="text-link" href="account.html">sign in</a>';
        if (upgrade && upgrade.required_role) {
            msg += ' or upgrade to the <strong>' + esc(upgrade.required_role) + '</strong> tier';
        }
        msg += ' to run portfolio checks.';
        renderStatus(mountId, 'warn', msg);
    }

    function renderPortfolio(data) {
        var html = '<div class="panel"><h3>Portfolio result</h3>';
        html += '<p class="muted small">Portfolio ID: <code>' + esc(data.portfolio_id) + '</code> · ' +
            esc(data.ok_count) + ' of ' + esc(data.count) + ' assets OK</p>';

        var ps = data.portfolio_summary || {};
        html += '<h4>Per-peril level distribution</h4>';
        var dist = ps.level_distribution || {};
        var hasDist = Object.keys(dist).length > 0;
        if (hasDist) {
            html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Peril</th><th>Level</th><th>Count</th>' +
                '</tr></thead><tbody>';
            Object.keys(dist).forEach(function (peril) {
                Object.keys(dist[peril]).forEach(function (level) {
                    html += '<tr><td>' + esc(peril) + '</td><td>' + esc(level) + '</td><td>' + esc(dist[peril][level]) + '</td></tr>';
                });
            });
            html += '</tbody></table></div>';
        } else {
            html += '<p class="muted small">No level distribution available.</p>';
        }

        html += '<h4>Per-asset results</h4>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Asset</th><th>OK</th><th>Peril levels</th><th>Events available</th><th>Profile id</th>' +
            '</tr></thead><tbody>';
        (data.results || []).forEach(function (r) {
            var asset = r.asset || {};
            var siteLabel = asset.name || (asset.lat + ', ' + asset.lon);
            var levels = Object.keys(r.peril_levels || {}).map(function (h) {
                return esc(h) + ': ' + esc(r.peril_levels[h]);
            }).join(', ') || '—';
            html += '<tr>' +
                '<td>' + esc(siteLabel) + '</td>' +
                '<td>' + (r.ok ? '<span class="chip chip-observed">YES</span>' : '<span class="chip chip-error">NO</span>') + '</td>' +
                '<td>' + levels + '</td>' +
                '<td>' + esc(r.events_available_count) + '</td>' +
                '<td>' + esc(r.profile_id || '—') + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        html += '<p class="muted small" style="margin-top:10px;">' +
            'Full record: <a class="text-link" href="' + esc(API + '/v2/insurance/portfolio/' + data.portfolio_id) + '" target="_blank" rel="noopener">JSON →</a>' +
            '</p>';
        html += '</div>';
        el('portfolioResult').innerHTML = html;
    }

    function assessPortfolio() {
        var parsed = parseAssets(el('portfolioText').value);
        if (parsed.error) {
            renderStatus('portfolioStatus', 'error', esc(parsed.error));
            return;
        }
        if (!parsed.assets.length) {
            renderStatus('portfolioStatus', 'error', 'Enter at least one asset.');
            return;
        }
        var radius = getRadius('portfolioRadiusInput');
        if (radius === null) {
            renderStatus('portfolioStatus', 'error', 'Radius must be between 1 and 500 km.');
            return;
        }
        var payload = {
            name: el('portfolioName').value.trim() || null,
            assets: parsed.assets,
            radius_km: radius,
        };

        clearStatus('portfolioStatus');
        renderStatus('portfolioStatus', 'info', 'Running portfolio check…');
        el('assessPortfolioBtn').disabled = true;

        fetchJSON(API + '/v2/insurance/portfolio', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('assessPortfolioBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                handleAuthError(res, 'portfolioStatus');
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('portfolioStatus', 'error', esc(res.body.error || 'Portfolio check failed'));
                return;
            }
            clearStatus('portfolioStatus');
            renderPortfolio(res.body);
        }).catch(function () {
            el('assessPortfolioBtn').disabled = false;
            renderStatus('portfolioStatus', 'error', 'The service could not be reached.');
        });
    }

    function init() {
        el('assessAssetBtn').addEventListener('click', assessAsset);
        el('assessPortfolioBtn').addEventListener('click', assessPortfolio);
        if (window.HS && HS.location) {
            HS.location.enhance('assetLocInput', 'assetLocAssist');
        }

        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q && el('assetLocInput')) el('assetLocInput').value = q;
    }

    init();
})();
