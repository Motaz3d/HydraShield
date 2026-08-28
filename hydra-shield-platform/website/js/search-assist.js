/* Talaix — search assist: one unified on-focus dropdown for every search
 * box on the site.
 *
 * Clicking any search input opens a list with three sections, always in
 * the same order:
 *
 *   1. Where you are searching from — the last analysed/searched location
 *      (HS.lastLocation), one click to reuse it.
 *   2. Tips — short, page-specific hints for this exact box.
 *   3. Live context — current information relevant to the page (e.g. the
 *      highest-risk monitored areas right now), with an honest fallback
 *      when it is unavailable.
 *
 * The model is generic: pages register per-input configs in CONFIG below;
 * dynamic inputs (created after page load) work through event delegation.
 */
(function () {
    'use strict';

    var OPEN_CLASS = 'sa-open';

    function esc(s) {
        return (window.HS && HS.esc) ? HS.esc(s) : String(s == null ? '' : s);
    }

    function pageId() {
        return (document.body.getAttribute('data-page') || '').trim();
    }

    /* Live context providers — each returns HTML or a plain unavailable
     * note. Never invented numbers: the snapshot either serves real entries
     * or says it is unavailable. */
    function liveSnapshot(mount) {
        if (!window.HS || !HS.fetchJSON || !HS.API) return;
        HS.fetchJSON(HS.API + '/risk-snapshot').then(function (res) {
            var snap = res.body || {};
            if (!res.ok || snap.status !== 'ok' || !(snap.entries || []).length) {
                mount.innerHTML = '<div class="sa-live-note">Live risk signals are temporarily unavailable.</div>';
                return;
            }
            var items = snap.entries.slice(0, 3).map(function (e) {
                return '<a class="sa-live-item" href="map.html?location=' +
                    encodeURIComponent(e.name) + '">' +
                    '<span class="risk-badge risk-badge-' + esc(e.risk_class) + '">' +
                    esc((e.risk_class || '').toUpperCase()) + '</span> ' +
                    esc(e.name) + ' · ' + esc(Number(e.risk).toFixed(0)) + '</a>';
            });
            mount.innerHTML = '<div class="sa-live-title">Highest-risk monitored areas right now:</div>' +
                items.join('');
        }).catch(function () {
            mount.innerHTML = '<div class="sa-live-note">Live risk signals could not be reached.</div>';
        });
    }

    /* Per-page, per-input configuration. tips: 2–4 short strings.
     * live: 'snapshot' | null. */
    var CONFIG = {
        map: {
            locInput: {
                tips: [
                    'Type a place name or coordinates (lat,lon) — both work.',
                    'Layers, years and the evidence filter live in the sidebar.',
                    'Switch to Map Check mode (top right) to verify a place against satellite observation.'
                ],
                live: 'snapshot'
            },
            mapcheckLocInput: {
                tips: [
                    'Pick a place you want to cross-verify — map data vs satellite.',
                    'A discrepancy is a signal to verify, never proof of an error.'
                ],
                live: null
            }
        },
        intelligence: {
            locWidget_q: {
                tips: [
                    'Type a place name or coordinates, then choose a hazard tab.',
                    'The wildfire tab is the full pipeline: reports, map and history.'
                ],
                live: 'snapshot'
            },
            locationInput: {
                tips: [
                    'The full wildfire pipeline runs here: stages, scenarios, map, history.',
                    'Enter a place name or lat,lon and press Analyze.'
                ],
                live: null
            },
            eventsLocInput: {
                tips: ['Search historical hazard events near any place.'],
                live: 'snapshot'
            },
            locInput: {
                tips: ['Economic exposure is profiled per location — never monetised without a documented basis.'],
                live: 'snapshot'
            }
        },
        solutions: { locInput: { tips: ['Solutions are matched to the exact site — with limitations stated.'], live: 'snapshot' } },
        story: { locInput: { tips: ['Optional: follow the story with a real place you know.'], live: null } },
        'report-builder': {
            locationInput: {
                tips: [
                    'Choose a product first, then give the location its report is about.',
                    'Drafts are editable before PDF export — nothing is final until you say so.'
                ],
                live: null
            }
        },
        academy: {
            glossarySearch: {
                tips: ['Search the evidence vocabulary — every term links its source discipline.'],
                live: null
            }
        },
        industries: {
            audienceAnalyzeInput: {
                tips: [
                    'Run a real location live — the first analysis needs no account.',
                    'A free account keeps what you analyse saved, monitored and reported.'
                ],
                live: 'snapshot'
            }
        }
    };

    function lastLocationHtml(input) {
        var last = (window.HS && HS.lastLocation) ? HS.lastLocation() : null;
        if (!last || (last.lat == null && !last.name)) {
            return '<div class="sa-section"><div class="sa-heading">Searching from</div>' +
                '<div class="sa-note">No recent location yet — type a place name or lat,lon.</div></div>';
        }
        var label = last.name || (last.lat + ', ' + last.lon);
        return '<div class="sa-section"><div class="sa-heading">Searching from</div>' +
            '<button type="button" class="sa-use">' +
            '<span class="sa-use-name">📍 ' + esc(label) + '</span>' +
            '<span class="sa-use-hint">click to reuse</span></button></div>';
    }

    function useLastLocation(input) {
        var last = (window.HS && HS.lastLocation) ? HS.lastLocation() : null;
        if (!last) return;
        input.value = last.name || (last.lat + ',' + last.lon);
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function tipsHtml(tips) {
        if (!tips || !tips.length) return '';
        return '<div class="sa-section"><div class="sa-heading">Tips</div><ul class="sa-tips">' +
            tips.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') +
            '</ul></div>';
    }

    function closeAll() {
        document.querySelectorAll('.sa-dropdown.' + OPEN_CLASS).forEach(function (d) {
            d.classList.remove(OPEN_CLASS);
        });
    }

    function openFor(input, cfg) {
        closeAll();
        var dd = input._saDropdown;
        if (!dd) {
            dd = document.createElement('div');
            dd.className = 'sa-dropdown';
            input._saDropdown = dd;
            (input.closest('.panel, .toolbar, form, .search-row, .map-sidebar, .form-group') ||
             input.parentElement).appendChild(dd);
            dd.addEventListener('mousedown', function (e) {
                // Keep the input's blur from closing before a click lands.
                e.preventDefault();
            });
            dd.addEventListener('click', function (e) {
                var use = e.target.closest('.sa-use');
                if (use) { useLastLocation(input); closeAll(); input.focus(); }
            });
        }
        dd.innerHTML =
            lastLocationHtml(input) +
            tipsHtml(cfg.tips) +
            (cfg.live ? '<div class="sa-section"><div class="sa-heading">Live now</div><div class="sa-live"><span class="sa-note">Loading…</span></div></div>' : '');
        dd.classList.add(OPEN_CLASS);
        if (cfg.live === 'snapshot') {
            liveSnapshot(dd.querySelector('.sa-live'));
        }
    }

    function configFor(input) {
        var pageCfg = CONFIG[pageId()];
        if (!pageCfg || !pageCfg[input.id]) return null;
        return pageCfg[input.id];
    }

    function init() {
        // Delegated so dynamically created inputs (industries hub, widgets)
        // get the same treatment without extra wiring.
        document.addEventListener('focusin', function (e) {
            var input = e.target.closest('input[type="text"], input[type="search"]');
            if (!input) return;
            var cfg = configFor(input);
            if (cfg) openFor(input, cfg);
        });
        document.addEventListener('focusout', function (e) {
            if (e.target.matches && e.target.matches('input')) {
                setTimeout(closeAll, 120);
            }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeAll();
        });
        document.addEventListener('click', function (e) {
            if (!e.target.closest('.sa-dropdown') && !e.target.closest('input')) closeAll();
        });
    }

    window.HS = window.HS || {};
    window.HS.searchAssist = { openFor: openFor, configFor: configFor };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
