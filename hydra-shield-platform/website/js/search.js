/* Talaix — site-wide command-palette quick search.
 *
 * Opened from the navbar search button or via Cmd/Ctrl+K (and '/' when not
 * typing in an input). A row of clickable search-type tabs filters the
 * results and opens per-type advanced options; the free-text input always
 * accepts anything. Searches static navigation, portal actions, hazards,
 * data sources, the glossary and evidence briefs. Only real content is
 * returned; there are no fake results.
 *
 * This file is loaded dynamically by chrome.js after the nav is rendered.
 * It must run without api.js, so it only uses platform fetch and the
 * HS_NAV_LINKS / HS.lastLocation contracts guarded behind existence checks.
 */
(function () {
    'use strict';

    var API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8051/api'
        : '/api';

    var MAX_PER_GROUP = 7;
    var GROUP_ORDER = ['Navigation', 'Actions', 'Location', 'Hazards', 'Glossary', 'Briefs', 'Sources'];

    /* Clickable search types: 'all' shows every group; any other id is a
     * group name from GROUP_ORDER and filters the palette to that group. */
    var TYPES = [
        { id: 'all', label: 'All' },
        { id: 'Navigation', label: 'Pages' },
        { id: 'Actions', label: 'Actions' },
        { id: 'Location', label: 'Location' },
        { id: 'Hazards', label: 'Hazards' },
        { id: 'Glossary', label: 'Glossary' },
        { id: 'Briefs', label: 'Briefs' },
        { id: 'Sources', label: 'Data sources' }
    ];

    var _container = null;
    var _input = null;
    var _resultsEl = null;
    var _typesEl = null;
    var _allItems = [];
    var _filteredItems = [];
    var _activeIndex = -1;
    var _activeType = 'all';
    var _glossary = null;
    var _briefs = null;
    var _hazards = null;
    var _sources = null;
    var _openedOnce = false;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function qs(selector) {
        return document.querySelector(selector);
    }

    function qsa(selector) {
        return document.querySelectorAll(selector);
    }

    // -----------------------------------------------------------------------
    // Index builders
    // -----------------------------------------------------------------------

    function buildNavigationItems() {
        var links = (typeof window !== 'undefined' && window.HS_NAV_LINKS) || [];
        return links.map(function (item) {
            return {
                id: 'nav-' + item.id,
                label: item.label,
                hint: 'Page',
                keywords: [item.label, 'page'],
                href: item.href,
                group: 'Navigation'
            };
        });
    }

    function buildActionItems() {
        return [
            { id: 'act-verify', label: 'Verify an asset', hint: 'Green Finance', href: 'green-finance.html', group: 'Actions', keywords: ['verify', 'green', 'finance', 'taxonomy'] },
            { id: 'act-csrd', label: 'Build a CSRD evidence report', hint: 'Sustainability', href: 'sustainability.html', group: 'Actions', keywords: ['csrd', 'sustainability', 'report', 'esrs'] },
            { id: 'act-insurance', label: 'Profile an insured asset', hint: 'Insurance', href: 'insurance.html', group: 'Actions', keywords: ['insurance', 'risk', 'profile', 'peril'] },
            { id: 'act-supplychain', label: 'Screen an origin claim (EUDR)', hint: 'Supply Chain', href: 'supplychain.html', group: 'Actions', keywords: ['supply', 'chain', 'eudr', 'origin', 'deforestation'] },
            { id: 'act-forensics', label: 'Open a forensic case', hint: 'Forensics', href: 'forensics.html', group: 'Actions', keywords: ['forensics', 'case', 'investigation'] },
            { id: 'act-reports', label: 'Compose a report', hint: 'Report Builder', href: 'reports.html#builder', group: 'Actions', keywords: ['report', 'builder', 'compose'] },
            { id: 'act-academy', label: 'Take the Academy course', hint: 'Learn', href: 'academy.html', group: 'Actions', keywords: ['academy', 'course', 'learn', 'training'] },
            { id: 'act-briefs', label: 'Read evidence briefs', hint: 'Knowledge', href: 'academy.html?mode=briefs', group: 'Actions', keywords: ['briefs', 'evidence', 'knowledge', 'articles'] }
        ];
    }

    function _locationParam(loc) {
        if (!loc) return '';
        var name = loc.name || '';
        if (name) return encodeURIComponent(name);
        if (loc.lat != null && loc.lon != null) {
            return encodeURIComponent(loc.lat + ',' + loc.lon);
        }
        return '';
    }

    function buildLocationItems() {
        var items = [];
        var last = (typeof window !== 'undefined' && window.HS && typeof window.HS.lastLocation === 'function')
            ? window.HS.lastLocation()
            : null;
        if (!last) return items;
        var param = _locationParam(last);
        var displayName = last.name || (last.lat + ',' + last.lon);
        items.push({
            id: 'loc-verify',
            label: 'Verify ' + displayName,
            hint: 'Last analysed location',
            href: 'green-finance.html?location=' + param,
            group: 'Location',
            keywords: ['verify', displayName]
        });
        items.push({
            id: 'loc-insurance',
            label: 'Profile ' + displayName + ' (insurance)',
            hint: 'Last analysed location',
            href: 'insurance.html?location=' + param,
            group: 'Location',
            keywords: ['insurance', 'profile', displayName]
        });
        return items;
    }

    function buildFallbackItems(query) {
        var q = String(query).trim();
        if (!q) return [];
        return [
            {
                id: 'fb-map',
                label: "Search map for '" + q + "'",
                hint: 'New location',
                href: 'map.html?location=' + encodeURIComponent(q),
                group: 'Actions',
                keywords: ['map', q]
            },
            {
                id: 'fb-verify',
                label: "Verify '" + q + "'",
                hint: 'New location',
                href: 'green-finance.html?location=' + encodeURIComponent(q),
                group: 'Actions',
                keywords: ['verify', q]
            },
            {
                id: 'fb-analyze',
                label: "Analyze '" + q + "' (Intelligence)",
                hint: 'New location',
                href: 'intelligence.html?location=' + encodeURIComponent(q),
                group: 'Actions',
                keywords: ['analyze', 'intelligence', 'hazard', q]
            }
        ];
    }

    function buildGlossaryItems() {
        var terms = (_glossary && _glossary.terms) || [];
        return terms.map(function (t) {
            return {
                id: 'gloss-' + t.id,
                label: t.term,
                hint: t.short || 'Glossary',
                href: 'academy.html#' + t.id,
                group: 'Glossary',
                keywords: [t.term, t.short || '']
            };
        });
    }

    function buildBriefItems() {
        var briefs = (_briefs && _briefs.briefs) || [];
        return briefs.map(function (b) {
            return {
                id: 'brief-' + b.id,
                label: b.title,
                hint: b.kind === 'framework_explainer' ? 'Framework explainer' : 'Evidence brief',
                href: 'academy.html?mode=briefs&id=' + encodeURIComponent(b.id),
                group: 'Briefs',
                keywords: [b.title, b.summary || '', b.kind || '']
            };
        });
    }

    /* payload: the /api/v2/hazards contract ({hazards: [...]}) or a bare
     * array. Each entry opens the Intelligence page with that hazard's tab
     * preselected (?mode= is honoured by intelligence.js). */
    function buildHazardItems(payload) {
        var hazards = Array.isArray(payload) ? payload : (payload && payload.hazards) || [];
        return hazards.map(function (h) {
            return {
                id: 'haz-' + h.id,
                label: h.name || h.id,
                hint: h.tagline || 'Hazard analysis',
                href: 'intelligence.html?mode=' + encodeURIComponent(h.id),
                group: 'Hazards',
                keywords: [h.id, h.name || '', h.tagline || '', 'hazard', 'analysis']
            };
        });
    }

    /* payload: the /api/sources contract ({sources: [...]}) or a bare array.
     * Only integrated sources are listed — candidates and rejected sources
     * are audit metadata, not site capabilities. */
    function buildSourceItems(payload) {
        var sources = Array.isArray(payload) ? payload : (payload && payload.sources) || [];
        return sources.filter(function (s) {
            return !s.status || s.status === 'integrated';
        }).map(function (s, i) {
            return {
                id: 'src-' + i,
                label: s.name,
                hint: s.provider || s.kind || 'Data source',
                href: s.url || '/api/sources',
                group: 'Sources',
                keywords: [s.name || '', s.provider || '', s.kind || '', s.purpose || '', 'data', 'source', 'dataset']
            };
        });
    }

    function rebuildIndex() {
        _allItems = []
            .concat(buildNavigationItems())
            .concat(buildActionItems())
            .concat(buildLocationItems())
            .concat(buildHazardItems(_hazards))
            .concat(buildGlossaryItems())
            .concat(buildBriefItems())
            .concat(buildSourceItems(_sources));
    }

    // -----------------------------------------------------------------------
    // Filtering (exported, DOM-free, testable)
    // -----------------------------------------------------------------------

    function matches(entry, query) {
        if (!query) return true;
        var q = query.toLowerCase();
        var haystack = [entry.label, entry.hint || '', entry.group || '']
            .concat(entry.keywords || [])
            .join(' ')
            .toLowerCase();
        return haystack.indexOf(q) !== -1;
    }

    function filterIndex(entries, query) {
        var q = String(query || '').trim();
        var out = entries.filter(function (e) { return matches(e, q); });
        // Cap per group, preserving group order.
        var byGroup = {};
        out.forEach(function (e) {
            byGroup[e.group] = byGroup[e.group] || [];
            if (byGroup[e.group].length < MAX_PER_GROUP) {
                byGroup[e.group].push(e);
            }
        });
        var ordered = [];
        GROUP_ORDER.forEach(function (g) {
            if (byGroup[g]) ordered = ordered.concat(byGroup[g]);
        });
        Object.keys(byGroup).forEach(function (g) {
            if (GROUP_ORDER.indexOf(g) === -1) ordered = ordered.concat(byGroup[g]);
        });
        return ordered;
    }

    // -----------------------------------------------------------------------
    // Fetching
    // -----------------------------------------------------------------------

    function fetchJSON(url) {
        return fetch(url)
            .then(function (r) { return r.json(); })
            .catch(function () { return null; });
    }

    function loadDynamicData() {
        if (_glossary && _briefs && _hazards && _sources) return Promise.resolve();
        return Promise.all([
            fetchJSON(API + '/v2/academy/glossary'),
            fetchJSON(API + '/v2/briefs'),
            fetchJSON(API + '/v2/hazards'),
            fetchJSON(API + '/sources')
        ]).then(function (results) {
            if (results[0]) _glossary = results[0];
            if (results[1]) _briefs = results[1];
            if (results[2]) _hazards = results[2];
            if (results[3]) _sources = results[3];
            rebuildIndex();
            if (_input) render(_input.value);
        });
    }

    // -----------------------------------------------------------------------
    // Rendering
    // -----------------------------------------------------------------------

    function contextHtml() {
        /* On an empty query the palette opens with the same assist model as
         * every search box: where you are searching from + a tip. */
        var last = (typeof HS !== 'undefined' && HS.lastLocation) ? HS.lastLocation() : null;
        var from = (last && (last.name || last.lat != null))
            ? '📍 ' + esc(last.name || (last.lat + ', ' + last.lon))
            : 'No recent location yet — search a place to set one.';
        return '<div class="search-context">' +
            '<div class="search-context-from">Searching from: <strong>' + from + '</strong></div>' +
            '<div class="search-context-tip">Tip: type a place, a hazard, a portal — or press ↑↓ and Enter to open the first result.</div>' +
            '</div>';
    }

    /* Per-type advanced-options panels, shown on an empty query when a
     * specific type tab is active: a short capability brief plus the group's
     * items. Descriptions state only what the site really does. */
    var TYPE_PANELS = {
        Navigation: { title: 'Pages', desc: 'Every portal and page on the platform.' },
        Actions: { title: 'Portal actions', desc: 'Start a real workflow: verify an asset, build a CSRD report, profile insurance risk, screen a supply chain.' },
        Location: { title: 'Location search', desc: 'Type any place name or lat,lon — the map, verification and profiling portals accept it directly.' },
        Hazards: { title: 'Hazard intelligence', desc: 'Per-hazard screening analysis computed from real, documented datasets. Pick a hazard to open its pipeline.' },
        Glossary: { title: 'Evidence vocabulary', desc: 'Every term links the discipline and dataset behind it.' },
        Briefs: { title: 'Evidence briefs', desc: 'Framework explainers and briefs grounded in documented sources.' },
        Sources: { title: 'Data sources', desc: 'The integrated public datasets behind the numbers this site shows.' }
    };

    function typePanelHtml(type) {
        var p = TYPE_PANELS[type];
        if (!p) return '';
        return '<div class="search-panel">' +
            '<div class="search-panel-title">' + esc(p.title) + '</div>' +
            '<div class="search-panel-desc">' + esc(p.desc) + '</div>' +
            '</div>';
    }

    function render(query) {
        _filteredItems = filterIndex(_allItems, query);
        if (_activeType !== 'all') {
            _filteredItems = _filteredItems.filter(function (e) { return e.group === _activeType; });
        }
        if (query && query.trim() && _filteredItems.length === 0) {
            /* Free text stays actionable whatever type is selected. */
            _filteredItems = buildFallbackItems(query);
        }
        _activeIndex = _filteredItems.length ? 0 : -1;

        if (!_resultsEl) return;

        if (_filteredItems.length === 0) {
            _resultsEl.innerHTML = '<div class="search-empty">No results. Try a location, hazard, or portal name.</div>';
            return;
        }

        var context = '';
        if (!query || !query.trim()) {
            context = _activeType === 'all' ? contextHtml() : typePanelHtml(_activeType);
        }

        var groups = {};
        _filteredItems.forEach(function (item, idx) {
            groups[item.group] = groups[item.group] || [];
            item._index = idx;
            groups[item.group].push(item);
        });

        var html = context;
        GROUP_ORDER.forEach(function (g) {
            if (!groups[g]) return;
            html += '<div class="search-group">' +
                '<div class="search-group-header">' + esc(g) + ' <span class="search-count">' + groups[g].length + '</span></div>' +
                groups[g].map(function (item) {
                    return '<a class="search-item" href="' + esc(item.href) + '" role="option" id="search-item-' + item._index + '" data-index="' + item._index + '">' +
                        '<div class="search-item-main">' +
                        '<span class="search-item-label">' + esc(item.label) + '</span>' +
                        '<span class="search-item-hint">' + esc(item.hint || '') + '</span>' +
                        '</div>' +
                        '</a>';
                }).join('') +
                '</div>';
        });

        _resultsEl.innerHTML = html;
        updateActive();
        bindItemClicks();
    }

    function updateActive() {
        if (!_resultsEl) return;
        qsa('.search-item').forEach(function (el) {
            el.classList.remove('active');
        });
        if (_activeIndex >= 0 && _activeIndex < _filteredItems.length) {
            var active = _resultsEl.querySelector('#search-item-' + _activeIndex);
            if (active) {
                active.classList.add('active');
                if (_input) _input.setAttribute('aria-activedescendant', active.id);
                active.scrollIntoView({ block: 'nearest' });
            }
        } else if (_input) {
            _input.removeAttribute('aria-activedescendant');
        }
    }

    function bindItemClicks() {
        if (!_resultsEl) return;
        qsa('.search-item').forEach(function (el) {
            el.addEventListener('click', function (ev) {
                ev.preventDefault();
                var idx = parseInt(el.getAttribute('data-index'), 10);
                _activeIndex = idx;
                navigate();
            });
            el.addEventListener('mouseenter', function () {
                _activeIndex = parseInt(el.getAttribute('data-index'), 10);
                updateActive();
            });
        });
    }

    function navigate() {
        if (_activeIndex < 0 || _activeIndex >= _filteredItems.length) return;
        var item = _filteredItems[_activeIndex];
        close();
        location.href = item.href;
    }

    // -----------------------------------------------------------------------
    // Overlay DOM
    // -----------------------------------------------------------------------

    function ensureContainer() {
        if (_container) return;
        _container = document.createElement('div');
        _container.className = 'search-overlay';
        _container.setAttribute('role', 'dialog');
        _container.setAttribute('aria-modal', 'true');
        _container.setAttribute('aria-label', 'Site search');
        _container.innerHTML =
            '<div class="search-backdrop"></div>' +
            '<div class="search-dialog">' +
            '<div class="search-input-wrap">' +
            '<svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            '<circle cx="11" cy="11" r="8"></circle>' +
            '<line x1="21" y1="21" x2="16.65" y2="16.65"></line>' +
            '</svg>' +
            '<input type="text" class="search-input" id="searchInput" placeholder="Search anything — pages, actions, hazards, sources…" autocomplete="off" aria-autocomplete="list" aria-controls="searchResults">' +
            '</div>' +
            '<div class="search-types" id="searchTypes" role="tablist" aria-label="Search types"></div>' +
            '<div class="search-results" id="searchResults" role="listbox"></div>' +
            '<div class="search-footer">↑↓ navigate · Enter open · Esc close · tabs filter by type · Cmd/Ctrl+K</div>' +
            '</div>';
        document.body.appendChild(_container);

        _input = _container.querySelector('#searchInput');
        _resultsEl = _container.querySelector('#searchResults');
        _typesEl = _container.querySelector('#searchTypes');
        renderTypes();

        _container.querySelector('.search-backdrop').addEventListener('click', close);
        _input.addEventListener('input', function () { render(_input.value); });
        _input.addEventListener('keydown', onKeyDown);
    }

    function renderTypes() {
        if (!_typesEl) return;
        _typesEl.innerHTML = TYPES.map(function (t) {
            var active = t.id === _activeType;
            return '<button type="button" class="search-type-tab' + (active ? ' active' : '') + '" role="tab" aria-selected="' + active + '" data-type="' + esc(t.id) + '">' + esc(t.label) + '</button>';
        }).join('');
        _typesEl.querySelectorAll('.search-type-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                setType(btn.getAttribute('data-type'));
                if (_input) _input.focus();
            });
        });
    }

    function setType(typeId) {
        _activeType = typeId || 'all';
        renderTypes();
        render(_input ? _input.value : '');
    }

    function onKeyDown(ev) {
        if (ev.key === 'ArrowDown') {
            ev.preventDefault();
            if (_filteredItems.length) {
                _activeIndex = (_activeIndex + 1) % _filteredItems.length;
                updateActive();
            }
        } else if (ev.key === 'ArrowUp') {
            ev.preventDefault();
            if (_filteredItems.length) {
                _activeIndex = (_activeIndex - 1 + _filteredItems.length) % _filteredItems.length;
                updateActive();
            }
        } else if (ev.key === 'Enter') {
            ev.preventDefault();
            navigate();
        } else if (ev.key === 'Escape') {
            ev.preventDefault();
            close();
        }
    }

    function open() {
        ensureContainer();
        _container.classList.add('open');
        document.body.classList.add('search-open');
        if (!_openedOnce) {
            _openedOnce = true;
            rebuildIndex();
            loadDynamicData().catch(function () { /* keep static index */ });
        }
        _activeType = 'all';
        renderTypes();
        render('');
        setTimeout(function () { _input && _input.focus(); }, 10);
    }

    function close() {
        if (!_container) return;
        _container.classList.remove('open');
        document.body.classList.remove('search-open');
        if (_input) _input.value = '';
        _filteredItems = [];
        _activeIndex = -1;
    }

    function isOpen() {
        return !!(_container && _container.classList.contains('open'));
    }

    // -----------------------------------------------------------------------
    // Global keyboard shortcuts
    // -----------------------------------------------------------------------

    document.addEventListener('keydown', function (ev) {
        if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') {
            ev.preventDefault();
            open();
            return;
        }
        if (ev.key === '/' && !isTypingTarget(ev.target)) {
            ev.preventDefault();
            open();
        }
        if (ev.key === 'Escape' && isOpen()) {
            ev.preventDefault();
            close();
        }
    });

    function isTypingTarget(el) {
        if (!el) return false;
        var tag = el.tagName.toLowerCase();
        var editable = el.isContentEditable;
        return tag === 'input' || tag === 'textarea' || tag === 'select' || editable;
    }

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    window.HSSearch = {
        open: open,
        close: close,
        isOpen: isOpen,
        filterIndex: filterIndex,
        // Internal helpers exposed for the Node harness.
        _buildActionItems: buildActionItems,
        _buildLocationItems: buildLocationItems,
        _buildFallbackItems: buildFallbackItems,
        _buildHazardItems: buildHazardItems,
        _buildSourceItems: buildSourceItems,
        _setType: setType
    };
})();
