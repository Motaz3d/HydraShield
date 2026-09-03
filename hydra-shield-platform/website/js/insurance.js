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

    function pct(x, digits) {
        if (x === null || x === undefined) return '—';
        return (x * 100).toFixed(digits === undefined ? 1 : digits) + '%';
    }

    function _primarySeverityMetric(sev) {
        if (!sev || !sev.metrics) return null;
        var keys = Object.keys(sev.metrics);
        if (!keys.length) return null;
        keys.sort(function (a, b) {
            var A = sev.metrics[a], B = sev.metrics[b];
            return (B.n - A.n) || (B.mean - A.mean);
        });
        return { key: keys[0], stats: sev.metrics[keys[0]] };
    }

    function renderPerilActuarial(act) {
        if (!act) return '';
        var html = '<p class="muted small" style="margin-top:8px;"><strong>Actuarial screening:</strong></p>';
        if (act.status !== 'ok') {
            return html + '<p class="muted small">Unavailable: ' + esc(act.unavailable_reason || 'no actuarial estimate.') + '</p>';
        }
        var f = act.frequency || {};
        html += '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Annual frequency λ̂</th><td>' + esc(f.lambda_per_year) +
            ' <span class="muted small">(90% CI ' + esc(f.ci_lower) + '–' + esc(f.ci_upper) + ' · ' + esc(f.tier) + ')</span></td></tr>' +
            '<tr><th>Annual exceedance probability</th><td>' + pct(act.annual_exceedance_probability) +
            ' <span class="muted small">(upper bound ' + pct(act.annual_exceedance_probability_ci_upper) + ')</span></td></tr>' +
            '<tr><th>Return period</th><td>' + (act.return_period_years != null ? esc(act.return_period_years) + ' years' : '—') + '</td></tr>' +
            '<tr><th>Horizon probabilities</th><td>' +
            '5y ' + pct((act.horizon_probabilities || {})['5y'], 0) + ' · ' +
            '10y ' + pct((act.horizon_probabilities || {})['10y'], 0) + ' · ' +
            '25y ' + pct((act.horizon_probabilities || {})['25y'], 0) + '</td></tr>' +
            '</table></div>';

        var sev = act.severity || {};
        var primary = _primarySeverityMetric(sev);
        if (primary) {
            html += '<p class="muted small"><strong>Severity (' + esc(primary.key) + '):</strong> ' +
                'n=' + esc(primary.stats.n) + ', mean=' + esc(primary.stats.mean) +
                ', max=' + esc(primary.stats.max) + ', cv=' + esc(primary.stats.cv) +
                ' <span class="muted">(dataset units, non-monetary)</span></p>';
        }
        if (act.severity_fit && act.severity_fit.status === 'ok') {
            var fitLine = act.severity_fit.fits.map(function (f) {
                return esc(f.distribution) + ' (AIC ' + esc(f.aic) + ', KS ' + esc(f.ks_statistic) + ')';
            }).join(' · ');
            html += '<p class="muted small"><strong>Severity fit:</strong> ' + fitLine +
                ' — preferred: <strong>' + esc(act.severity_fit.preferred) + '</strong> (lowest AIC)</p>';
        }
        if (act.trend) {
            if (act.trend.status === 'ok') {
                html += '<p class="muted small"><strong>Frequency trend:</strong> ' + esc(act.trend.direction) +
                    ' — ×' + esc(act.trend.annual_multiplier) + '/yr (p=' + esc(act.trend.p_value) + '); ' +
                    'λ at latest record year ' + esc(act.trend.lambda_current_year) +
                    ' vs record average ' + esc(act.trend.lambda_average) + '</p>';
            } else {
                html += '<p class="muted small"><strong>Frequency trend:</strong> unavailable — ' +
                    esc(act.trend.unavailable_reason || '') + '</p>';
            }
        }
        if (act.collective_risk && act.collective_risk.expected_annual_index != null) {
            html += '<p class="muted small"><strong>Collective risk (compound Poisson):</strong> ' +
                'E[S]=' + esc(act.collective_risk.expected_annual_index) + ', σ(S)=' + esc(act.collective_risk.std_annual_index) +
                ' <span class="muted">(' + esc(act.collective_risk.unit) + ')</span></p>';
        }
        (act.notes || []).forEach(function (n) {
            html += '<p class="muted small"><em>' + esc(n) + '</em></p>';
        });
        (act.assumptions || []).forEach(function (a) {
            html += '<p class="muted small"><em>Assumption: ' + esc(a) + '</em></p>';
        });
        return html;
    }

    function renderActuarialAccount(profile) {
        var a = profile.actuarial_summary;
        if (!a) return '';
        var html = '<div class="panel"><h3>Actuarial screening</h3>';
        if (a.text) html += '<p class="muted small">' + esc(a.text) + '</p>';

        var ins = a.insurability || {};
        if (ins.status === 'ok') {
            html += '<p style="margin:6px 0;"><strong>Insurability screen:</strong> ' + chip(ins.attention_band) +
                ' <span class="muted small">attention score ' + esc(ins.attention_score) + '/100 · ' +
                'confidence ' + esc(ins.confidence) + ' · data adequacy ' + pct(ins.data_adequacy, 0) + '</span><br>' +
                '<span class="muted small">' + esc(ins.band_meaning) + ' ' + esc(ins.note || '') + '</span></p>';
        } else if (ins.unavailable_reason) {
            html += '<p class="muted small">Insurability screen unavailable: ' + esc(ins.unavailable_reason) + '</p>';
        }

        var trends = a.significant_trends || {};
        if (Object.keys(trends).length) {
            html += '<p class="muted small"><strong>Significant frequency trends (p&lt;0.05):</strong> ' +
                Object.keys(trends).map(function (h) {
                    return esc(h) + ' ' + esc(trends[h].direction) + ' (×' + esc(trends[h].annual_multiplier) + '/yr)';
                }).join('; ') + '.</p>';
        }

        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Peril</th><th>λ̂ /yr (90% CI)</th><th>Tier</th><th>AEP</th><th>Return period</th>' +
            '<th>10-yr horizon</th><th>Trend</th><th>Severity mean</th><th>E[S] /yr</th>' +
            '</tr></thead><tbody>';
        (profile.perils || []).forEach(function (p) {
            var act = p.actuarial || {};
            if (act.status !== 'ok') {
                html += '<tr><td>' + esc(p.peril) + '</td><td colspan="8">' +
                    chip(act.status || 'unavailable') + ' <span class="muted small">' +
                    esc(act.unavailable_reason || '') + '</span></td></tr>';
                return;
            }
            var f = act.frequency || {};
            var trendCell = '<span class="muted">n/a</span>';
            if (act.trend && act.trend.status === 'ok') {
                trendCell = esc(act.trend.direction) + ' ×' + esc(act.trend.annual_multiplier);
            }
            var primary = _primarySeverityMetric(act.severity || {});
            var sevCell = primary ? esc(primary.stats.mean) + ' <span class="muted small">' + esc(primary.key) + '</span>' : '—';
            var esCell = (act.collective_risk && act.collective_risk.expected_annual_index != null)
                ? esc(act.collective_risk.expected_annual_index) : '—';
            html += '<tr>' +
                '<td>' + esc(p.peril) + '</td>' +
                '<td>' + esc(f.lambda_per_year) + ' <span class="muted small">(' + esc(f.ci_lower) + '–' + esc(f.ci_upper) + ')</span></td>' +
                '<td>' + esc(f.tier) + '</td>' +
                '<td>' + pct(act.annual_exceedance_probability) + '</td>' +
                '<td>' + (act.return_period_years != null ? esc(act.return_period_years) + ' yrs' : '—') + '</td>' +
                '<td>' + pct((act.horizon_probabilities || {})['10y'], 0) + '</td>' +
                '<td>' + trendCell + '</td>' +
                '<td>' + sevCell + '</td>' +
                '<td>' + esCell + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';

        var caveats = (a.assumptions || []).concat(a.independence_caveat ? [a.independence_caveat] : []);
        if (caveats.length) {
            html += '<details class="expander" style="margin-top:8px;"><summary><strong>Assumptions &amp; caveats</strong></summary><ul class="muted small">';
            caveats.forEach(function (c) { html += '<li>' + esc(c) + '</li>'; });
            html += '</ul></details>';
        }
        html += renderActuarialReference(profile.actuarial_reference);
        html += '</div>';
        return html;
    }

    function renderActuarialReference(ref) {
        if (!ref) return '';
        var html = '<details class="expander" style="margin-top:8px;">' +
            '<summary><strong>Actuarial reference — formulas &amp; terminology (EN / AR)</strong> ' +
            '<span class="muted small">' + esc(ref.formula_count) + ' formulas · ' + esc(ref.term_count) + ' terms</span></summary>';
        html += '<p class="muted small">' + esc(ref.note || '') + '</p>';
        html += '<h4>Formulas</h4><div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Name</th><th>الاسم</th><th>Formula</th><th>Use</th></tr></thead><tbody>';
        (ref.formulas || []).forEach(function (f) {
            html += '<tr><td>' + esc(f.name_en) + '</td><td>' + esc(f.name_ar) + '</td>' +
                '<td><code>' + esc(f.formula) + '</code></td><td class="muted small">' + esc(f.use_en) + '</td></tr>';
        });
        html += '</tbody></table></div>';
        html += '<h4>Terminology</h4><div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Category</th><th>Term</th><th>المصطلح</th><th>Definition</th><th>التعريف</th></tr></thead><tbody>';
        (ref.glossary || []).forEach(function (t) {
            var cat = (ref.categories && ref.categories[t.category]) || {};
            html += '<tr><td class="muted small">' + esc(cat.en || t.category) + '</td>' +
                '<td>' + esc(t.term_en) + '</td><td>' + esc(t.term_ar) + '</td>' +
                '<td class="muted small">' + esc(t.def_en) + '</td>' +
                '<td class="muted small">' + esc(t.def_ar) + '</td></tr>';
        });
        html += '</tbody></table></div></details>';
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

        html += renderActuarialAccount(profile);

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
            html += renderPerilActuarial(p.actuarial);
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
        var pact = ps.actuarial || {};
        if (pact.sites_with_quantified_perils !== undefined) {
            html += '<p class="muted small"><strong>Actuarial screen:</strong> ' +
                esc(pact.sites_with_quantified_perils) + ' site(s) with quantified perils' +
                (pact.any_site_any_peril_aep != null
                    ? ' · any-site/any-peril AEP ' + (pact.any_site_any_peril_aep * 100).toFixed(1) + '%'
                    : '') +
                (pact.independence_caveat ? '<br><em>' + esc(pact.independence_caveat) + '</em>' : '') +
                '</p>';
        }
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
            '<th>Asset</th><th>OK</th><th>Peril levels</th><th>Events available</th>' +
            '<th>Any-peril AEP</th><th>Dominant peril</th><th>Profile id</th>' +
            '</tr></thead><tbody>';
        (data.results || []).forEach(function (r) {
            var asset = r.asset || {};
            var siteLabel = asset.name || (asset.lat + ', ' + asset.lon);
            var levels = Object.keys(r.peril_levels || {}).map(function (h) {
                return esc(h) + ': ' + esc(r.peril_levels[h]);
            }).join(', ') || '—';
            var ra = r.actuarial || {};
            var aepCell = ra.any_peril_annual_exceedance_probability != null
                ? (ra.any_peril_annual_exceedance_probability * 100).toFixed(1) + '%' : '—';
            var domCell = (ra.dominant_peril && ra.dominant_peril.hazard)
                ? esc(ra.dominant_peril.hazard) : '—';
            html += '<tr>' +
                '<td>' + esc(siteLabel) + '</td>' +
                '<td>' + (r.ok ? '<span class="chip chip-observed">YES</span>' : '<span class="chip chip-error">NO</span>') + '</td>' +
                '<td>' + levels + '</td>' +
                '<td>' + esc(r.events_available_count) + '</td>' +
                '<td>' + aepCell + '</td>' +
                '<td>' + domCell + '</td>' +
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
