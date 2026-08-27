/* Talaix — Press Evidence Pack page (press.html).
 *
 * Generates a journalist-facing evidence pack from /api/v2/press/pack.
 * English packs are public; other languages are subscriber-gated.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function renderStatus(kind, html) {
        el('pressStatus').innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function clearStatus() {
        el('pressStatus').innerHTML = '';
    }

    function generatePack() {
        var input = el('pressLocInput').value.trim();
        var lang = el('pressLangSelect').value;
        if (!input) {
            renderStatus('error', 'Enter a location — a place name or lat,lon coordinates.');
            return;
        }
        el('pressGenerateBtn').disabled = true;
        clearStatus();
        renderStatus('info', 'Resolving location and building the evidence pack…');

        HS.resolveLocation(input).then(function (loc) {
            if (!loc.ok) {
                el('pressGenerateBtn').disabled = false;
                renderStatus('error', esc(loc.error || 'Location could not be resolved.'));
                return;
            }
            var url = API + '/v2/press/pack?lat=' + loc.lat.toFixed(4) +
                '&lon=' + loc.lon.toFixed(4) +
                '&lang=' + encodeURIComponent(lang) +
                '&name=' + encodeURIComponent(loc.name);
            return fetchJSON(url).then(function (res) {
                el('pressGenerateBtn').disabled = false;
                if (!res.ok) {
                    if (res.status === 401) {
                        renderStatus('error', 'Please sign in to access subscriber packs. <a class="text-link" href="account.html">Sign in →</a>');
                    } else if (res.status === 403 && res.body && res.body.upgrade) {
                        renderStatus('error', 'This language requires a subscriber account. ' +
                            '<a class="text-link" href="account.html">Upgrade →</a>');
                    } else {
                        renderStatus('error', esc(res.body.error || 'Pack generation failed'));
                    }
                    return;
                }
                renderPack(res.body, loc, lang);
            });
        }).catch(function () {
            el('pressGenerateBtn').disabled = false;
            renderStatus('error', 'The pack service could not be reached.');
        });
    }

    function renderPack(pack, loc, lang) {
        var location = pack.location || {};
        var html = '';

        // Title block
        html += '<div class="panel">';
        html += '<h2>' + esc(pack.headline) + '</h2>';
        if (pack.subhead) html += '<p class="muted">' + esc(pack.subhead) + '</p>';
        html += '<p>' + esc(pack.lead) + '</p>';
        html += '<p class="muted small">Pack ID: ' + esc(pack.pack_id) + ' · Generated: ' + esc(pack.generated_at) + ' · Language: ' + esc(pack.language) + '</p>';
        html += '</div>';

        // Key facts
        html += '<div class="panel"><h3>Key facts</h3><ul>';
        (pack.key_facts || []).forEach(function (fact) {
            html += '<li>' + esc(fact) + '</li>';
        });
        html += '</ul></div>';

        // Figures
        html += '<div class="panel"><h3>Figures</h3>';
        var hasFigure = false;
        (pack.figures || []).forEach(function (fig) {
            var src = fig.endpoint;
            if (fig.available) {
                hasFigure = true;
                html += '<figure style="margin:12px 0;">';
                html += '<img src="' + esc(src) + '" alt="' + esc(fig.alt_text) + '" style="max-width:100%; border:1px solid #e2e8f0; border-radius:4px;">';
                html += '<figcaption class="muted small">' + esc(fig.caption) + '</figcaption>';
                html += '</figure>';
            } else {
                html += '<p class="muted small">' + esc(fig.alt_text) + ' — unavailable for this location.</p>';
            }
        });
        if (!hasFigure) html += '<p class="muted small">No figures could be generated for this location.</p>';
        html += '</div>';

        // Quotable lines
        if ((pack.quotable_lines || []).length) {
            html += '<div class="panel"><h3>Quotable sourced lines</h3>';
            pack.quotable_lines.forEach(function (line) {
                html += '<blockquote style="margin:8px 0; padding:10px; border-left:3px solid #0ea5e9; background:#f8fafc;">';
                html += '<p style="margin:0;">“' + esc(line.text) + '”</p>';
                html += '<p class="muted small" style="margin:6px 0 0;">Source: ' + esc(line.source) + ' · ' + chip(line.status) + '</p>';
                html += '</blockquote>';
            });
            html += '</div>';
        }

        // Data sources
        if ((pack.sources || []).length) {
            html += '<div class="panel"><h3>Data sources</h3><ul class="muted">';
            pack.sources.forEach(function (src) {
                html += '<li><strong>' + esc(src.name) + '</strong>';
                if (src.provider) html += ' (' + esc(src.provider) + ')';
                if (src.url) html += ' — <a class="text-link" href="' + esc(src.url) + '" target="_blank" rel="noopener">' + esc(src.url) + '</a>';
                html += '</li>';
            });
            html += '</ul></div>';
        }

        // Press watch
        if ((pack.press_watch || []).length) {
            html += '<div class="panel"><h3>Press watch registry</h3><ul class="muted">';
            pack.press_watch.forEach(function (entry) {
                html += '<li><strong>' + esc(entry.name) + '</strong>';
                if (entry.publisher) html += ' · ' + esc(entry.publisher);
                if (entry.frequency) html += ' · ' + esc(entry.frequency);
                if (entry.url) html += ' — <a class="text-link" href="' + esc(entry.url) + '" target="_blank" rel="noopener">' + esc(entry.url) + '</a>';
                html += '</li>';
            });
            html += '</ul></div>';
        }

        // Methodology and honesty
        html += '<div class="panel">';
        html += '<h3>Methodology &amp; honesty</h3>';
        html += '<p class="muted small">' + esc(pack.methodology_note) + '</p>';
        html += '<p class="muted small">' + esc(pack.honesty_note) + '</p>';
        html += '</div>';

        // PDF download
        var pdfUrl = API + '/v2/press/pack.pdf?lat=' + location.lat.toFixed(4) +
            '&lon=' + location.lon.toFixed(4) +
            '&lang=' + encodeURIComponent(lang) +
            '&name=' + encodeURIComponent(location.name || '');
        html += '<div class="panel">' +
            '<a class="btn-action" href="' + esc(pdfUrl) + '" target="_blank" rel="noopener">Download pack PDF</a>' +
            '</div>';

        el('pressResult').innerHTML = html;
    }

    el('pressGenerateBtn').addEventListener('click', generatePack);
    el('pressLocInput').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') generatePack();
    });

    // The live example (RTL.lu drought story) — one click to run it.
    var exampleBtn = el('pressExampleBtn');
    if (exampleBtn) {
        exampleBtn.addEventListener('click', function () {
            el('pressLocInput').value = '49.75, 6.64';
            generatePack();
        });
    }

    // Deep link: press.html?location=… (e.g. from the map act-on-point panel).
    var q = new URLSearchParams(location.search).get('location');
    if (q && el('pressLocInput')) el('pressLocInput').value = q;
})();
