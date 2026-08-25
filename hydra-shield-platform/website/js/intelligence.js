/* Talaix — per-hazard Climate Intelligence (intelligence.html).
 *
 * Tab strip of the registered hazards (GET /api/v2/hazards — names,
 * availability and official source links are rendered from the descriptor);
 * a location ("lat,lon" directly, or a place name geocoded via
 * GET /api/analyze) is analysed through GET /api/v2/analyze?hazard=<id>&lat&lon.
 *
 * Rendering is generic and data-driven: the HazardAnalysis level, summary,
 * blocks (key-value tables, daily-series tables wherever arrays of
 * {date, …} appear), provenance chips and evidence records are rendered
 * from the payload — no per-hazard hardcoded markup beyond section titles.
 * unavailable / key_required / insufficient states are shown honestly.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    var hazards = [];
    var currentHazard = null;
    var resolvedLoc = null;   // canonical location from HS.location widget

    function el(id) { return document.getElementById(id); }

    // ------------------------------------------------------------------
    // Hazard tabs
    // ------------------------------------------------------------------

    function loadHazards(preselect) {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) {
                el('hazardTabs').innerHTML =
                    '<span class="muted">Hazard registry unavailable — analysis cannot run.</span>';
                return;
            }
            hazards = res.body.hazards;
            renderTabs();
            var wanted = preselect && hazards.some(function (h) {
                return h.id === preselect && h.analysis.available;
            }) ? preselect : (hazards.filter(function (h) { return h.analysis.available; })[0] || {}).id;
            if (wanted) selectHazard(wanted);
        }).catch(function () {
            el('hazardTabs').innerHTML =
                '<span class="muted">Hazard registry could not be reached.</span>';
        });
    }

    function renderTabs() {
        var tabs = el('hazardTabs');
        tabs.innerHTML = '';
        hazards.forEach(function (h) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'hazard-tab' + (currentHazard === h.id ? ' active' : '');
            btn.textContent = h.name;
            btn.setAttribute('role', 'tab');
            if (!h.analysis.available) {
                btn.disabled = true;
                btn.title = h.analysis.reason || 'Unavailable';
            } else {
                btn.addEventListener('click', function () { selectHazard(h.id); });
            }
            tabs.appendChild(btn);
        });
    }

    function selectHazard(hazardId) {
        currentHazard = hazardId;
        renderTabs();
        if (window.HS && HS.track) HS.track('hazard_selected', { hazard: hazardId });
        var h = hazards.filter(function (x) { return x.id === hazardId; })[0];
        var note = h ? (h.tagline || '') : '';
        if (hazardId === 'wildfire') {
            note += ' For the full wildfire pipeline (spread scenarios, protection planning, reports) use the ';
        }
        var noteHtml = esc(note) +
            (hazardId === 'wildfire'
                ? '<a class="text-link" href="dashboard.html">full wildfire analyzer →</a>'
                : '');
        // Official sources behind this hazard (from the registry descriptor —
        // the same declarations the map layer panel shows).
        if (h && h.sources && h.sources.length) {
            noteHtml += '<span class="muted small" style="display:block;margin-top:6px;">Sources: ' +
                h.sources.map(function (s) {
                    return '<a class="text-link" href="' + esc(s.url) +
                        '" target="_blank" rel="noopener">' + esc(s.name) + '</a>';
                }).join(' · ') + '</span>';
        }
        el('hazardNote').innerHTML = noteHtml;
        el('analysisArea').innerHTML = '';
        el('statusArea').innerHTML = '';
        if (history.replaceState) history.replaceState(null, '', '#' + hazardId);
    }

    // ------------------------------------------------------------------
    // Analyze
    // ------------------------------------------------------------------

    function analyze() {
        var q = el('locWidget_q') ? el('locWidget_q').value.trim() : '';
        if (!q && !resolvedLoc) {
            renderStatus('error', 'Enter a location — a place name or lat,lon coordinates.');
            return;
        }
        if (!currentHazard) return;
        el('analyzeBtn').disabled = true;
        el('analysisArea').innerHTML = '';
        renderStatus('info', 'Resolving location…');

        // Use the widget's canonical location when it matches the current
        // input; otherwise resolve fresh.
        var direct = Promise.resolve(null);
        if (resolvedLoc && q && resolvedLoc._input === q) {
            direct = Promise.resolve({ ok: true, lat: resolvedLoc.lat,
                                       lon: resolvedLoc.lon, name: resolvedLoc.name });
        } else {
            direct = HS.resolveLocation(q);
        }
        direct.then(function (loc) {
            if (!loc.ok) {
                el('analyzeBtn').disabled = false;
                renderStatus('error', loc.error || 'Location could not be resolved.');
                return;
            }
            HS.rememberLocation({ name: loc.name, lat: loc.lat, lon: loc.lon });
            renderStatus('info', 'Running ' + currentHazard + ' analysis for ' + loc.name + '…');
            var url = API + '/v2/analyze?hazard=' + encodeURIComponent(currentHazard) +
                '&lat=' + loc.lat.toFixed(4) + '&lon=' + loc.lon.toFixed(4) +
                '&name=' + encodeURIComponent(loc.name);
            return fetchJSON(url).then(function (res) {
                el('analyzeBtn').disabled = false;
                renderAnalysis(res.body || {}, res.ok, res.status);
            });
        }).catch(function () {
            el('analyzeBtn').disabled = false;
            renderStatus('error', 'The analysis service could not be reached.');
        });
    }

    function renderStatus(kind, msg) {
        el('statusArea').innerHTML =
            '<div class="notice notice-' + kind + '">' + esc(msg) + '</div>';
    }

    // ------------------------------------------------------------------
    // Rendering — generic, data-driven
    // ------------------------------------------------------------------

    function renderAnalysis(a, ok, httpStatus) {
        var area = el('analysisArea');

        if (httpStatus === 503 || a.status === 'unavailable' || a.status === 'key_required') {
            renderStatus('warn', '');
            el('statusArea').innerHTML =
                '<div class="notice notice-warn"><strong>' +
                esc((a.hazard || currentHazard) + ' analysis unavailable') + '</strong><br>' +
                esc(a.unavailable_reason || a.error || 'No reason provided.') + '</div>';
            return;
        }
        if (!ok || a.error) {
            renderStatus('error', 'Analysis failed: ' + (a.error || 'request failed'));
            return;
        }

        el('statusArea').innerHTML = '';
        var html = '';

        // ---- Level banner ------------------------------------------------
        var lvl = a.level;
        var loc = a.location || {};
        if (window.HSConvert) HSConvert.trackAction('location_analyzed', {
            hazard: a.hazard || currentHazard, lat: loc.lat, lon: loc.lon
        });
        if (window.HSConvert) HSConvert.show({
            mount: 'statusArea', context: 'save_analysis',
            text: 'This analysis is real but temporary — save it and monitor this place with a free account.',
            cta: 'Get alerts for this place',
            href: 'account.html?location=' + encodeURIComponent(loc.name || '') +
                  '&hazard=' + encodeURIComponent(a.hazard || currentHazard) + '#sms'
        });
        if (window.HSConvert) HSConvert.evaluate('statusArea');
        html += '<div class="panel">';
        html += '<h2>' + esc(loc.name || (loc.lat + ', ' + loc.lon)) + ' — ' +
            esc(a.hazard) + ' ' + chip(a.status || 'ok', (a.status || 'ok').toUpperCase()) + '</h2>';
        if (lvl) {
            var label = lvl.label || 'Unknown';
            html += '<div class="level-banner">' +
                (lvl.score != null
                    ? '<div class="level-score">' + esc(lvl.score) +
                      (lvl.score_max ? '<span style="font-size:1.1rem;color:var(--text-light);">/' + esc(lvl.score_max) + '</span>' : '') + '</div>'
                    : '') +
                '<div class="level-label level-' + esc(label) + '">' + esc(label.toUpperCase()) + '</div>' +
                '</div>';
            if (lvl.basis) html += '<p class="muted" style="margin-top:10px;">' + esc(lvl.basis) + '</p>';
            if (lvl.validated === false) {
                html += '<div class="disclaimer-box">Screening indicator — <strong>not a validated predictor</strong> ' +
                    '(see the validation status in every report).</div>';
            }
        } else {
            html += '<p class="muted">No level could be computed for this location; see the blocks below for what is available.</p>';
        }
        if (a.summary) html += '<p style="margin-top:10px;">' + esc(a.summary) + '</p>';
        if (loc.lat != null && loc.lon != null) {
            html += '<p class="muted small" style="margin-top:10px;">' +
                '<a class="text-link" href="forensics.html?location=' +
                encodeURIComponent(loc.lat.toFixed(4) + ',' + loc.lon.toFixed(4)) +
                '">Open a forensic case at this location →</a>' +
                '</p>';
        }
        html += '</div>';

        // ---- Blocks (generic renderer) -----------------------------------
        var blocks = a.blocks || {};
        var blockKeys = Object.keys(blocks).filter(function (k) {
            return blocks[k] !== null && blocks[k] !== undefined;
        });
        if (blockKeys.length) {
            html += '<div class="panel"><h2>Analysis blocks</h2>';
            blockKeys.forEach(function (key) {
                html += renderBlock(key, blocks[key], (a.provenance || {})[key]);
            });
            html += '</div>';
        }

        // ---- Evidence records --------------------------------------------
        if (a.evidence && a.evidence.length) {
            html += '<div class="panel"><h2>Evidence (' + a.evidence.length + ' record' +
                (a.evidence.length === 1 ? '' : 's') + ')</h2>';
            a.evidence.forEach(function (rec) { html += renderEvidenceRecord(rec); });
            html += '</div>';
        }

        // ---- Provenance table --------------------------------------------
        var prov = a.provenance || {};
        var provKeys = Object.keys(prov).filter(function (k) {
            return prov[k] && typeof prov[k] === 'object' && (prov[k].source || prov[k].kind);
        });
        if (provKeys.length) {
            html += '<div class="panel"><details class="expander"><summary>Data sources &amp; provenance (' +
                provKeys.length + ')</summary><div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Component</th><th>Status</th><th>Source</th><th>Acquired / retrieved</th><th>Resolution</th><th>Limitations</th>' +
                '</tr></thead><tbody>' +
                provKeys.map(function (k) {
                    var p = prov[k];
                    return '<tr><td>' + esc(k) + '</td>' +
                        '<td>' + chip(p.claim_status || p.kind || 'UNKNOWN') + '</td>' +
                        '<td>' + esc(p.source || '—') + '</td>' +
                        '<td>' + esc(p.acquired || p.retrieved_at || '—') + '</td>' +
                        '<td>' + esc(p.resolution || '—') + '</td>' +
                        '<td>' + esc(p.limitations || '—') + '</td></tr>';
                }).join('') + '</tbody></table></div></details></div>';
        }

        area.innerHTML = html;
    }

    /* One block: key-value tables for scalar dicts, daily-series tables for
     * arrays of {date, …}, recursion for nested dicts, honest error states. */
    function renderBlock(key, value, prov) {
        var title = key.replace(/_/g, ' ');
        var html = '<div class="sub-block">' +
            '<div class="sub-block-title" style="color:var(--dark);">' + esc(title) +
            (prov && (prov.claim_status || prov.kind)
                ? ' ' + chip(prov.claim_status || prov.kind) +
                  (prov.source ? ' <span class="muted small">' + esc(prov.source) + '</span>' : '')
                : '') + '</div>';

        if (typeof value !== 'object') {
            html += '<div>' + esc(value) + '</div></div>';
            return html;
        }
        if (Array.isArray(value)) {
            html += renderValue(value) + '</div>';
            return html;
        }
        if (value.error) {
            html += '<div class="muted">' + chip('UNAVAILABLE') + ' ' + esc(value.error) + '</div></div>';
            return html;
        }

        var scalars = {};
        var complex = {};
        Object.keys(value).forEach(function (k) {
            var v = value[k];
            if (v === null || v === undefined) return;
            if (typeof v === 'object') complex[k] = v;
            else scalars[k] = v;
        });

        var scalarKeys = Object.keys(scalars);
        if (scalarKeys.length) {
            html += '<div class="table-scroll"><table class="kv-table">' +
                scalarKeys.map(function (k) {
                    return '<tr><th>' + esc(k.replace(/_/g, ' ')) + '</th><td>' + esc(scalars[k]) + '</td></tr>';
                }).join('') + '</table></div>';
        }
        Object.keys(complex).forEach(function (k) {
            html += '<div style="margin-top:8px;"><strong class="small">' +
                esc(k.replace(/_/g, ' ')) + '</strong>' + renderValue(complex[k]) + '</div>';
        });
        if (!scalarKeys.length && !Object.keys(complex).length) {
            html += '<div class="muted small">No values returned for this block.</div>';
        }
        html += '</div>';
        return html;
    }

    function renderValue(v) {
        if (v === null || v === undefined) return '';
        if (Array.isArray(v)) {
            if (!v.length) return '<div class="muted small">Empty list.</div>';
            var allObjects = v.every(function (x) { return x && typeof x === 'object' && !Array.isArray(x); });
            if (allObjects) {
                var cols = [];
                v.forEach(function (row) {
                    Object.keys(row).forEach(function (k) {
                        if (cols.indexOf(k) < 0 && (row[k] === null || typeof row[k] !== 'object')) cols.push(k);
                    });
                });
                if (cols.length) {
                    var rows = v.slice(0, 62);
                    return '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                        cols.map(function (c) { return '<th>' + esc(c.replace(/_/g, ' ')) + '</th>'; }).join('') +
                        '</tr></thead><tbody>' +
                        rows.map(function (row) {
                            return '<tr>' + cols.map(function (c) {
                                return '<td>' + esc(row[c] === null || row[c] === undefined ? '—' : row[c]) + '</td>';
                            }).join('') + '</tr>';
                        }).join('') + '</tbody></table></div>' +
                        (v.length > rows.length
                            ? '<div class="muted small">Showing ' + rows.length + ' of ' + v.length + ' rows.</div>'
                            : '');
                }
            }
            // Arrays of scalars / mixed: compact list.
            return '<ul style="margin:4px 0 4px 18px;">' + v.slice(0, 30).map(function (x) {
                return '<li>' + esc(typeof x === 'object' ? JSON.stringify(x) : x) + '</li>';
            }).join('') + '</ul>' +
                (v.length > 30 ? '<div class="muted small">…and ' + (v.length - 30) + ' more.</div>' : '');
        }
        if (typeof v === 'object') {
            if (v.error) return '<div class="muted">' + chip('UNAVAILABLE') + ' ' + esc(v.error) + '</div>';
            var keys = Object.keys(v).filter(function (k) {
                return v[k] !== null && v[k] !== undefined && typeof v[k] !== 'object';
            });
            var nested = Object.keys(v).filter(function (k) {
                return v[k] && typeof v[k] === 'object';
            });
            var html = '';
            if (keys.length) {
                html += '<div class="table-scroll"><table class="kv-table">' +
                    keys.map(function (k) {
                        return '<tr><th>' + esc(k.replace(/_/g, ' ')) + '</th><td>' + esc(v[k]) + '</td></tr>';
                    }).join('') + '</table></div>';
            }
            nested.forEach(function (k) {
                html += '<div style="margin-top:6px;"><strong class="small">' +
                    esc(k.replace(/_/g, ' ')) + '</strong>' + renderValue(v[k]) + '</div>';
            });
            if (!keys.length && !nested.length) return '<div class="muted small">No values.</div>';
            return html;
        }
        return esc(v);
    }

    function renderEvidenceRecord(rec) {
        var period = rec.reference_period
            ? (rec.reference_period.start || '') +
              (rec.reference_period.end && rec.reference_period.end !== rec.reference_period.start
                  ? ' → ' + rec.reference_period.end : '')
            : '';
        return '<div class="sub-block">' +
            '<div class="badge-row">' +
            chip(rec.claim_status || 'UNKNOWN') + ' ' + chip(rec.temporal || 'OBSERVED') +
            '<span class="muted small">' + esc(rec.class || '') + '</span></div>' +
            '<div style="margin-top:6px;"><strong>' + esc(rec.source || '') + '</strong>' +
            (rec.dataset ? ' · ' + esc(rec.dataset) : '') + '</div>' +
            '<div class="muted small">' +
            [rec.method && 'Method: ' + rec.method,
             rec.resolution && 'Resolution: ' + rec.resolution,
             period && 'Period: ' + period,
             rec.confidence && 'Confidence: ' + rec.confidence,
             rec.limitations && 'Limitations: ' + rec.limitations]
                .filter(Boolean).map(esc).join('<br>') + '</div>' +
            (rec.provider_url
                ? '<a class="text-link" href="' + esc(rec.provider_url) + '" target="_blank" rel="noopener">Provider →</a>'
                : '') +
            '</div>';
    }

    // ------------------------------------------------------------------
    // Init
    // ------------------------------------------------------------------

    function init() {
        el('analyzeBtn').addEventListener('click', analyze);
        // Platform Location component: named search / coordinates / map link.
        if (window.HS && HS.location) {
            HS.location.mount('locWidget', {
                onResolve: function (loc) {
                    loc._input = el('locWidget_q').value.trim();
                    resolvedLoc = loc;
                }
            });
            el('locWidget_q').addEventListener('keydown', function (e) {
                if (e.key === 'Enter') analyze();
            });
        }
        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q && el('locWidget_q')) el('locWidget_q').value = q;
        var hash = (location.hash || '').replace('#', '');
        loadHazards(hash || undefined);
    }

    init();
})();
