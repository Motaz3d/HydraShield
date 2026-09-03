/* Talaix — Industries hub (consolidated audience portals).
 *
 * One page carries the six industry portals that used to be separate
 * for-*.html pages (banks, insurance, investors, real estate, consulting,
 * government). ?sector=<id> deep-links a sector; the old URLs 301 here
 * (see Caddyfile). Content is data-driven from SECTORS below — a new
 * industry is added by extending one config, never a new page.
 *
 * Each sector renders: hero copy + CTAs, the interactive hub (live
 * analyze bar → real analysis flow, live risk signals strip from
 * /api/risk-snapshot, free-account benefits panel), the sector's content
 * cards and any extra sections (journey / frameworks), then the closing
 * CTA. All claims are backed by shipped features; nothing invents
 * capabilities or numbers.
 */
(function () {
    'use strict';

    var esc = HS.esc, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    var SECTORS = {
        banks: {
            tab: 'Banks & lenders',
            badge: 'For banks & lenders',
            title: 'Environmental-risk intelligence for credit decisions',
            sub: 'Collateral screening, portfolio exposure mapping and climate stress-test ' +
                 'support from one evidence base — hazard analysis, historical events, ' +
                 'exposure counts and provenance-carrying reports, with uncertainty stated ' +
                 'instead of hidden.',
            actions: [
                ['intelligence.html', 'btn btn-primary', 'Screen collateral'],
                ['contact.html', 'btn btn-outline', 'Discuss a portfolio pilot']
            ],
            hub: {
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
            cards: [
                ['🏦 Collateral risk screening', 'Per-asset screening across wildfire, flood, drought, heat, wind, coastal exposure and tropical cyclones — with historical event evidence and the data provenance a credit file needs.'],
                ['🗺️ Portfolio exposure mapping', 'Aggregate exposure by geography, sector or asset class — population, buildings, critical facilities and land cover counted from real mapped data, with completeness caveats visible.'],
                ['📊 Stress-testing inputs', 'Hazard screening levels and historical event histories that can feed into your own PD/LGD and concentration-risk workflows — inputs to internal models, never a replacement for them.'],
                ['📄 Disclosure support', 'Evidence-labelled reports and source registries that help prepare disclosures under TCFD/ISSB IFRS S2, CSRD/ESRS and EU Taxonomy requirements — supporting alignment, not asserting compliance.']
            ],
            disclaimer: 'Talaix provides climate-risk evidence and exposure intelligence. It is not a credit-rating tool, not an actuarial model, and not a substitute for your own credit, risk or compliance judgement. Nothing here is a guarantee of regulatory alignment or compliance.',
            extra: {
                tag: 'Regulatory context',
                title: 'Helps prepare for the frameworks you face',
                subtitle: 'The same traceable evidence base can support alignment with multiple banking and disclosure regimes — as inputs, not as certified outputs.',
                cards: [
                    ['TCFD / ISSB IFRS S2', 'Governance and strategy discussions supported by location-level hazard evidence, scenario context and historical event data — documented, not modelled in secret.'],
                    ['CSRD / ESRS', 'Exposure counts, data-source registries and evidence-labelled reports that help substantiate climate-related disclosures and risk assessments.'],
                    ['EU Taxonomy', 'Screening for climate-related physical risks that can feed into taxonomy-alignment assessments — one input among many in your own substantiation process.'],
                    ['EBA / ECB climate stress tests', 'Hazard and exposure data that can be used as inputs to internal climate stress-test exercises, including EBA and ECB programmes — we do not provide the bank\'s final stress-test results.'],
                    ['BaFin / ECB Guide on climate-related risks', 'Risk-identification and monitoring workflows that can support materiality assessment and risk-management documentation — aligned with supervisory expectations as an input, not a verdict.'],
                    ['Concentration risk', 'Geographic and sector exposure views that can inform concentration limits and risk-appetite discussions — with the underlying evidence traceable to its source.']
                ]
            },
            cta: ['Put your loan book under evidence watch',
                  'Free collateral screening with evidence labels — a free account keeps financed locations monitored with alerts.',
                  ['green-finance.html', 'Open Green Finance verification']]
        },

        insurance: {
            tab: 'Insurance',
            badge: 'For insurance & risk',
            title: 'Historical hazard evidence for insured assets',
            sub: 'Build a documented hazard and exposure profile for any insured location: ' +
                 'what happened, what is exposed, what the evidence says — and what it does ' +
                 'not say.',
            actions: [
                ['intelligence.html', 'btn btn-primary', 'Profile a location'],
                ['contact.html', 'btn btn-outline', 'Discuss a pilot']
            ],
            hub: {
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
            cards: [
                ['📜 Historical hazard profile', 'Documented events and past conditions from authoritative archives — satellite records and long-term weather history — labelled HISTORICAL, never blended with projections.'],
                ['🏙️ Exposure intelligence', 'Population, buildings, critical facilities and sector context around the insured asset, from real mapped data with completeness caveats.'],
                ['🧭 Uncertainty, stated', 'Claim status on every figure: OBSERVED / DOCUMENTED / REPORTED / MODELLED / INFERRED / UNKNOWN. Unknown is a first-class answer.'],
                ['🛡️ Resilience evidence', 'Solutions intelligence connects the hazard evidence to feasible resilience measures — with limitations and sources.']
            ],
            disclaimer: 'Talaix provides risk intelligence and evidence. It does not price insurance, and it does not replace actuarial underwriting or any regulated insurance decision.',
            cta: ['Keep your book under evidence watch',
                  'Free analysis with evidence labels — a free account keeps insured locations monitored with alerts.',
                  ['insurance.html', 'Open the insurance risk tool']]
        },

        investors: {
            tab: 'Investors',
            badge: 'For investors & asset managers',
            title: 'Assess climate exposure before committing capital',
            sub: 'Multi-hazard screening, historical event evidence, exposure profiles and ' +
                 'scenario context for assets and regions — every figure traceable to a source, ' +
                 'with uncertainty stated instead of hidden.',
            actions: [
                ['intelligence.html', 'btn btn-primary', 'Screen a location'],
                ['contact.html', 'btn btn-outline', 'Request a portfolio pilot']
            ],
            hub: {
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
            cards: [
                ['📍 Asset & location risk', 'Per-location screening across wildfire, flood, drought, heat, wind, coastal exposure and tropical cyclones — from real datasets, each compared against local historical norms.'],
                ['📚 Historical evidence', 'What actually happened at or near the asset: documented events with sources, kept structurally separate from modelled interpretation.'],
                ['🏙️ Exposure', 'Population, built-up area, critical facilities and sector context counted from real mapped data — with completeness caveats.'],
                ['🔍 Honest uncertainty', 'Screening indicators are labelled as such; monetary exposure is reported as not-quantified unless a documented valuation basis exists. No fabricated figures, ever.'],
                ['🏭 Sector Exposure Screening', 'Screen any asset against agriculture, real estate, tourism, energy, logistics, mining and forestry sensitivity profiles — with physical trajectory and official crime statistics where openly available. <a class="text-link" href="intelligence.html#sector">Open Sector Exposure →</a>']
            ],
            disclaimer: 'Talaix provides climate-evidence intelligence. It does not provide financial, investment or legal advice, and nothing here is a recommendation to buy or sell any asset.',
            cta: ['Put your assets under evidence watch',
                  'The first screening needs no account. A free account keeps every asset saved, monitored and alerted.',
                  ['green-finance.html', 'Verify an asset first']]
        },

        'real-estate': {
            tab: 'Real estate',
            badge: 'For real estate',
            title: 'Multi-hazard exposure before you evaluate',
            sub: 'Wildfire, flood, drought, heat, wind, coastal exposure and tropical cyclones for any property ' +
                 'location — with historical evidence, population context and resilience ' +
                 'options, from real data.',
            actions: [
                ['intelligence.html', 'btn btn-primary', 'Assess a property location'],
                ['map.html', 'btn btn-outline', 'Open the map']
            ],
            hub: {
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
            cards: [
                ['🏠 Location screening', 'Per-location screening across all eight hazards — one place, one evidence base, one consistent answer format.'],
                ['📚 What happened there', 'Historical events near the property from authoritative datasets — labelled, sourced, and separated from models.'],
                ['🏙️ Context', 'Population, settlements and critical facilities around the location, counted from real mapped data.'],
                ['🌱 What can be done', 'Solutions matched to the exact place — with limitations stated, and potential funding programmes where they exist.']
            ],
            cta: ['Keep every property under watch',
                  'Free analysis — a free account saves each property and monitors it with alerts.',
                  ['insurance.html', 'Profile a property first']]
        },

        consulting: {
            tab: 'Consultants & auditors',
            badge: 'For climate & ESG consultants',
            title: 'Documented climate-risk evidence, in minutes',
            sub: 'Assembling defensible climate evidence for client assessments takes days of ' +
                 'source hunting. Talaix brings Earth observation, official open data and ' +
                 'historical events into one evidence-labelled analysis — with provenance your ' +
                 'clients can audit.',
            actions: [
                ['intelligence.html', 'btn btn-primary', 'Start an analysis'],
                ['contact.html', 'btn btn-outline', 'Talk to us']
            ],
            hub: {
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
            },
            cards: [
                ['🧾 Audit-grade evidence', 'Every result carries source, dataset, date, method, resolution, confidence and limitations — the claim status (OBSERVED / DOCUMENTED / REPORTED / MODELLED / INFERRED / UNKNOWN) is part of the output, not a footnote.'],
                ['🌍 Seven hazards, one workflow', 'Wildfire, flood, drought, extreme heat, extreme wind and coastal exposure from one place — no per-hazard tool switching.'],
                ['🗺️ GIS-native', 'GeoJSON grids, per-layer provenance, a documented API, and a QGIS plugin (in early access) bring the analysis into your existing geospatial workflow.'],
                ['📄 Client-ready outputs', 'PDF reports with content-hashed IDs and engine versions; the same bytes are re-verifiable. Solutions and funding intelligence connect evidence to next steps.']
            ],
            extra: {
                tag: 'How consultants use it',
                title: 'From client site to documented answer',
                steps: [
                    ['1', 'Analyze', 'Run the client\'s location — free, no account.'],
                    ['2', 'Save & monitor', 'Keep the analysis; get alerted when conditions change.'],
                    ['3', 'Report', 'Generate the evidence-labelled report for the deliverable.'],
                    ['4', 'Scale', 'Professional/business tiers: many locations, API, team access.']
                ]
            },
            cta: ['Keep client sites under continuous evidence',
                  'Free analysis on real data — a free account keeps client sites saved, monitored and reported.',
                  ['sustainability.html', 'Build an evidence report first']]
        },

        government: {
            tab: 'Government',
            badge: 'For government & municipalities',
            title: 'Understand risk across your territory',
            sub: 'Wildfire, flood, drought, heat, wind and coastal risk across your territory — ' +
                 'with the people, infrastructure and economic activity in their path, the ' +
                 'resilience options that fit, the funding programmes that may apply, and ' +
                 'monitoring that keeps watch for you. Every figure traceable to an official source.',
            actions: [
                ['intelligence.html', 'btn btn-primary', 'Analyze your territory — free'],
                ['contact.html', 'btn btn-outline', 'Contact the public-sector team']
            ],
            hub: {
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
            extra: {
                tag: 'The journey',
                title: 'From hazard to funded, monitored action',
                subtitle: 'One evidence chain, built for public decisions.',
                cards: [
                    ['1 · Territorial risk', 'Run your municipality or region: eight risks computed from real datasets — wildfire, flood, drought, heat, wind, coastal exposure, tropical cyclones and earthquakes, each compared against local history. Screening levels, honestly labelled. <a class="text-link" href="intelligence.html">Analyze your territory →</a>'],
                    ['2 · Who and what is exposed', 'Population and settlements, hospitals, schools, fire stations, transport, energy and water — counted from real mapped data with completeness caveats stated, never estimated silently. <a class="text-link" href="map.html">See it on the map →</a>'],
                    ['3 · Economic exposure', 'Which sectors and assets sit in exposed areas — structured exposure profiles for budget and planning conversations. Where no documented valuation basis exists, we say so instead of inventing figures. <a class="text-link" href="intelligence.html?mode=economy">Explore exposure →</a>'],
                    ['4 · Resilience solutions', 'Site-fitted options — nature-based, engineering, monitoring — each with limitations, maturity and maintenance stated. No solution is presented as guaranteed prevention. <a class="text-link" href="solutions.html">Match solutions →</a>'],
                    ['5 · Funding programmes', 'Which public programmes (EU and beyond) may fit your project — real programmes with official sources. Eligibility always requires verification; we never promise funding. <a class="text-link" href="solutions.html?mode=funding">Find funding →</a>'],
                    ['6 · Continuous monitoring', 'Your territory watched around the clock. When conditions cross a threshold you chose, a concise alert reaches your duty officers by SMS or email — without anyone opening a website. <a class="text-link" href="account.html#sms">Enable alerts →</a>']
                ],
                roles: [
                    ['🏙️', 'Municipal resilience officers', 'Territory risk, exposure and monitoring for the places you are responsible for — with the evidence to defend decisions.'],
                    ['🚒', 'Civil protection', 'Current conditions, historical event intelligence and alerts that reach the right people on meaningful change.'],
                    ['🏗️', 'Urban planning & infrastructure', 'Hazard-aware siting context and resilience prioritization for long-lived public assets.'],
                    ['🧾', 'Environmental & funding officers', 'Provenance-carrying reports for plans, and the funding programmes that may apply to resilience projects.']
                ]
            },
            cta: ['Put your territory under continuous watch',
                  'Free analysis on real data — a free account keeps watched places monitored with email alerts.',
                  ['forensics.html', 'Open the forensic tool first']]
        }
    };

    var SECTOR_ORDER = ['banks', 'government', 'insurance', 'investors', 'real-estate', 'consulting'];

    /* ---------------- interactive hub (ported from audience.js) -------- */

    function renderHub(cfg) {
        var hub = el('audienceHub');
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
    }

    function wireHub(sectorId) {
        el('audienceAnalyzeForm').addEventListener('submit', function (e) {
            e.preventDefault();
            var q = el('audienceAnalyzeInput').value.trim();
            if (!q) return;
            if (window.HS && HS.track) HS.track('audience_analyze_submitted', { page: 'industries-' + sectorId });
            location.href = 'intelligence.html?location=' + encodeURIComponent(q);
        });
        el('audienceRegisterBtn').addEventListener('click', function () {
            if (window.HS && HS.track) HS.track('cta_clicked', { feature: 'audience_register_industries-' + sectorId });
        });
    }

    function loadSignals() {
        var mount = el('audienceSignals');
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

    /* ---------------- sector body rendering ---------------------------- */

    function cardsHtml(cards) {
        return '<div class="content-grid">' + cards.map(function (c) {
            return '<div class="content-card"><h3>' + esc(c[0]) + '</h3><p>' + c[1] + '</p></div>';
        }).join('') + '</div>';
    }

    function extraHtml(extra) {
        if (!extra) return '';
        var html = '<section class="section section-dark"><div class="container">' +
            '<div class="section-header"><span class="section-tag">' + esc(extra.tag) + '</span>' +
            '<h2 class="section-title">' + esc(extra.title) + '</h2>' +
            (extra.subtitle ? '<p class="section-subtitle">' + esc(extra.subtitle) + '</p>' : '') +
            '</div>';
        if (extra.cards) html += cardsHtml(extra.cards);
        if (extra.steps) {
            html += '<div class="problem-grid">' + extra.steps.map(function (s) {
                return '<div class="problem-card"><div class="problem-icon">' + esc(s[0]) + '</div>' +
                    '<h3>' + esc(s[1]) + '</h3><p>' + esc(s[2]) + '</p></div>';
            }).join('') + '</div>';
        }
        if (extra.roles) {
            html += '<div class="problem-grid">' + extra.roles.map(function (r) {
                return '<div class="problem-card"><div class="problem-icon">' + r[0] + '</div>' +
                    '<h3>' + esc(r[1]) + '</h3><p>' + esc(r[2]) + '</p></div>';
            }).join('') + '</div>';
        }
        return html + '</div></section>';
    }

    function accessTableHtml() {
        return '<section class="content-section"><div class="container">' +
            '<div class="section-header"><span class="section-tag">Access</span>' +
            '<h2 class="section-title">What your municipality gets</h2></div>' +
            '<div class="table-scroll"><table class="data-table"><thead>' +
            '<tr><th></th><th>Free (no account)</th><th>Free account</th><th>Organization</th></tr>' +
            '</thead><tbody>' +
            '<tr><th>Territory analysis, eight hazards</th><td>✓</td><td>✓</td><td>✓</td></tr>' +
            '<tr><th>Maps, historical events, exposure, solutions, funding, reports</th><td>✓</td><td>✓</td><td>✓</td></tr>' +
            '<tr><th>Saved territories &amp; analysis history</th><td>—</td><td>✓</td><td>✓</td></tr>' +
            '<tr><th>Monitoring rules &amp; SMS/email alerts</th><td>—</td><td>✓ (2 places)</td><td>✓ many places</td></tr>' +
            '<tr><th>Multiple recipients &amp; team access</th><td>—</td><td>—</td><td>✓</td></tr>' +
            '<tr><th>API &amp; webhooks into your systems</th><td>—</td><td>—</td><td>✓</td></tr>' +
            '</tbody></table></div>' +
            '<p class="muted small" style="margin-top:10px;">Registration is free. Organization ' +
            'arrangements for municipalities and public bodies are set up with us directly — ' +
            '<a href="contact.html">contact us</a>.</p>' +
            '</div></section>' +
            '<section class="section" style="background:var(--light-2);"><div class="container">' +
            '<div class="section-header"><span class="section-tag">Why you can defend it</span>' +
            '<h2 class="section-title">Evidence you can show a council</h2>' +
            '<p class="section-subtitle">Every figure carries its source, dataset, date, method ' +
            'and limitations. Observed is never mixed with modelled or projected. "Unknown" is ' +
            'a first-class answer. The public data-source registry is open.</p></div>' +
            '<p style="text-align:center;"><a class="btn btn-outline-dark" href="/sources">Open the data-source registry</a></p>' +
            '</div></section>';
    }

    function ctaHtml(cta) {
        return '<section class="cta-section"><div class="container">' +
            '<h2>' + esc(cta[0]) + '</h2><p>' + esc(cta[1]) + '</p>' +
            '<div class="cta-actions">' +
            '<a href="account.html" class="btn btn-light guest-only">Create a free account</a>' +
            '<a href="account.html" class="btn btn-light user-only" style="display:none">Open your account</a>' +
            '<a href="' + cta[2][0] + '" class="btn btn-outline-light">' + esc(cta[2][1]) + '</a>' +
            '</div></div></section>';
    }

    /* ---------------- sector switching --------------------------------- */

    function renderSector(id) {
        var s = SECTORS[id];
        el('sectorBadge').textContent = s.badge;
        el('sectorTitle').innerHTML = esc(s.title);
        el('sectorSub').textContent = s.sub;
        el('sectorActions').innerHTML = s.actions.map(function (a) {
            return '<a href="' + a[0] + '" class="' + a[1] + '">' + esc(a[2]) + '</a>';
        }).join('');
        Array.prototype.forEach.call(el('sectorTabs').children, function (btn) {
            var active = btn.getAttribute('data-sector') === id;
            btn.className = active ? 'btn btn-primary' : 'btn btn-outline';
        });
        renderHub(s.hub);
        wireHub(id);
        loadSignals();
        if (window.HSConvert) HSConvert.evaluate('audienceConvert');

        var body = '<section class="content-section"><div class="container">' +
            (s.cards ? cardsHtml(s.cards) : '') +
            (s.disclaimer ? '<div class="disclaimer-box" style="margin-top:18px;">' + esc(s.disclaimer) + '</div>' : '') +
            '</div></section>';
        if (id === 'government') body += extraHtml(s.extra) + accessTableHtml();
        else body += extraHtml(s.extra);
        body += ctaHtml(s.cta);
        el('sectorBody').innerHTML = body;
        if (window.HS && HS.track) HS.track('industry_sector_viewed', { sector: id });
    }

    function currentSector() {
        var q = new URLSearchParams(location.search).get('sector');
        return SECTORS[q] ? q : 'banks';
    }

    function init() {
        el('sectorTabs').innerHTML = SECTOR_ORDER.map(function (id) {
            return '<button type="button" class="btn btn-outline" data-sector="' + id + '">' +
                esc(SECTORS[id].tab) + '</button>';
        }).join('');
        Array.prototype.forEach.call(el('sectorTabs').children, function (btn) {
            btn.addEventListener('click', function () {
                var id = btn.getAttribute('data-sector');
                history.replaceState(null, '', 'industries.html?sector=' + id);
                renderSector(id);
            });
        });
        renderSector(currentSector());
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
