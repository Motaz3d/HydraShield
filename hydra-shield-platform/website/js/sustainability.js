/* Talaix — Sustainability & CSRD Reporting page (sustainability.html).
 *
 * Builds a CSRD/ESRS-oriented evidence pack from a company profile + site list.
 * Reuses the same physical verification engine as Green Finance Verification.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function renderStatus(kind, html) {
        el('reportStatus').innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function clearStatus() {
        el('reportStatus').innerHTML = '';
    }

    function looksLikeUrl(text) {
        return /^(https?:\/\/|www\.)/i.test(text) ||
            /^[\w-]+(\.[\w-]+)*\.[a-z]{2,}(\/\S*)?$/i.test(text);
    }

    /* Sites, one per line: "name,lat,lon", "lat,lon", or a place name
     * ("Trier, Germany" / "Trier factory, Trier, Germany") resolved through
     * the platform geocoder. Numeric entries become assets immediately;
     * place-name entries keep {place, lineNo} for resolveSites(). */
    function parseAssets(text) {
        var items = [];
        var lines = text.split(/\r?\n/);
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (!line) continue;
            var parts = line.split(',').map(function (s) { return s.trim(); });
            var name = null, place = null, lat = NaN, lon = NaN;
            if (parts.length >= 3) {
                lat = parseFloat(parts[1]);
                lon = parseFloat(parts[2]);
                if (!isNaN(lat) && !isNaN(lon)) {
                    items.push({ name: parts[0], lat: lat, lon: lon });
                    continue;
                }
                name = parts[0];
                place = parts.slice(1).join(', ');
            } else if (parts.length === 2) {
                lat = parseFloat(parts[0]);
                lon = parseFloat(parts[1]);
                if (!isNaN(lat) && !isNaN(lon)) {
                    items.push({ name: null, lat: lat, lon: lon });
                    continue;
                }
                place = line;
            } else {
                place = line;
            }
            if (looksLikeUrl(place)) {
                return { error: 'Line ' + (i + 1) + ' (“' + line + '”) looks like a web address. ' +
                    'Sites are physical locations — enter a place name (e.g. “Trier, Germany”) ' +
                    'or name,lat,lon coordinates. The company web address goes in the Website field.' };
            }
            items.push({ name: name, place: place, lineNo: i + 1 });
        }
        return { items: items };
    }

    function geocodeSite(place) {
        return fetchJSON(API + '/geocode?location=' + encodeURIComponent(place))
            .then(function (res) {
                var loc = res.body && res.body.location;
                if (res.ok && loc && loc.lat != null && loc.lon != null) {
                    return { ok: true, lat: loc.lat, lon: loc.lon, name: loc.name || place };
                }
                return { ok: false, error: (res.body && res.body.error) || 'Location could not be resolved.' };
            })
            .catch(function () {
                return { ok: false, error: 'The geocoding service could not be reached.' };
            });
    }

    /* Sequential on purpose: the geocoder is rate-limited. */
    function resolveSites(items) {
        var assets = [];
        var idx = 0;
        function next() {
            if (idx >= items.length) return Promise.resolve({ assets: assets });
            var item = items[idx++];
            if (item.place == null) {
                assets.push({ name: item.name, lat: item.lat, lon: item.lon });
                return next();
            }
            return geocodeSite(item.place).then(function (res) {
                if (!res.ok) {
                    return { error: 'Line ' + item.lineNo + ' (“' + item.place + '”) could not be ' +
                        'resolved to a place. Try a more specific name (city, country) or use ' +
                        'name,lat,lon coordinates.' };
                }
                assets.push({ name: item.name || res.name, lat: res.lat, lon: res.lon });
                return next();
            });
        }
        return next();
    }

    function handleAuthError(res) {
        var upgrade = (res.body || {}).upgrade;
        var msg = 'Please <a class="text-link" href="account.html">sign in</a>';
        if (upgrade && upgrade.required_role) {
            msg += ' or upgrade to the <strong>' + esc(upgrade.required_role) + '</strong> tier';
        }
        msg += ' to generate sustainability reports.';
        renderStatus('warn', msg);
    }

    function renderCoverageMap(coverage) {
        var html = '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Area</th><th>Ref</th><th>Coverage</th><th>Note</th>' +
            '</tr></thead><tbody>';
        coverage.forEach(function (item) {
            var statusChip;
            if (item.coverage === 'covered_by_evidence') statusChip = chip('observed', 'COVERED');
            else if (item.coverage === 'partial') statusChip = chip('modelled', 'PARTIAL');
            else statusChip = chip('unknown', 'NOT COVERED');
            html += '<tr>' +
                '<td>' + esc(item.area) + '</td>' +
                '<td>' + esc(item.ref) + '</td>' +
                '<td>' + statusChip + '</td>' +
                '<td>' + esc(item.note) + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    function renderEvidenceStandard(std) {
        var html = '<div class="panel"><h3>Talaix Evidence Standard</h3><ul class="muted">';
        (std.criteria || []).forEach(function (c) {
            html += '<li>' + esc(c) + '</li>';
        });
        html += '</ul><p class="notice notice-warn"><strong>' + esc(std.not_accreditation) + '</strong></p></div>';
        return html;
    }

    function renderReport(data) {
        var html = '<div class="panel"><h3>Report: ' + esc((data.company.fields || {}).name) + '</h3>';
        html += '<p class="muted small">Report ID: <code>' + esc(data.report_id) + '</code> · ' +
            'Generated: ' + esc(data.generated_at) + '</p>';

        html += '<h4>Portfolio summary</h4>';
        var ps = data.portfolio_summary || {};
        html += '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Sites analysed</th><td>' + esc(ps.site_count) + '</td></tr>' +
            '<tr><th>Sites with real data</th><td>' + esc(ps.ok_count) + '</td></tr>' +
            '<tr><th>Total declared gaps</th><td>' + esc(ps.total_declared_gaps) + '</td></tr>' +
            '</table></div>';

        html += '<h4>Per-site results</h4>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Site</th><th>OK</th><th>Top hazard levels</th><th>Verification id</th>' +
            '</tr></thead><tbody>';
        (data.site_results || []).forEach(function (r) {
            var asset = r.asset || {};
            var siteLabel = asset.name || (asset.lat + ', ' + asset.lon);
            var levels = Object.keys(r.hazard_levels || {}).map(function (h) {
                return esc(h) + ': ' + esc(r.hazard_levels[h]);
            }).join(', ') || '—';
            html += '<tr>' +
                '<td>' + esc(siteLabel) + '</td>' +
                '<td>' + (r.ok ? '<span class="chip chip-observed">YES</span>' : '<span class="chip chip-error">NO</span>') + '</td>' +
                '<td>' + levels + '</td>' +
                '<td>' + esc(r.verification_id || '—') + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';

        html += '<h4>Declared data gaps</h4>';
        if ((data.declared_gaps || []).length) {
            html += '<div class="notice notice-warn">';
            data.declared_gaps.forEach(function (g) {
                html += '<strong>' + esc(g.site) + '</strong> — ' + esc(g.taxonomy_label || g.hazard) + ': ' + esc(g.reason) + '<br>';
            });
            html += '</div>';
        } else {
            html += '<div class="notice notice-info">No declared data gaps across the portfolio.</div>';
        }

        html += '<h4>Disclosure coverage map</h4>';
        html += renderCoverageMap(data.coverage_map || []);

        html += '</div>';
        html += renderEvidenceStandard(data.evidence_standard || {});
        html += '<p class="muted small">Full record: <a class="text-link" href="' + esc(API + '/v2/sustainability/report/' + data.report_id) + '" target="_blank" rel="noopener">JSON →</a></p>';
        el('reportResult').innerHTML = html;
    }

    function generateReport(mode) {
        var company = {
            name: el('companyName').value.trim(),
            sector: el('companySector').value.trim() || null,
            country: el('companyCountry').value.trim() || null,
            website: el('companyWebsite').value.trim() || null,
            description: el('companyDescription').value.trim() || null,
        };
        if (!company.name) {
            renderStatus('error', 'Company name is required.');
            return;
        }
        var parsed = parseAssets(el('assetsText').value);
        if (parsed.error) {
            renderStatus('error', esc(parsed.error));
            return;
        }
        if (!parsed.items.length) {
            renderStatus('error', 'Enter at least one site — a place name (e.g. “Trier, Germany”) ' +
                'or name,lat,lon coordinates, one per line.');
            return;
        }

        clearStatus();
        renderStatus('info', 'Resolving site names…');
        setButtonsDisabled(true);

        resolveSites(parsed.items).then(function (res) {
            if (res.error) {
                setButtonsDisabled(false);
                renderStatus('error', esc(res.error));
                return;
            }
            submitReport(mode, { company: company, assets: res.assets });
        });
    }

    function setButtonsDisabled(disabled) {
        ['generateReportBtn', 'downloadPdfBtn', 'downloadXbrlBtn', 'downloadIxbrlBtn'].forEach(function (id) {
            el(id).disabled = disabled;
        });
    }

    function downloadBlob(blob, filename) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    function submitReport(mode, payload) {
        clearStatus();
        renderStatus('info', 'Building sustainability evidence report…');

        var endpoint, body = payload, downloadName = null;
        if (mode === 'pdf') {
            endpoint = API + '/v2/sustainability/report/pdf';
            downloadName = 'talaix_sustainability_' + (payload.company.name || 'report').replace(/\W+/g, '_') + '.pdf';
        } else if (mode === 'xbrl' || mode === 'ixbrl') {
            endpoint = API + '/v2/csrd/assessment/xbrl';
            body = { company: payload.company, assets: payload.assets, format: mode };
            downloadName = 'talaix_csrd_' + (payload.company.name || 'assessment').replace(/\W+/g, '_') +
                (mode === 'xbrl' ? '.xbrl' : '.xhtml');
        } else {
            endpoint = API + '/v2/sustainability/report';
        }

        if (downloadName) {
            fetch(endpoint, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            }).then(function (r) {
                setButtonsDisabled(false);
                if (r.status === 401 || r.status === 403) {
                    return r.json().then(function (body) {
                        handleAuthError({ ok: r.ok, status: r.status, body: body });
                    });
                }
                if (!r.ok) {
                    return r.json().then(function (body) {
                        renderStatus('error', esc(body.error || 'Report generation failed'));
                    }).catch(function () {
                        renderStatus('error', 'Report generation failed');
                    });
                }
                return r.blob().then(function (blob) {
                    downloadBlob(blob, downloadName);
                    clearStatus();
                });
            }).catch(function () {
                setButtonsDisabled(false);
                renderStatus('error', 'The reporting service could not be reached.');
            });
            return;
        }

        fetchJSON(endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).then(function (res) {
            setButtonsDisabled(false);
            if (res.status === 401 || res.status === 403) {
                handleAuthError(res);
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('error', esc(res.body.error || 'Report generation failed'));
                return;
            }
            clearStatus();
            renderReport(res.body);
        }).catch(function () {
            setButtonsDisabled(false);
            renderStatus('error', 'The reporting service could not be reached.');
        });
    }

    function loadFrameworks() {
        fetchJSON(API + '/v2/sustainability/frameworks').then(function (res) {
            if (!res.ok || !res.body.frameworks) {
                el('frameworksArea').innerHTML = '<span class="muted">Frameworks reference unavailable.</span>';
                return;
            }
            var html = '';
            html += '<div class="card-grid">';
            res.body.frameworks.forEach(function (fw) {
                html += '<div class="item-card">' +
                    '<h3>' + esc(fw.name) + '</h3>' +
                    '<span class="chip chip-documented">' + esc(fw.id) + '</span>' +
                    '<p class="muted">' + esc(fw.aspect) + '. ' + esc(fw.note) + '</p>' +
                    '</div>';
            });
            html += '</div>';

            html += '<div class="panel" style="margin-top:24px;">' +
                '<h3>ESRS coverage map</h3>' +
                renderCoverageMap(res.body.coverage_map || []) +
                '</div>';

            html += renderEvidenceStandard(res.body.evidence_standard || {});
            el('frameworksArea').innerHTML = html;
        }).catch(function () {
            el('frameworksArea').innerHTML = '<span class="muted">Frameworks reference could not be reached.</span>';
        });
    }

    /* ---- CsrdTX: applicability check ---- */

    function applStatus(kind, html) {
        el('applStatus').innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function numOrNull(id) {
        var v = el(id).value.trim();
        if (!v) return null;
        var n = Number(v);
        return isNaN(n) ? null : n;
    }

    function determinationChip(det) {
        if (det === 'in_scope') return chip('observed', 'IN SCOPE');
        if (det === 'out_of_scope') return chip('unknown', 'OUT OF SCOPE');
        if (det === 'potentially_in_scope') return chip('modelled', 'POTENTIALLY IN SCOPE');
        return chip('reported', 'REQUIRES LEGAL CONFIRMATION');
    }

    function renderApplicability(data) {
        var html = '<div class="panel"><h3>' + esc((data.company || {}).name || 'Company') + ' — ' +
            'reporting year ' + esc(data.reporting_year) + '</h3>';
        html += '<p>' + determinationChip(data.determination) + ' ' +
            '<span class="muted small">Rule set: ' + esc((data.rule_set || {}).name || '—') +
            ' (' + esc((data.rule_set || {}).status || '') + ')</span></p>';

        if (data.wave) {
            html += '<div class="table-scroll"><table class="kv-table">' +
                '<tr><th>Phase-in wave</th><td>' + esc(data.wave.wave) + '</td></tr>' +
                '<tr><th>Population</th><td>' + esc(data.wave.population) + '</td></tr>' +
                '<tr><th>First reporting year</th><td>' + esc(data.wave.first_reporting_year) + '</td></tr>' +
                '<tr><th>First report due</th><td>' + esc(data.wave.first_report_year) + '</td></tr>' +
                '</table></div>';
        }

        var size = data.size_evaluation || {};
        if (size.criteria) {
            html += '<h4>Size criteria</h4><div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Criterion</th><th>Result</th></tr></thead><tbody>';
            Object.keys(size.criteria).forEach(function (k) {
                html += '<tr><td>' + esc(k) + '</td><td>' + esc(size.criteria[k]) + '</td></tr>';
            });
            html += '</tbody></table></div>';
        }

        if ((data.reasons || []).length) {
            html += '<h4>Reasons</h4><ul class="muted">';
            data.reasons.forEach(function (r) { html += '<li>' + esc(r) + '</li>'; });
            html += '</ul>';
        }
        if ((data.assumptions || []).length) {
            html += '<h4>Declared assumptions</h4><ul class="muted">';
            data.assumptions.forEach(function (a) { html += '<li>' + esc(a) + '</li>'; });
            html += '</ul>';
        }

        var fwd = data.forward_outlook || {};
        if (fwd.rule_set_id) {
            html += '<p class="muted small"><strong>Forward outlook (proposed rules, never applied):</strong> ' +
                'under ' + esc(fwd.rule_set_id) + ' the determination would be ' +
                determinationChip(fwd.determination_if_adopted) + '</p>';
        }
        if (data.voluntary_route) {
            html += '<div class="notice notice-info"><strong>Voluntary route:</strong> ' +
                esc(data.voluntary_route.note) + '</div>';
        }
        html += '<p class="muted small">' + esc(data.honesty_note || '') + '</p></div>';
        el('applResult').innerHTML = html;
    }

    function checkApplicability() {
        var company = {
            name: el('applName').value.trim(),
            country: el('applCountry').value.trim() || null,
            employees: numOrNull('applEmployees'),
            net_turnover_eur: numOrNull('applTurnover'),
            balance_sheet_total_eur: numOrNull('applBalance'),
            reporting_year: numOrNull('applYear'),
        };
        var listed = el('applListed').value;
        if (listed !== '') company.listed = listed === 'true';
        if (!company.name) {
            applStatus('error', 'Company name is required.');
            return;
        }
        el('applStatus').innerHTML = '';
        applStatus('info', 'Evaluating CSRD applicability…');
        el('checkApplicabilityBtn').disabled = true;

        fetchJSON(API + '/v2/csrd/applicability', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ company: company }),
        }).then(function (res) {
            el('checkApplicabilityBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                applStatus('warn', 'Please <a class="text-link" href="account.html">sign in</a> to run the applicability check.');
                return;
            }
            if (!res.ok || res.body.error) {
                applStatus('error', esc(res.body.error || 'Applicability check failed'));
                return;
            }
            el('applStatus').innerHTML = '';
            renderApplicability(res.body);
        }).catch(function () {
            el('checkApplicabilityBtn').disabled = false;
            applStatus('error', 'The applicability service could not be reached.');
        });
    }

    /* ---- CsrdTX: regulatory watch ---- */

    function statusChip(status) {
        if (status === 'in_force') return chip('observed', 'IN FORCE');
        if (status === 'adopted_pending_application') return chip('modelled', 'PENDING APPLICATION');
        if (status === 'proposed') return chip('reported', 'PROPOSED');
        return chip('unknown', esc(status || '—'));
    }

    function loadRegulations() {
        fetchJSON(API + '/v2/csrd/regulations').then(function (res) {
            if (!res.ok || !res.body.esrs_versions) {
                el('regulationsArea').innerHTML = '<span class="muted">Regulatory watch unavailable.</span>';
                return;
            }
            var data = res.body;
            var html = '<p class="muted small">Knowledge base as of ' + esc(data.as_of || '—') + '</p>';

            html += '<h3>ESRS versions</h3><div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Version</th><th>Status</th><th>Adopted</th><th>Source</th>' +
                '</tr></thead><tbody>';
            data.esrs_versions.forEach(function (v) {
                html += '<tr><td>' + esc(v.short_name || v.id) + '</td><td>' + statusChip(v.status) + '</td>' +
                    '<td>' + esc(v.adopted || '—') + '</td><td class="muted small">' + esc(v.source || '—') + '</td></tr>';
            });
            html += '</tbody></table></div>';

            html += '<h3>Phase-in waves</h3><div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Wave</th><th>Population</th><th>First reporting year</th><th>First report</th><th>Status</th>' +
                '</tr></thead><tbody>';
            (data.wave_calendar || []).forEach(function (w) {
                html += '<tr><td>' + esc(w.wave) + '</td><td>' + esc(w.population) + '</td>' +
                    '<td>' + esc(w.first_reporting_year) + '</td><td>' + esc(w.first_report_year) + '</td>' +
                    '<td>' + statusChip(w.status) + '</td></tr>';
            });
            html += '</tbody></table></div>';

            html += '<h3>Change log</h3><div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Date</th><th>Event</th><th>Status</th><th>Summary</th>' +
                '</tr></thead><tbody>';
            (data.changelog || []).forEach(function (e) {
                html += '<tr><td>' + esc(e.date) + '</td><td>' + esc(e.title) + '</td>' +
                    '<td>' + statusChip(e.status) + '</td><td class="muted small">' + esc(e.summary) + '</td></tr>';
            });
            html += '</tbody></table></div>';

            el('regulationsArea').innerHTML = html;
        }).catch(function () {
            el('regulationsArea').innerHTML = '<span class="muted">Regulatory watch could not be reached.</span>';
        });
    }

    function init() {
        el('generateReportBtn').addEventListener('click', function () { generateReport('json'); });
        el('downloadPdfBtn').addEventListener('click', function () { generateReport('pdf'); });
        el('downloadXbrlBtn').addEventListener('click', function () { generateReport('xbrl'); });
        el('downloadIxbrlBtn').addEventListener('click', function () { generateReport('ixbrl'); });
        el('checkApplicabilityBtn').addEventListener('click', checkApplicability);
        loadFrameworks();
        loadRegulations();
    }

    init();
})();
