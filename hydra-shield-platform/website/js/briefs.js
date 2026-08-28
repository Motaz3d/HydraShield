/* Talaix Knowledge Arm — Briefs page.
 *
 * Loads the public briefs registry, renders filterable cards, and provides a
 * linkable reader view for individual briefs.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    var briefs = [];
    var currentKind = 'all';

    function renderStatus(mountId, kind, html) {
        el(mountId).innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function loadBriefs() {
        return fetchJSON(API + '/v2/briefs').then(function (res) {
            if (!res.ok || !res.body || !res.body.briefs) {
                renderStatus('briefList', 'error', 'Briefs could not be loaded.');
                return;
            }
            briefs = res.body.briefs;
            renderList();
        }).catch(function () {
            renderStatus('briefList', 'error', 'The briefs service could not be reached.');
        });
    }

    function kindLabel(kind) {
        return kind === 'framework_explainer' ? 'Framework explainer'
            : kind === 'evidence_brief' ? 'Evidence brief'
            : esc(kind);
    }

    function renderList() {
        var filtered = briefs.filter(function (b) {
            return currentKind === 'all' || b.kind === currentKind;
        });

        var html = '';
        filtered.forEach(function (b) {
            html += '<div class="item-card brief-card" data-id="' + esc(b.id) + '">' +
                '<div class="toolbar" style="justify-content:space-between; gap:12px; flex-wrap:wrap;">' +
                chip(b.kind, kindLabel(b.kind)) +
                '<span class="muted small">' + esc(b.date) + '</span>' +
                '</div>' +
                '<h3>' + esc(b.title) + '</h3>' +
                '<p class="muted">' + esc(b.summary) + '</p>' +
                '<p class="muted small">' + (b.source_count || 0) + ' source' + (b.source_count === 1 ? '' : 's') + '</p>' +
                '<button class="btn-action btn-sm" data-id="' + esc(b.id) + '">Read</button>' +
                '</div>';
        });

        el('briefList').innerHTML = html || '<p class="muted small">No briefs match this filter.</p>';

        el('briefList').querySelectorAll('.brief-card, button[data-id]').forEach(function (node) {
            node.addEventListener('click', function (ev) {
                var id = ev.currentTarget.getAttribute('data-id');
                if (id) openBrief(id);
            });
        });
    }

    function updateFilterButtons() {
        document.querySelectorAll('.filter-btn').forEach(function (btn) {
            var active = btn.getAttribute('data-kind') === currentKind;
            btn.classList.toggle('btn-action', active);
            btn.classList.toggle('btn-secondary', !active);
            btn.classList.toggle('active', active);
        });
    }

    function onFilterClick(ev) {
        var kind = ev.currentTarget.getAttribute('data-kind');
        if (!kind) return;
        currentKind = kind;
        updateFilterButtons();
        renderList();
    }

    function showReader(show) {
        el('briefListPanel').style.display = show ? 'none' : '';
        el('readerPanel').style.display = show ? 'block' : 'none';
        if (!show) {
            // Remove deep-link id without reloading.
            var url = new URL(location.href);
            url.searchParams.delete('id');
            history.replaceState(null, '', url.toString());
        }
    }

    function formatSourceDate(d) {
        return d ? esc(d) : '—';
    }

    function openBrief(briefId) {
        fetchJSON(API + '/v2/briefs/' + encodeURIComponent(briefId)).then(function (res) {
            if (!res.ok || !res.body || !res.body.brief) {
                renderStatus('briefList', 'error', 'Brief not found.');
                return;
            }
            var b = res.body.brief;

            showReader(true);
            el('readerKindChip').innerHTML = chip(b.kind, kindLabel(b.kind));
            el('readerTitle').textContent = b.title;
            el('readerMeta').textContent = b.date + ' · ' + (b.sources ? b.sources.length : 0) + ' source' + (b.sources && b.sources.length === 1 ? '' : 's');

            var sectionsHtml = '';
            (b.sections || []).forEach(function (s) {
                sectionsHtml += '<h3>' + esc(s.heading) + '</h3>' +
                    '<p>' + esc(s.body).replace(/\n/g, '<br>') + '</p>';
            });
            el('readerSections').innerHTML = sectionsHtml;

            var sourcesHtml = '';
            (b.sources || []).forEach(function (s) {
                sourcesHtml += '<tr>' +
                    '<td>' + esc(s.name) + '</td>' +
                    '<td>' + formatSourceDate(s.date) + '</td>' +
                    '<td>' + chip(s.claim_status, s.claim_status) + '</td>' +
                    '<td><a class="text-link" href="' + esc(s.url) + '" target="_blank" rel="noopener">Source →</a></td>' +
                    '</tr>';
            });
            el('readerSources').innerHTML = sourcesHtml || '<tr><td colspan="4" class="muted small">No sources listed.</td></tr>';

            var toolsHtml = '';
            if (b.related_tools && b.related_tools.length) {
                toolsHtml = '<h3>Related tools</h3><p>' +
                    b.related_tools.map(function (t) {
                        return '<a class="btn-secondary btn-sm" href="' + esc(t.href) + '" style="margin-right:8px; margin-bottom:8px; display:inline-block;">' + esc(t.label) + '</a>';
                    }).join('') +
                    '</p>';
            }
            el('readerRelatedTools').innerHTML = toolsHtml;

            var glossHtml = '';
            if (b.related_glossary && b.related_glossary.length) {
                glossHtml = '<p><strong>Related glossary:</strong> ' +
                    b.related_glossary.map(function (termId) {
                        return '<a class="chip chip-documented" href="academy.html" style="text-decoration:none; margin-right:6px;">' + esc(termId) + '</a>';
                    }).join('') +
                    '</p>';
            }
            el('readerRelatedGlossary').innerHTML = glossHtml;

            // Update URL so the brief is linkable.
            var url = new URL(location.href);
            url.searchParams.set('id', briefId);
            history.replaceState(null, '', url.toString());
        }).catch(function () {
            renderStatus('briefList', 'error', 'The brief could not be loaded.');
        });
    }

    function wireFilters() {
        document.querySelectorAll('.filter-btn').forEach(function (btn) {
            btn.addEventListener('click', onFilterClick);
        });
        el('backToListBtn').addEventListener('click', function () {
            showReader(false);
        });
    }

    function init() {
        wireFilters();
        loadBriefs().then(function () {
            var params = new URL(location.href).searchParams;
            var id = params.get('id');
            // On the merged Academy page a brief deep-link only opens in
            // briefs mode (?mode=briefs&id=…).
            if (id && params.get('mode') === 'briefs') openBrief(id);
        });
    }

    init();
})();
