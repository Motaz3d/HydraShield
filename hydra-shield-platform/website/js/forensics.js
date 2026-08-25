/* Talaix — Environmental Forensic Verification page (forensics.html).
 *
 * Builds Environmental Forensic Evidence Packs: satellite × land cover × fire.
 * Conventions match insurance.js / supplychain.js.
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

    function resultClass(result) {
        if (result === 'consistent') return 'chip-observed';
        if (result === 'inconsistent') return 'chip-error';
        return 'chip-unknown';
    }

    function resultChip(result) {
        return '<span class="chip ' + resultClass(result) + '">' + esc(result) + '</span>';
    }

    function parseDocs(text) {
        var docs = [];
        var lines = text.split(/\r?\n/);
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (!line) continue;
            var idx = line.indexOf(',');
            var title, url;
            if (idx >= 0) {
                title = line.slice(0, idx).trim();
                url = line.slice(idx + 1).trim();
            } else {
                title = line;
                url = '';
            }
            if (title || url) docs.push({ title: title || 'Untitled', url: url });
        }
        return docs;
    }

    function buildPayload() {
        var radius = parseFloat(el('caseRadiusInput').value);
        if (isNaN(radius) || radius < 1 || radius > 200) {
            return { error: 'Radius must be between 1 and 200 km.' };
        }
        var typology = el('caseTypology').value;
        var claimType = el('caseClaimType').value;
        var claimText = el('caseClaimText').value.trim() || null;
        var siteInput = el('caseSiteInput').value.trim();
        if (!siteInput) return { error: 'Enter a site location.' };

        var site = null;
        var parts = siteInput.split(',').map(function (s) { return s.trim(); });
        if (parts.length === 2 && !isNaN(parseFloat(parts[0])) && !isNaN(parseFloat(parts[1]))) {
            site = { lat: parseFloat(parts[0]), lon: parseFloat(parts[1]) };
        } else {
            site = { address: siteInput };
        }

        var docs = parseDocs(el('caseDocs').value);
        return {
            title: el('caseTitle').value.trim() || null,
            typology: typology,
            site: site,
            subject_claim: { type: claimType, text: claimText },
            radius_km: radius,
            reference_documents: docs.length ? docs : undefined,
        };
    }

    function renderEvidenceRecords(records) {
        if (!records || !records.length) return '<p class="muted small">No evidence records.</p>';
        var html = '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Evidence ID</th><th>Source</th><th>Dataset</th><th>Acquired</th><th>Content hash</th>' +
            '</tr></thead><tbody>';
        records.forEach(function (rec) {
            html += '<tr>' +
                '<td><code>' + esc(rec.evidence_id) + '</code></td>' +
                '<td>' + esc(rec.source || '—') + '</td>' +
                '<td>' + esc(rec.dataset || '—') + '</td>' +
                '<td>' + esc(rec.acquired_at || '—') + '</td>' +
                '<td><code>' + esc(rec.content_hash || '—') + '</code></td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    function renderCase(data) {
        var payload = data.payload || {};
        var html = '';

        html += '<div class="panel"><h3>Case result</h3>';
        html += '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Case ID</th><td>' + esc(data.case_id) + '</td></tr>' +
            '<tr><th>Title</th><td>' + esc(payload.title || '—') + '</td></tr>' +
            '<tr><th>Typology</th><td>' + esc((payload.typology || {}).label) + '</td></tr>' +
            '<tr><th>Site</th><td>' + esc((payload.site || {}).lat) + ', ' + esc((payload.site || {}).lon) + '</td></tr>' +
            '<tr><th>Generated</th><td>' + esc(payload.generated_at) + '</td></tr>' +
            '<tr><th>Case verdict</th><td>' + resultChip(payload.case_verdict) + '</td></tr>' +
            '</table></div>';
        html += '<p class="muted small"><strong>Verdict note:</strong> ' + esc(payload.verdict_note) + '</p>';
        html += '</div>';

        html += '<div class="panel"><h3>Consistency matrix</h3>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Check</th><th>Result</th><th>Basis</th>' +
            '</tr></thead><tbody>';
        (payload.checks || []).forEach(function (c) {
            html += '<tr>' +
                '<td>' + esc(c.check) + '</td>' +
                '<td>' + resultChip(c.result) + '</td>' +
                '<td>' + esc(c.basis);
            if ((c.caveats || []).length) {
                html += '<br><span class="muted small">' + c.caveats.map(esc).join(' ') + '</span>';
            }
            html += '</td></tr>';
        });
        html += '</tbody></table></div></div>';

        html += '<div class="panel"><h3>Evidence bundle</h3>';
        var bundle = payload.evidence_bundle || {};
        ['landcover', 'satellite', 'active_fires'].forEach(function (layer) {
            var block = bundle[layer] || {};
            html += '<details class="expander">';
            html += '<summary><strong>' + esc(layer) + '</strong></summary>';
            html += '<div style="padding:10px 0;">';
            if (block.error) {
                html += '<p class="muted small">Unavailable: ' + esc(block.error) + '</p>';
            } else if (layer === 'landcover') {
                html += '<p class="muted small">Dominant: ' + esc(block.dominant_label) +
                    ' (' + esc(block.dominant_fraction) + ') · source ' + esc(block.source) + '</p>';
            } else if (layer === 'satellite') {
                html += '<p class="muted small">NDVI ' + esc(block.ndvi) +
                    ' · NDMI ' + esc(block.ndmi) + ' · observation ' + esc(block.observation_date) + '</p>';
            } else if (layer === 'active_fires') {
                html += '<p class="muted small">' + esc(block.count || 0) + ' detection(s) within ' +
                    esc(block.radius_km) + ' km / ' + esc(block.days) + ' days · sensor ' + esc(block.sensor) + '</p>';
            }
            html += '</div></details>';
        });
        html += '</div>';

        html += '<div class="panel"><h3>Chain of custody</h3>';
        html += renderEvidenceRecords(((payload.chain_of_custody || {}).evidence_records || []));
        html += '</div>';

        html += '<div class="panel"><h3>Declared data gaps</h3>';
        if ((payload.declared_gaps || []).length) {
            html += '<div class="notice notice-warn">';
            payload.declared_gaps.forEach(function (g) {
                html += '<strong>' + esc(g.dataset || g.type) + '</strong> — ' + esc(g.reason) + '<br>';
            });
            html += '</div>';
        } else {
            html += '<div class="notice notice-info">No declared data gaps.</div>';
        }
        html += '</div>';

        html += '<div class="panel notice notice-warn"><h3>Disclaimer</h3>' +
            '<p>' + esc(payload.disclaimer) + '</p></div>';

        html += '<div class="panel">' +
            '<a class="text-link" href="' + esc(API + '/v2/forensics/cases/' + data.case_id) + '" target="_blank" rel="noopener">Stored JSON record →</a>' +
            '</div>';

        el('caseResult').innerHTML = html;
    }

    function handleAuthError(res) {
        var upgrade = (res.body || {}).upgrade;
        var msg = 'Please <a class="text-link" href="account.html">sign in</a>';
        if (upgrade && upgrade.required_role) {
            msg += ' or upgrade to the <strong>' + esc(upgrade.required_role) + '</strong> tier';
        }
        msg += ' to open forensic cases.';
        renderStatus('caseStatus', 'warn', msg);
    }

    function assessCase() {
        var payload = buildPayload();
        if (payload.error) {
            renderStatus('caseStatus', 'error', esc(payload.error));
            return;
        }
        clearStatus('caseStatus');
        renderStatus('caseStatus', 'info', 'Building evidence pack…');
        el('assessCaseBtn').disabled = true;

        fetchJSON(API + '/v2/forensics/cases', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('assessCaseBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                handleAuthError(res);
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('caseStatus', 'error', esc(res.body.error || 'Case assessment failed'));
                return;
            }
            clearStatus('caseStatus');
            renderCase(res.body);
        }).catch(function () {
            el('assessCaseBtn').disabled = false;
            renderStatus('caseStatus', 'error', 'The service could not be reached.');
        });
    }

    function downloadPdf() {
        var payload = buildPayload();
        if (payload.error) {
            renderStatus('caseStatus', 'error', esc(payload.error));
            return;
        }
        clearStatus('caseStatus');
        renderStatus('caseStatus', 'info', 'Building PDF…');
        el('downloadCasePdfBtn').disabled = true;

        fetch(API + '/v2/forensics/cases/pdf', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            el('downloadCasePdfBtn').disabled = false;
            if (!res.ok) {
                return res.json().then(function (body) {
                    renderStatus('caseStatus', 'error', esc(body.error || 'PDF generation failed'));
                }, function () {
                    renderStatus('caseStatus', 'error', 'PDF generation failed');
                });
            }
            return res.blob().then(function (blob) {
                clearStatus('caseStatus');
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                a.download = 'talaix_forensics_case.pdf';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
            });
        }).catch(function () {
            el('downloadCasePdfBtn').disabled = false;
            renderStatus('caseStatus', 'error', 'The service could not be reached.');
        });
    }

    function loadFrameworks() {
        fetchJSON(API + '/v2/forensics/frameworks').then(function (res) {
            if (!res.ok || !res.body) return;
            var data = res.body;
            var typSel = el('caseTypology');
            data.typologies.forEach(function (t) {
                var opt = document.createElement('option');
                opt.value = t.id;
                opt.textContent = t.label;
                typSel.appendChild(opt);
            });
            var claimSel = el('caseClaimType');
            data.claim_types.forEach(function (c) {
                var opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.label;
                claimSel.appendChild(opt);
            });

            var cards = el('typologyCards');
            var html = '';
            data.typologies.forEach(function (t) {
                html += '<div class="item-card">' +
                    '<h3>' + esc(t.label) + '</h3>' +
                    '<span class="chip chip-documented">' + esc(t.id) + '</span>' +
                    '<p class="muted">' + esc(t.note) + '</p></div>';
            });
            data.frameworks.forEach(function (f) {
                html += '<div class="item-card">' +
                    '<h3>' + esc(f.name) + '</h3>' +
                    '<span class="chip chip-modelled">' + esc(f.role) + '</span>' +
                    '<p class="muted">' + esc(f.note) + '</p></div>';
            });
            cards.innerHTML = html;
        });
    }

    function init() {
        el('assessCaseBtn').addEventListener('click', assessCase);
        el('downloadCasePdfBtn').addEventListener('click', downloadPdf);
        if (window.HS && HS.location) {
            HS.location.enhance('caseSiteInput', 'caseSiteAssist');
        }

        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q && el('caseSiteInput')) el('caseSiteInput').value = q;

        loadFrameworks();
    }

    init();
})();
