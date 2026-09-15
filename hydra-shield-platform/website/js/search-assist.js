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
            },
            'sec-loc-input': {
                tips: ['Screen the location against the selected sector exposure profile.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            },
            fundLocWidget_q: {
                tips: ['Match public funding programmes to this location.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal'],
                live: null
            }
        },
        about: {
            locInput: {
                tips: ['Optional: follow the story with a real place you know.'],
                chips: ['Faro, Portugal'],
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
        sustainability: {
            applName: {
                tips: ['Your legal company name — used only for the screening determination.'],
                live: null
            },
            applCountry: {
                tips: ['Country of establishment — drives the CSRD wave calendar.'],
                chips: ['Luxembourg', 'Germany', 'France', 'United States'],
                live: null
            },
            companyName: {
                tips: ['Company-supplied — not verified by Talaix.'],
                live: null
            },
            companySector: {
                tips: ['The sector drives which ESRS datapoints are material.'],
                chips: ['renewable energy', 'manufacturing', 'real estate', 'agriculture'],
                live: null
            },
            companyCountry: {
                chips: ['Luxembourg', 'Germany', 'France'],
                live: null
            },
            companyWebsite: {
                tips: ['Optional — appears in the report header.'],
                live: null
            },
            assetsText: {
                tips: [
                    'One site per line: a place name, or name,lat,lon — max 25 free, 100 for subscribers.',
                    'Each site becomes its own per-hazard assessment in the pack.'
                ],
                chips: ['Trier factory,49.75,6.64', 'A Coruña port,43.3,-8.4'],
                live: null
            },
            applEmployees: {
                tips: ['CSRD threshold: more than 250 average employees.'],
                chips: ['250', '500', '1000'],
                live: null
            },
            applTurnover: {
                tips: ['CSRD threshold: net turnover above €50M.'],
                chips: ['€50M|50000000', '€100M|100000000'],
                live: null
            },
            applBalance: {
                tips: ['CSRD threshold: balance-sheet total above €25M.'],
                chips: ['€25M|25000000', '€50M|50000000'],
                live: null
            },
            applYear: {
                tips: ['Reporting year — wave-2 reports cover FY2027.'],
                chips: ['2027', '2028'],
                live: null
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
            },
            portfolioName: {
                tips: ['Name this portfolio batch — used as its label in the report.'],
                live: null
            },
            portfolioText: {
                tips: ['One asset per line: name,lat,lon — each asset is screened individually.'],
                chips: ['Asset A,49.75,6.64'],
                live: null
            }
        },
        insurance: {
            assetLocInput: {
                tips: ['The profile screens perils at the exact site — screening levels, never loss promises.'],
                chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'],
                live: 'snapshot'
            },
            portfolioName: {
                tips: ['Name this insured portfolio — used as its label in the report.'],
                live: null
            },
            radiusInput: {
                tips: ['Screening radius in km around the asset (default 50).'],
                live: null
            },
            portfolioText: {
                tips: ['One asset per line: name,lat,lon — each asset is profiled per peril.'],
                chips: ['Asset A,49.75,6.64'],
                live: null
            },
            portfolioRadiusInput: {
                tips: ['Screening radius in km for the portfolio.'],
                live: null
            }
        },
        forensics: {
            caseSiteInput: {
                tips: ['The case site anchors every cross-check: map, satellite and documented events.'],
                chips: ['Clervaux, Luxembourg', '50.06, 6.03'],
                live: null
            },
            caseTitle: {
                tips: ['A short title for this case — visible in the evidence pack.'],
                live: null
            },
            caseRadiusInput: {
                tips: ['Search radius in km around the case site (default 25).'],
                live: null
            },
            caseDocs: {
                tips: ['Optional: paste or describe the documents the claim is based on.'],
                live: null
            }
        },
        supplychain: {
            supplierInput: {
                tips: ['Supplier name — company-supplied, not verified by Talaix.'],
                live: null
            },
            countryInput: {
                tips: ['Origin claims are screened against documented deforestation and hazard datasets.'],
                chips: ['Brazil', 'Indonesia', 'Ghana'],
                live: null
            },
            commodityInput: {
                tips: ['EUDR covers cattle, cocoa, coffee, oil palm, rubber, soya and wood.'],
                chips: ['soy', 'cocoa', 'palm oil'],
                live: null
            },
            plotsText: {
                tips: [
                    'One plot per line: name,lat,lon — up to 25 on the free tier.',
                    'Coordinates keep the screening honest — a place name alone is approximate.'
                ],
                chips: ['Plot A,49.75,6.64', 'Plot B,43.3,-8.4'],
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
            },
            locationInput: {
                tips: [
                    'Choose a product first, then give the location its report is about.',
                    'Drafts are editable before PDF export — nothing is final until you say so.'
                ],
                chips: ['Clervaux, Luxembourg'],
                live: null
            }
        },
        licensing: {
            licSiteInput: {
                tips: ['The site anchors the licensing dossier: hazards, exposure and documented context.'],
                chips: ['Almería, Spain', '39.62, 22.39'],
                live: null
            },
            licJurisdiction: {
                tips: ['The permitting jurisdiction — e.g. region and country.'],
                chips: ['Almería, Spain', 'Wallonia, Belgium'],
                live: null
            },
            licTitle: {
                tips: ['Project title — e.g. "Helios 50 MW".'],
                live: null
            },
            licRadiusInput: {
                tips: ['Screening radius in km around the site (default 25).'],
                live: null
            },
            licDescription: {
                tips: ['Short project description — e.g. ground-mounted solar plant.'],
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
                var parts = String(c).split('|');
                var label = parts[0];
                var value = parts.length > 1 ? parts.slice(1).join('|') : parts[0];
                return '<button type="button" class="sa-chip" data-value="' + esc(value) + '">' + esc(label) + '</button>';
            }).join('') +
            '</div></div>';
    }

    function closeAll() {
        document.querySelectorAll('.sa-dropdown.' + OPEN_CLASS).forEach(function (d) {
            d.classList.remove(OPEN_CLASS);
        });
    }

    function openFor(input, cfg) {
        var dd = input._saDropdown;
        if (dd && dd.classList.contains(OPEN_CLASS)) {
            return; // already open for this input — a click while it holds focus
        }
        closeAll();
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

    /* Open the helper for an input on either keyboard focus or a mouse click.
     * A click is handled separately from focusin because a click on an input
     * that is already focused fires no focusin, yet the user still expects the
     * dropdown to appear every time they press the field. */
    function openInput(input) {
        var cfg = configFor(input);
        if (!cfg) return;
        if (blurTimer) { clearTimeout(blurTimer); blurTimer = null; }
        openFor(input, cfg);
    }

    /* Additional per-field configs — kept separate so the main CONFIG above
     * stays easy to scan. Every field listed here gets a tailored helper;
     * any other text/number/textarea field still gets a sensible generic
     * helper via defaultConfig() below, so no search box is ever left empty. */
    var EXTRA_CONFIG = {
        reports: {
            radiusInput: { tips: ['Search radius in km around the location (default 50).'], live: null },
            companyName: { tips: ['Company name — company-supplied, not verified by Talaix.'], live: null },
            companySector: { tips: ['The sector drives which datapoints are material.'], chips: ['renewable energy', 'manufacturing', 'real estate', 'agriculture'], live: null },
            companyCountry: { chips: ['Luxembourg', 'Germany', 'France'], live: null },
            companyWebsite: { tips: ['Optional — appears in the report header.'], live: null },
            companyDescription: { tips: ['Short company description — appears in the report.'], live: null },
            assetsText: { tips: ['One site per line: name,lat,lon — each site is assessed individually.'], chips: ['Headquarters,49.6116,6.1319', 'Sevilla, Spain'], live: null },
            draftTitle: { tips: ['Report title — editable before PDF export.'], live: null }
        },
        intelligence: {
            eventsRadius: { tips: ['Search radius in km for historical events (default 50).'], live: null },
            economyRadius: { tips: ['Radius in km for the economic-exposure profile (default 5).'], live: null }
        },
        map: {
            advCompareInput: { tips: ['Compare this place against another — place name or lat,lon.'], chips: ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'], live: 'snapshot' }
        },
        forensics: {
            caseClaimText: { tips: ['Optional: the exact claim under investigation — quoted verbatim in the evidence pack.'], live: null }
        },
        academy: {
            verifyCertId: { tips: ['Paste a certificate ID (TX-…) to verify its authenticity.'], live: null }
        }
    };

    function isLocationField(input) {
        var key = (input.id || input.getAttribute('name') || '').toLowerCase();
        return /(loc|location|site|place|asset|plot|portfolio|area|address|coordinates|lat|lon|compare)/.test(key);
    }

    function defaultConfig(input) {
        var cfg = {
            tips: ['Type a place name, coordinates (lat,lon), or the value this field expects.'],
            live: null
        };
        if (isLocationField(input)) {
            cfg.tips = ['Type a place name or coordinates (lat,lon) — both work.'];
            cfg.chips = ['Clervaux, Luxembourg', 'Faro, Portugal', '50.06, 6.03'];
        }
        return cfg;
    }

    function configFor(input) {
        var pid = pageId();
        var key = input.id || input.getAttribute('name') || '';
        var pageCfg = CONFIG[pid];
        if (pageCfg && pageCfg[key]) return pageCfg[key];
        var extraCfg = EXTRA_CONFIG[pid];
        if (extraCfg && extraCfg[key]) return extraCfg[key];
        return defaultConfig(input);
    }

    var blurTimer = null;

    function init() {
        // Delegated so dynamically created inputs (industries hub, widgets)
        // get the same treatment without extra wiring. Covers text, search,
        // number and textarea so every field can carry a helper dropdown.
        var SELECTOR = 'input[type="text"], input[type="search"], input[type="number"], textarea';
        document.addEventListener('focusin', function (e) {
            var input = e.target.closest(SELECTOR);
            if (!input) return;
            openInput(input);
        });
        document.addEventListener('focusout', function (e) {
            if (e.target.matches && (e.target.matches('input') || e.target.matches('textarea'))) {
                if (blurTimer) clearTimeout(blurTimer);
                blurTimer = setTimeout(closeAll, 120);
            }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeAll();
        });
        document.addEventListener('click', function (e) {
            var input = e.target.closest(SELECTOR);
            if (input) { openInput(input); return; }
            if (!e.target.closest('.sa-dropdown')) closeAll();
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
