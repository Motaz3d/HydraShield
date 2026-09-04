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

    function generateReport(asPdf) {
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
        el('generateReportBtn').disabled = true;
        el('downloadPdfBtn').disabled = true;

        resolveSites(parsed.items).then(function (res) {
            if (res.error) {
                el('generateReportBtn').disabled = false;
                el('downloadPdfBtn').disabled = false;
                renderStatus('error', esc(res.error));
                return;
            }
            submitReport(asPdf, { company: company, assets: res.assets });
        });
    }

    function submitReport(asPdf, payload) {
        clearStatus();
        renderStatus('info', 'Building sustainability evidence report…');

        var endpoint = asPdf ? API + '/v2/sustainability/report/pdf' : API + '/v2/sustainability/report';

        if (asPdf) {
            fetch(endpoint, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }).then(function (r) {
                el('generateReportBtn').disabled = false;
                el('downloadPdfBtn').disabled = false;
                if (r.status === 401 || r.status === 403) {
                    return r.json().then(function (body) {
                        handleAuthError({ ok: r.ok, status: r.status, body: body });
                    });
                }
                if (!r.ok) {
                    return r.json().then(function (body) {
                        renderStatus('error', esc(body.error || 'PDF generation failed'));
                    }).catch(function () {
                        renderStatus('error', 'PDF generation failed');
                    });
                }
                return r.blob().then(function (blob) {
                    var url = URL.createObjectURL(blob);
                    var a = document.createElement('a');
                    a.href = url;
                    a.download = 'talaix_sustainability_' + (payload.company.name || 'report').replace(/\W+/g, '_') + '.pdf';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);
                    clearStatus();
                });
            }).catch(function () {
                el('generateReportBtn').disabled = false;
                el('downloadPdfBtn').disabled = false;
                renderStatus('error', 'The reporting service could not be reached.');
            });
            return;
        }

        fetchJSON(endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('generateReportBtn').disabled = false;
            el('downloadPdfBtn').disabled = false;
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
            el('generateReportBtn').disabled = false;
            el('downloadPdfBtn').disabled = false;
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

    function init() {
        el('generateReportBtn').addEventListener('click', function () { generateReport(false); });
        el('downloadPdfBtn').addEventListener('click', function () { generateReport(true); });
        loadFrameworks();
    }

    init();
})();
