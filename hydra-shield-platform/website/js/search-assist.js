/* Talaix — search assist: one unified on-focus dropdown for every search
 * box on the site.
 *
 * Clicking any covered search input opens a compact helper — never an
 * empty box. Sections appear in this fixed order, each optional:
 *
 *   1. Context — one dynamic line (e.g. the active hazard on the
 *      Intelligence page), read from the live DOM at open time.
 *   2. Quick picks — up to three clickable chips that fill the input
 *      (no auto-submit; the user still presses the action button).
 *   3. Searching from — the last analysed/searched location
 *      (HS.lastLocation), one click to reuse it.
 *   4. Tips — at most two short, page-specific hints for this exact box.
 *   5. Live now — current information relevant to the page (e.g. the
 *      highest-risk monitored areas right now), with an honest fallback
 *      when it is unavailable.
 *
 * The model is generic: pages register per-input configs in CONFIG below,
 * keyed by data-page attribute then input id (or name); dynamic inputs
 * (created after page load) work through event delegation.
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

    /* Per-page, per-input configuration. Keys match each page's
     * data-page attribute; inner keys match the input's id (or name).
     * tips: up to 2 short strings. chips: up to 3 quick-pick values that
     * fill the input on click. context: 'activeHazard' | null.
     * live: 'snapshot' | null. */
    var MAX_TIPS = 2;
    var MAX_CHIPS = 3;

    var CONFIG = {
        map: {
            locInput: {
                tips: [
                    'Type a place name or coordinates (lat,lon) — both work.',
                    'Layers, years and the evidence filter live in the sidebar.'
                ],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            },
            mapcheckLocInput: {
                tips: [
                    'Pick a place you want to cross-verify — map data vs satellite.',
                    'A discrepancy is a signal to verify, never proof of an error.'
                ],
                chips: ['Clervaux, Luxembourg'],
                live: null
            }
        },
        intelligence: {
            locWidget_q: {
                context: 'activeHazard',
                tips: ['Type a place name or coordinates, then press Analyze.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            },
            locationInput: {
                context: 'activeHazard',
                tips: ['The full wildfire pipeline runs here: stages, scenarios, map, history.'],
                chips: ['Clervaux, Luxembourg', '50.06, 6.03'],
                live: null
            },
            eventsLocInput: {
                tips: ['Search historical hazard events near any place.'],
                chips: ['50.06, 6.03', 'Clervaux, Luxembourg'],
                live: 'snapshot'
            },
            locInput: {
                tips: ['Economic exposure is profiled per location — never monetised without a documented basis.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal'],
                live: 'snapshot'
            },
            solLocInput: {
                tips: ['Solutions are matched to the exact site — with limitations stated.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            }
        },
        about: {
            locInput: {
                tips: ['Optional: follow the story with a real place you know.'],
                chips: ['Faro, Portugal'],
                live: null
            }
        },
        reportbuilder: {
            locationInput: {
                tips: [
                    'Choose a product first, then give the location its report is about.',
                    'Drafts are editable before PDF export — nothing is final until you say so.'
                ],
                chips: ['Clervaux, Luxembourg'],
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
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal'],
                live: 'snapshot'
            }
        },
        home: {
            location: {
                tips: ['Opens the live map for the place — layers, years and evidence included.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            }
        },
        greenfinance: {
            assetLocInput: {
                tips: [
                    'Verification screens the asset against documented hazard and exposure datasets.',
                    'Every figure links its basis — nothing is asserted without a source.'
                ],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            }
        },
        insurance: {
            assetLocInput: {
                tips: ['The profile screens perils at the exact site — screening levels, never loss promises.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            }
        },
        forensics: {
            caseSiteInput: {
                tips: ['The case site anchors every cross-check: map, satellite and documented events.'],
                chips: ['Clervaux, Luxembourg', '50.06, 6.03'],
                live: null
            }
        },
        supplychain: {
            countryInput: {
                tips: ['Origin claims are screened against documented deforestation and hazard datasets.'],
                chips: ['Brazil', 'Indonesia', 'Ghana'],
                live: null
            },
            commodityInput: {
                tips: ['EUDR covers cattle, cocoa, coffee, oil palm, rubber, soya and wood.'],
                chips: ['soy', 'cocoa', 'palm oil'],
                live: null
            }
        },
        press: {
            pressLocInput: {
                tips: ['Press packs quote only documented figures for the chosen place.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal'],
                live: 'snapshot'
            }
        },
        reports: {
            legacyLocInput: {
                tips: ['Reports assemble documented analysis for the place — editable before export.'],
                chips: ['Clervaux, Luxembourg', '50.06, 6.03'],
                live: null
            }
        },
        licensing: {
            licSiteInput: {
                tips: ['The site anchors the licensing dossier: hazards, exposure and documented context.'],
                chips: ['Almería, Spain', '39.62, 22.39'],
                live: null
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
            tips.slice(0, MAX_TIPS).map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') +
            '</ul></div>';
    }

    /* One dynamic context line, read from the live DOM at open time.
     * 'activeHazard': the currently selected hazard tab on Intelligence. */
    function contextHtml(cfg) {
        if (cfg.context !== 'activeHazard') return '';
        var tab = document.querySelector('#hazardTabs .hazard-tab.active');
        var name = tab ? tab.textContent.trim() : '';
        if (!name) return '';
        return '<div class="sa-section"><div class="sa-context">Active hazard: <strong>' +
            esc(name) + '</strong> — pick a place, then Analyze.</div></div>';
    }

    /* Quick picks: clickable chips that fill the input (no auto-submit). */
    function chipsHtml(chips) {
        if (!chips || !chips.length) return '';
        return '<div class="sa-section"><div class="sa-heading">Quick picks</div><div class="sa-chips">' +
            chips.slice(0, MAX_CHIPS).map(function (c) {
                return '<button type="button" class="sa-chip" data-value="' + esc(c) + '">' + esc(c) + '</button>';
            }).join('') +
            '</div></div>';
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
                if (use) { useLastLocation(input); closeAll(); input.focus(); return; }
                var chip = e.target.closest('.sa-chip');
                if (chip) {
                    input.value = chip.getAttribute('data-value') || '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    closeAll();
                    input.focus();
                }
            });
        }
        dd.innerHTML =
            contextHtml(cfg) +
            chipsHtml(cfg.chips) +
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
        if (!pageCfg) return null;
        var key = input.id || input.getAttribute('name') || '';
        return pageCfg[key] || null;
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
