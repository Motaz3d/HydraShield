/* Talaix — Visual Report Builder page.
 *
 * Automatic links go to existing product pages. Interactive mode builds a
 * deterministic draft from engine data, lets the user edit/reorder sections,
 * and exports a PDF that honestly marks edited sections.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, resolveLocation = HS.resolveLocation, API = HS.API;

    function el(id) { return document.getElementById(id); }

    var draft = null;
    var sections = [];

    function renderStatus(mountId, kind, html) {
        el(mountId).innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function clearStatus(mountId) {
        el(mountId).innerHTML = '';
    }

    function authPrompt(action) {
        return 'Please <a class="text-link" href="account.html">sign in</a> to ' + esc(action) + '.';
    }

    function showPanel(id) {
        el(id).style.display = 'block';
    }

    function hidePanel(id) {
        el(id).style.display = 'none';
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

    function onProductChange() {
        var product = el('productSelect').value;
        hidePanel('locationSetup');
        hidePanel('sustainabilitySetup');
        el('radiusGroup').style.display = 'none';
        if (product === 'verification' || product === 'insurance') {
            showPanel('locationSetup');
            if (product === 'insurance') {
                el('radiusGroup').style.display = '';
            }
        } else if (product === 'sustainability') {
            showPanel('sustainabilitySetup');
        }
    }

    function collectParams() {
        var product = el('productSelect').value;
        if (!product) return { error: 'Choose a product.' };

        if (product === 'verification' || product === 'insurance') {
            var text = el('locationInput').value.trim();
            if (!text) return { error: 'Enter a location.' };
            var direct = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/.exec(text);
            if (direct) {
                var params = {
                    lat: parseFloat(direct[1]),
                    lon: parseFloat(direct[2]),
                    name: null,
                };
                if (product === 'insurance') {
                    params.radius_km = parseFloat(el('radiusInput').value) || 50;
                }
                return { product: product, params: params };
            }
            return { product: product, resolve: text };
        }

        if (product === 'sustainability') {
            var company = {
                name: el('companyName').value.trim(),
                sector: el('companySector').value.trim() || null,
                country: el('companyCountry').value.trim() || null,
                website: el('companyWebsite').value.trim() || null,
                description: el('companyDescription').value.trim() || null,
            };
            if (!company.name) return { error: 'Company name is required.' };
            var parsed = parseAssets(el('assetsText').value);
            if (parsed.error) return { error: parsed.error };
            if (!parsed.items.length) {
                return { error: 'Enter at least one site — a place name (e.g. “Trier, Germany”) ' +
                    'or name,lat,lon coordinates, one per line.' };
            }
            return { product: 'sustainability', company: company, items: parsed.items };
        }

        return { error: 'Unknown product.' };
    }

    function generateDraft() {
        var spec = collectParams();
        if (spec.error) {
            renderStatus('setupStatus', 'error', esc(spec.error));
            return;
        }

        if (spec.resolve) {
            clearStatus('setupStatus');
            renderStatus('setupStatus', 'info', 'Resolving location…');
            resolveLocation(spec.resolve).then(function (res) {
                if (!res.ok) {
                    renderStatus('setupStatus', 'error', esc(res.error || 'Location could not be resolved.'));
                    return;
                }
                var params = { lat: res.lat, lon: res.lon, name: res.name };
                if (spec.product === 'insurance') {
                    params.radius_km = parseFloat(el('radiusInput').value) || 50;
                }
                requestDraft(spec.product, params);
            });
            return;
        }

        if (spec.items) {
            clearStatus('setupStatus');
            renderStatus('setupStatus', 'info', 'Resolving site names…');
            el('generateDraftBtn').disabled = true;
            resolveSites(spec.items).then(function (res) {
                el('generateDraftBtn').disabled = false;
                if (res.error) {
                    renderStatus('setupStatus', 'error', esc(res.error));
                    return;
                }
                requestDraft(spec.product, { company: spec.company, assets: res.assets });
            });
            return;
        }

        requestDraft(spec.product, spec.params);
    }

    function requestDraft(product, params) {
        clearStatus('setupStatus');
        renderStatus('setupStatus', 'info', 'Generating draft…');
        el('generateDraftBtn').disabled = true;

        fetchJSON(API + '/v2/report-builder/draft', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ kind: product, params: params }),
        }).then(function (res) {
            el('generateDraftBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                renderStatus('setupStatus', 'warn', authPrompt('use the report builder'));
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('setupStatus', 'error', esc(res.body.error || 'Draft generation failed'));
                return;
            }
            loadDraft(res.body.draft);
        }).catch(function () {
            el('generateDraftBtn').disabled = false;
            renderStatus('setupStatus', 'error', 'The report builder service could not be reached.');
        });
    }

    function loadDraft(d) {
        draft = d;
        sections = (d.sections || []).map(function (s) { return Object.assign({}, s); });
        hidePanel('setupPanel');
        showPanel('editorPanel');
        el('draftTitle').value = d.title || '';
        el('interconnectionNote').textContent = d.interconnection_note || '';
        renderSections();
        updateEditSummary();
    }

    function kindChip(kind) {
        var token = kind === 'introduction' ? 'observed'
            : kind === 'body' ? 'documented'
            : kind === 'gaps' ? 'partial'
            : kind === 'conclusion' ? 'modelled'
            : 'unknown';
        return chip(token, kind);
    }

    function renderSections() {
        var container = el('sectionsContainer');
        if (!sections.length) {
            container.innerHTML = '<p class="muted small">No sections.</p>';
            return;
        }

        var html = '';
        sections.forEach(function (s, idx) {
            var locked = s.kind !== 'body';
            html += '<div class="panel" data-idx="' + idx + '" style="margin-bottom:16px;">' +
                '<div class="toolbar" style="justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:8px;">' +
                '<span>' + kindChip(s.kind) + (s.edited ? ' ' + chip('reported', 'edited') : '') + (s.ai_polished ? ' ' + chip('reported', 'AI-polished') : '') + '</span>' +
                '<span>' +
                '<button class="btn-secondary btn-sm" data-action="up" data-idx="' + idx + '"' + (idx === 0 ? ' disabled' : '') + '>↑</button>' +
                '<button class="btn-secondary btn-sm" data-action="down" data-idx="' + idx + '"' + (idx === sections.length - 1 ? ' disabled' : '') + '>↓</button>' +
                '<button class="btn-secondary btn-sm" data-action="remove" data-idx="' + idx + '"' + (locked ? ' disabled title="Locked section"' : '') + '>×</button>' +
                '</span>' +
                '</div>' +
                '<div class="form-group">' +
                '<input type="text" class="section-heading" data-idx="' + idx + '" value="' + esc(s.heading) + '" maxlength="200">' +
                '</div>' +
                '<div class="form-group">' +
                '<textarea class="section-text" data-idx="' + idx + '" rows="6" maxlength="5000">' + esc(s.text) + '</textarea>' +
                '</div>' +
                '<div style="margin-bottom:8px;">' +
                '<button class="btn-secondary btn-sm polish-btn" data-idx="' + idx + '"' + (s.text ? '' : ' disabled') + '>Polish with AI</button>' +
                '</div>' +
                '<details class="expander">' +
                '<summary>Why is this section here?</summary>' +
                '<p class="muted small">' + esc(s.why || 'No explanation provided.') + '</p>' +
                '<p class="muted small"><strong>Source refs:</strong> ' + esc((s.source_refs || []).join(', ') || 'none') + '</p>' +
                '</details>' +
                '</div>';
        });
        container.innerHTML = html;

        // Wire inputs
        container.querySelectorAll('.section-heading, .section-text').forEach(function (input) {
            input.addEventListener('input', function () {
                var idx = parseInt(input.getAttribute('data-idx'), 10);
                var field = input.classList.contains('section-heading') ? 'heading' : 'text';
                sections[idx][field] = input.value;
                if (!sections[idx].edited) {
                    sections[idx].edited = true;
                    renderSections();
                }
                if (input.classList.contains('section-text')) {
                    var panel = input.closest('.panel');
                    var polishBtn = panel && panel.querySelector('.polish-btn');
                    if (polishBtn) polishBtn.disabled = !input.value.trim();
                }
                updateEditSummary();
            });
        });

        // Wire actions
        container.querySelectorAll('button[data-action]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var idx = parseInt(btn.getAttribute('data-idx'), 10);
                var action = btn.getAttribute('data-action');
                if (action === 'up') moveSection(idx, -1);
                else if (action === 'down') moveSection(idx, 1);
                else if (action === 'remove') removeSection(idx);
            });
        });

        // Wire AI polish buttons
        container.querySelectorAll('.polish-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var idx = parseInt(btn.getAttribute('data-idx'), 10);
                polishSection(idx);
            });
        });
    }

    function moveSection(idx, dir) {
        var newIdx = idx + dir;
        if (newIdx < 0 || newIdx >= sections.length) return;
        var tmp = sections[idx];
        sections[idx] = sections[newIdx];
        sections[newIdx] = tmp;
        renderSections();
    }

    function removeSection(idx) {
        if (sections[idx].kind !== 'body') return;
        sections.splice(idx, 1);
        renderSections();
        updateEditSummary();
    }

    function polishSection(idx) {
        if (!draft) return;
        var s = sections[idx];
        if (!s || !s.text || !s.text.trim()) return;

        clearStatus('editorStatus');
        var btn = el('sectionsContainer').querySelector('.polish-btn[data-idx="' + idx + '"]');
        if (btn) btn.disabled = true;

        fetchJSON(API + '/v2/report-builder/polish', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ heading: s.heading, text: s.text }),
        }).then(function (res) {
            if (btn) btn.disabled = false;
            if (res.status === 401 || res.status === 403) {
                renderStatus('editorStatus', 'warn', authPrompt('polish sections'));
                return;
            }
            if (res.status === 503) {
                renderStatus('editorStatus', 'warn', 'AI polish is currently unavailable.');
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('editorStatus', 'error', esc(res.body.error || 'AI polish failed'));
                return;
            }
            sections[idx].text = res.body.text || sections[idx].text;
            sections[idx].edited = true;
            sections[idx].ai_polished = true;
            renderSections();
            updateEditSummary();
        }).catch(function () {
            if (btn) btn.disabled = false;
            renderStatus('editorStatus', 'error', 'The AI polish service could not be reached.');
        });
    }

    function updateEditSummary() {
        var edited = sections.filter(function (s) { return s.edited; }).length;
        el('editSummary').textContent = edited + ' of ' + sections.length + ' section' + (sections.length === 1 ? '' : 's') + ' edited — marked in the PDF.';
    }

    function offerPortfolioSave(payload) {
        var row = el('portfolioRow');
        fetchJSON(API + '/v2/account/portfolios').then(function (res) {
            if (!res.ok) return;  // anonymous or unavailable — row stays hidden
            var portfolios = res.body.portfolios || [];
            if (!portfolios.length) return;
            row.style.display = '';
            el('pfSelect').innerHTML = portfolios.map(function (p) {
                return '<option value="' + p.id + '">' + esc(p.name) + '</option>';
            }).join('');
            el('pfSaveBtn').onclick = function () {
                el('pfSaveBtn').disabled = true;
                fetchJSON(API + '/v2/account/portfolios/' + el('pfSelect').value + '/items', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        kind: 'report',
                        lat: payload.lat != null ? payload.lat : null,
                        lon: payload.lon != null ? payload.lon : null,
                        meta: {
                            title: payload.title,
                            report_type: payload.kind || 'custom',
                            draft_id: payload.draft_id || null
                        }
                    })
                }).then(function (res2) {
                    el('pfSaveBtn').disabled = false;
                    el('pfSaveNote').textContent = res2.ok
                        ? 'Saved to the portfolio ✓' : 'Could not save the draft.';
                }).catch(function () {
                    el('pfSaveBtn').disabled = false;
                    el('pfSaveNote').textContent = 'Could not save the draft.';
                });
            };
        });
    }

    function downloadPdf() {
        if (!draft) return;
        el('downloadPdfBtn').disabled = true;
        clearStatus('editorStatus');

        var payload = {
            title: el('draftTitle').value.trim() || draft.title,
            sections: sections,
            draft_id: draft.draft_id,
            generated_at: draft.generated_at,
            kind: draft.kind,
            engine_version: draft.engine_version,
            honesty_note: draft.honesty_note,
            disclaimer: draft.disclaimer,
        };
        // Site coordinates (when the draft carries them) enable the
        // site-context image in the exported PDF.
        if (draft.asset && typeof draft.asset.lat === 'number' && typeof draft.asset.lon === 'number') {
            payload.lat = draft.asset.lat;
            payload.lon = draft.asset.lon;
        }

        fetch(API + '/v2/report-builder/pdf', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (r) {
            el('downloadPdfBtn').disabled = false;
            if (r.status === 401 || r.status === 403) {
                renderStatus('editorStatus', 'warn', authPrompt('export a PDF'));
                return;
            }
            if (!r.ok) {
                return r.json().then(function (body) {
                    renderStatus('editorStatus', 'error', esc(body.error || 'PDF export failed'));
                }).catch(function () {
                    renderStatus('editorStatus', 'error', 'PDF export failed');
                });
            }
            return r.blob().then(function (blob) {
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                var safe = (payload.title || 'report').replace(/\W+/g, '_');
                a.download = 'talaix_builder_' + safe + '.pdf';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
                clearStatus('editorStatus');
                offerPortfolioSave(payload);
            });
        }).catch(function () {
            el('downloadPdfBtn').disabled = false;
            renderStatus('editorStatus', 'error', 'The PDF service could not be reached.');
        });
    }

    function resetBuilder() {
        draft = null;
        sections = [];
        hidePanel('editorPanel');
        hidePanel('setupPanel');
        showPanel('modeChoice');
        el('productSelect').value = '';
        onProductChange();
        clearStatus('setupStatus');
        clearStatus('editorStatus');
    }

    function init() {
        el('startInteractiveBtn').addEventListener('click', function () {
            hidePanel('modeChoice');
            showPanel('setupPanel');
        });
        el('productSelect').addEventListener('change', onProductChange);
        el('generateDraftBtn').addEventListener('click', generateDraft);
        el('downloadPdfBtn').addEventListener('click', downloadPdf);
        el('newDraftBtn').addEventListener('click', resetBuilder);
    }

    init();
})();
