/* Talaix — audience portals (for-* pages).
 *
 * Turns each audience page (banks, investors, government, real estate, insurance,
 * consulting) into an interactive mini-portal:
 *
 *   1. A live "try it now" analyze bar → routes into the real analysis
 *      flow (first look never gated — conversion philosophy).
 *   2. A live risk-signals strip from /api/risk-snapshot (real monitored
 *      areas; honest unavailable state — never placeholder numbers).
 *   3. An account panel: what a FREE account concretely unlocks for this
 *      audience, with register/sign-in actions and the conversion
 *      engine's escalation strip (HSConvert.evaluate).
 *
 * All claims in the benefit lists are backed by shipped account features
 * (saved locations, email alerts, history, PDF reports). Nothing here
 * invents capabilities or numbers.
 */
(function () {
    'use strict';

    var esc = HS.esc, fetchJSON = HS.fetchJSON, API = HS.API;

    var CONFIGS = {
        'for-banks': {
            tryTitle: 'Screen collateral live — right here',
            trySubtitle: 'Enter a financed asset or collateral location and get the evidence-labelled multi-hazard context for the credit file.',
            placeholder: 'Enter a collateral location…',
            benefitsTitle: 'What a free account unlocks for banks & lenders',
            benefits: [
                ['📌', 'Saved collateral locations', 'Keep financed assets saved and re-screened against fresh data as conditions change.'],
                ['🔔', 'Event alerts', 'Email alerts when monitored collateral enters hazardous conditions — inputs to watchlist reviews.'],
                ['🧾', 'Evidence trail', 'OBSERVED / MODELLED labels and named sources on every figure — documentation for the credit file.'],
                ['📊', 'Portfolio reports', 'Per-location PDF reports that can feed disclosure and risk-committee packs.']
            ],
            note: 'Climate-risk evidence for credit workflows — screening indicators, not credit decisions or compliance guarantees.'
        },
        'for-investors': {
            tryTitle: 'Screen an asset live — right here',
            trySubtitle: 'Enter any asset location or region and get the real multi-hazard picture before you commit capital.',
            placeholder: 'Enter an asset location or region…',
            benefitsTitle: 'What a free account unlocks for investors',
            benefits: [
                ['📌', 'Saved assets', 'Every screened asset kept in one place and revisited with fresh data — not stale exports.'],
                ['🔔', 'Monitoring alerts', 'Email alerts when conditions at your saved locations cross the thresholds you set.'],
                ['📚', 'Analysis history', 'Each analysis kept with its evidence and provenance — an audit trail for the investment committee.'],
                ['📊', 'Decision reports', 'Per-asset PDF reports with sources and uncertainty stated explicitly.']
            ],
            note: 'Climate-evidence intelligence — not financial, investment or legal advice. Figures are traceable to sources or honestly not quantified.'
        },
        'for-government': {
            tryTitle: 'Analyze your territory live — right here',
            trySubtitle: 'Enter your municipality or region and see the current multi-hazard picture computed from real datasets.',
            placeholder: 'Enter your municipality or region…',
            benefitsTitle: 'What a free account unlocks for public authorities',
            benefits: [
                ['📌', 'Watched places', 'Keep the critical points of your territory under continuous watch from one account.'],
                ['🔔', 'Alert subscriptions', 'Email alerts on threshold crossings at the places you are responsible for.'],
                ['📄', 'Decision-support reports', 'PDF reports for councils and planners — evidence-labelled, sources named.'],
                ['🧾', 'Evidence for funding', 'Documented hazard evidence to attach to resilience and adaptation applications.']
            ],
            note: 'Screening indicators for planning support — labelled as such, with the data provenance attached.'
        },
        'for-real-estate': {
            tryTitle: 'Check a property live — right here',
            trySubtitle: 'Enter a property address or plot and see its multi-hazard exposure before you price, buy or develop.',
            placeholder: 'Enter a property address or plot…',
            benefitsTitle: 'What a free account unlocks for property professionals',
            benefits: [
                ['🏘️', 'Property watchlist', 'Save every property you screened and come back to updated conditions anytime.'],
                ['🔔', 'Change alerts', 'Email alerts when monitored properties see conditions cross your thresholds.'],
                ['📚', 'Screening history', 'A documented record per property — what was analysed, when, from which data.'],
                ['📊', 'Client-ready reports', 'PDF reports with honest labels you can hand to a buyer, lender or board.']
            ],
            note: 'Exposure screening from real mapped data — completeness caveats are stated, never hidden.'
        },
        'for-insurance': {
            tryTitle: 'Underwrite with live evidence — right here',
            trySubtitle: 'Enter an insured location or region and get the evidence-labelled multi-hazard context for the risk file.',
            placeholder: 'Enter an insured location or region…',
            benefitsTitle: 'What a free account unlocks for insurers',
            benefits: [
                ['📌', 'Book locations', 'Keep insured locations saved and re-screened against fresh data.'],
                ['🔔', 'Event alerts', 'Email alerts when monitored locations enter hazardous conditions.'],
                ['🧾', 'Evidence trail', 'OBSERVED / MODELLED labels and named sources on every figure in the file.'],
                ['📊', 'Risk reports', 'Per-location PDF reports for underwriting and reinsurance discussions.']
            ],
            note: 'Evidence inputs for underwriting judgement — screening indicators, not loss guarantees.'
        },
        'for-consulting': {
            tryTitle: 'Run a client site live — right here',
            trySubtitle: 'Enter a client site and get the multi-hazard evidence base your engagement starts from.',
            placeholder: 'Enter a client site…',
            benefitsTitle: 'What a free account unlocks for consultants',
            benefits: [
                ['📌', 'Client locations', 'A saved location per client site — revisit with current data at each engagement phase.'],
                ['🔔', 'Monitoring between visits', 'Email alerts keep the engagement current between field visits.'],
                ['📚', 'Reusable evidence', 'Analyses persisted with provenance — cite them directly in deliverables.'],
                ['📊', 'Deliverable reports', 'PDF reports whose evidence labels strengthen, not weaken, your credibility.']
            ],
            note: 'Your expertise, our evidence base — every figure traceable to its dataset.'
        }
    };

    function renderHub(cfg) {
        var hub = document.getElementById('audienceHub');
        if (!hub) return null;
        hub.innerHTML =
            '<div class="hub-grid">' +
            '  <div class="panel" style="margin-bottom:0;">' +
            '    <h2>' + esc(cfg.tryTitle) + '</h2>' +
            '    <p>' + esc(cfg.trySubtitle) + '</p>' +
            '    <form id="audienceAnalyzeForm" class="hub-try-form">' +
            '      <input type="text" id="audienceAnalyzeInput" placeholder="' + esc(cfg.placeholder) + '" aria-label="Location" required>' +
            '      <button type="submit" class="btn btn-primary">Analyze it live</button>' +
            '    </form>' +
            '    <div id="audienceSignals" class="hub-signals">' +
            '      <span class="muted small">Loading live risk signals…</span>' +
            '    </div>' +
            '  </div>' +
            '  <div class="panel hub-account" style="margin-bottom:0;">' +
            '    <h2>' + esc(cfg.benefitsTitle) + '</h2>' +
            '    <ul class="hub-benefits">' +
            cfg.benefits.map(function (b) {
                return '<li><span class="hub-benefit-ico">' + b[0] + '</span>' +
                    '<span><strong>' + esc(b[1]) + '</strong> — ' + esc(b[2]) + '</span></li>';
            }).join('') +
            '    </ul>' +
            '    <div class="hub-actions">' +
            '      <a href="account.html" class="btn btn-primary" id="audienceRegisterBtn">Create a free account</a>' +
            '      <a href="account.html" class="btn btn-outline">Sign in</a>' +
            '    </div>' +
            '    <p class="muted small">Free tier, no card. Paid tiers exist for heavier use — ' +
            '    the platform says so at the moment you reach them.</p>' +
            '    <div id="audienceConvert"></div>' +
            '  </div>' +
            '</div>' +
            '<p class="muted small" style="margin-top:12px;">' + esc(cfg.note) + '</p>';
        return hub;
    }

    function wireForm() {
        var form = document.getElementById('audienceAnalyzeForm');
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var q = document.getElementById('audienceAnalyzeInput').value.trim();
            if (!q) return;
            if (window.HS && HS.track) HS.track('audience_analyze_submitted', { page: pageId() });
            location.href = 'intelligence.html?location=' + encodeURIComponent(q);
        });
        document.getElementById('audienceRegisterBtn').addEventListener('click', function () {
            if (window.HS && HS.track) HS.track('cta_clicked', { feature: 'audience_register_' + pageId() });
        });
    }

    function pageId() {
        return document.body.getAttribute('data-page') || 'unknown';
    }

    /* Live signals: top monitored areas from the real snapshot. */
    function loadSignals() {
        var mount = document.getElementById('audienceSignals');
        fetchJSON(API + '/risk-snapshot').then(function (res) {
            var snap = res.body || {};
            if (!res.ok || snap.status !== 'ok' || !(snap.entries || []).length) {
                mount.innerHTML = '<span class="muted small">Live risk signals are temporarily ' +
                    'unavailable — the live analysis above always works.</span>';
                return;
            }
            var items = snap.entries.slice(0, 3).map(function (e) {
                return '<a class="hub-signal" href="map.html?location=' +
                    encodeURIComponent(e.name) + '">' +
                    '<span class="risk-badge risk-badge-' + esc(e.risk_class) + '">' +
                    esc((e.risk_class || '').toUpperCase()) + '</span> ' +
                    esc(e.name) + ' · ' + esc(Number(e.risk).toFixed(0)) + '</a>';
            });
            mount.innerHTML =
                '<div class="hub-signals-title">Live now — highest-risk monitored areas:</div>' +
                '<div class="hub-signals-row">' + items.join('') + '</div>';
        }).catch(function () {
            mount.innerHTML = '<span class="muted small">Live risk signals could not be ' +
                'reached — the live analysis above always works.</span>';
        });
    }

    function init() {
        var cfg = CONFIGS[pageId()];
        if (!cfg || !document.getElementById('audienceHub')) return;
        renderHub(cfg);
        wireForm();
        loadSignals();
        if (window.HSConvert) HSConvert.evaluate('audienceConvert');
        if (window.HS && HS.track) HS.track('audience_hub_viewed', { page: pageId() });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
