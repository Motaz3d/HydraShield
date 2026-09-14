/* Talaix — plain-language glossary (no build step).
 *
 * Single source of truth for translating environmental / compliance jargon
 * into plain business English. Two behaviours, both automatic:
 *
 *   1. Tooltips — every `<span class="term" data-term="csrd">CSRD</span>`
 *      (or an unmatched all-caps acronym that matches a glossary key) gets a
 *      hover/focus tooltip with the plain explanation.
 *   2. Glossary page — if a page contains `<div id="glossaryRoot"></div>`,
 *      the full A–Z is rendered there.
 *
 * Auto-loaded on every page by chrome.js.
 */
(function () {
    'use strict';

    var GLOSSARY = {
        csrd:        { term: 'CSRD', full: 'Corporate Sustainability Reporting Directive', group: 'Regulation', plain: 'The EU law that makes companies disclose how climate and sustainability issues affect their business — and how their business affects the planet.' },
        esrs:        { term: 'ESRS', full: 'European Sustainability Reporting Standards', group: 'Regulation', plain: 'The detailed rulebook companies must follow when they file their sustainability report under the CSRD.' },
        'esrs-e1':   { term: 'ESRS E1', full: 'Climate change standard', group: 'Regulation', plain: 'The climate section of the ESRS rulebook: what you must disclose about climate risks, including the physical risks to your own sites and assets.' },
        taxonomy:    { term: 'EU Taxonomy', full: 'EU classification of sustainable activities', group: 'Regulation', plain: 'The EU’s official list of which business activities count as environmentally sustainable — the checklist behind most green-finance claims.' },
        dnsh:        { term: 'DNSH', full: 'Do No Significant Harm', group: 'Regulation', plain: 'A test that an activity does not seriously harm climate, water, ecosystems, pollution or the circular economy. Part of every EU Taxonomy check.' },
        eudr:        { term: 'EUDR', full: 'EU Deforestation Regulation', group: 'Regulation', plain: 'The EU law requiring importers and exporters of certain goods (coffee, cocoa, timber, rubber, soya, cattle, palm oil) to prove their supply chain did not cause deforestation.' },
        csddd:       { term: 'CSDDD', full: 'Corporate Sustainability Due Diligence Directive', group: 'Regulation', plain: 'The EU law requiring large companies to identify and address human-rights and environmental harm across their whole value chain.' },
        'pillar-3':  { term: 'EBA Pillar 3', full: 'Banking disclosure rules', group: 'Regulation', plain: 'The public disclosures banks must publish about their risks — now including climate and environmental risks on their loan books.' },
        'solvency-ii': { term: 'Solvency II', full: 'EU insurance rulebook', group: 'Regulation', plain: 'The EU rulebook for insurers and reinsurers, requiring them to understand and hold capital for the risks they underwrite — including natural-catastrophe risk.' },
        eiopa:       { term: 'EIOPA', full: 'European Insurance and Occupational Pensions Authority', group: 'Regulation', plain: 'The EU authority that supervises insurance and pension providers.' },
        icma:        { term: 'ICMA', full: 'International Capital Market Association', group: 'Regulation', plain: 'The body that publishes the voluntary Green Bond Principles — guidelines for issuing credible green bonds.' },
        'ifrs-s2':   { term: 'IFRS S2', full: 'Climate-related disclosures standard', group: 'Regulation', plain: 'The global standard for disclosing climate-related risks and opportunities, increasingly adopted into national law.' },
        tcfd:        { term: 'TCFD', full: 'Task Force on Climate-related Financial Disclosures', group: 'Regulation', plain: 'The earlier climate-disclosure framework whose recommendations IFRS S2 has now absorbed and replaced.' },
        issb:        { term: 'ISSB', full: 'International Sustainability Standards Board', group: 'Regulation', plain: 'The global body that publishes the IFRS sustainability-disclosure standards, including IFRS S2.' },
        'sb-261':    { term: 'SB 261', full: 'California climate-risk law', group: 'Regulation', plain: 'A California law requiring large companies doing business there to publish climate-related financial-risk reports.' },
        xbrl:        { term: 'XBRL', full: 'eXtensible Business Reporting Language', group: 'Format', plain: 'A machine-readable format for financial and sustainability data, so regulators’ software can read your report directly instead of a person re-typing it.' },
        ixbrl:       { term: 'iXBRL', full: 'Inline XBRL', group: 'Format', plain: 'XBRL embedded in a normal web page, so the same document is readable by both people and software.' },
        'double-materiality': { term: 'Double materiality', full: 'Two-way impact test', group: 'Concept', plain: 'The CSRD’s two-way test: how climate affects your company (risks) AND how your company affects climate (impacts). You report on whichever is significant.' },
        'physical-risk': { term: 'Physical risk', full: 'Climate/weather risk', group: 'Concept', plain: 'The risk of damage from weather and climate events — floods, heatwaves, storms, wildfires — hitting your buildings, equipment, people or supply routes.' },
        'transition-risk': { term: 'Transition risk', full: 'Low-carbon shift risk', group: 'Concept', plain: 'The risk of financial loss from moving to a lower-carbon economy — new policies, shifting markets, technology changes or reputation damage.' },
        materiality: { term: 'Materiality', full: 'Significance test', group: 'Concept', plain: 'Whether an issue is significant enough that leaving it out would mislead a reader. The test that decides what you must disclose.' },
        'scenario-analysis': { term: 'Scenario analysis', full: 'Climate pathway testing', group: 'Concept', plain: 'Testing how your business would fare under different possible climate futures (for example, a +2°C versus a +4°C world).' },
        'per-peril': { term: 'Per-peril', full: 'One hazard at a time', group: 'Concept', plain: 'Analysing risk one hazard at a time — flood separately from wildfire — rather than as a single blurred number.' },
        actuarial:   { term: 'Actuarial', full: 'Risk-pricing statistics', group: 'Concept', plain: 'The statistical methods insurers use to estimate risk, price policies and set aside capital.' },
        spo:         { term: 'Second Party Opinion', full: 'Independent green-bond review', group: 'Concept', plain: 'An independent expert’s assessment of a green bond’s environmental credibility. Talaix provides evidence, not this opinion.' },
        esma:        { term: 'ESMA', full: 'European Securities and Markets Authority', group: 'Regulation', plain: 'The EU authority that oversees securities markets and registers the external reviewers of green bonds.' },
        hazard:      { term: 'Hazard', full: 'Natural event', group: 'Concept', plain: 'A natural event that can cause harm — a flood, heatwave, storm or wildfire.' },
        exposure:    { term: 'Exposure', full: 'What could be hit', group: 'Concept', plain: 'What you have that could be affected — buildings, equipment, people, supply routes — and where they are.' },
        vulnerability: { term: 'Vulnerability', full: 'How badly you’d be affected', group: 'Concept', plain: 'How badly your assets would be affected if a hazard strikes — a warehouse and a data centre react very differently to a flood.' },
        acute:       { term: 'Acute hazard', full: 'Short, sharp event', group: 'Concept', plain: 'A short, sharp event — a flood, storm or heatwave.' },
        chronic:     { term: 'Chronic hazard', full: 'Slow, long-term shift', group: 'Concept', plain: 'A slow, long-term shift — rising temperatures, sea-level rise, or a gradual drying trend.' },
        'earth-observation': { term: 'Earth observation', full: 'Satellite measurement', group: 'Data', plain: 'Satellites and sensors measuring the Earth from space — the raw imagery and data behind Talaix’s evidence.' },
        geolocation: { term: 'Geolocation', full: 'Exact plot coordinates', group: 'Data', plain: 'The precise latitude/longitude coordinates of a plot of land, site or asset — the core data point behind every location check.' },
        'multi-hazard': { term: 'Multi-hazard', full: 'All hazards together', group: 'Concept', plain: 'Looking at many hazards together (fire, flood, heat, drought, wind, coastal, cyclone, earthquake…) instead of one at a time.' },
        'evidence-status': { term: 'Evidence status', full: 'How a figure was produced', group: 'Concept', plain: 'A label on every figure saying how it was produced: directly observed, documented, reported, modelled, inferred — or unknown.' },
        wildfire:    { term: 'Wildfire', full: 'Wildland fire', group: 'Hazard', plain: 'Uncontrolled fire in vegetation — forest, scrub or grassland — driven by fuel, wind, heat and dryness.' },
        flood:       { term: 'Flood', full: 'Inundation', group: 'Hazard', plain: 'Water covering normally dry land, from rivers, heavy rain, coastal surge or flash events.' },
        drought:     { term: 'Drought', full: 'Water deficit', group: 'Hazard', plain: 'A prolonged period of below-normal rainfall that stresses water supply, crops and infrastructure.' },
        'extreme-heat': { term: 'Extreme heat', full: 'Heatwave', group: 'Hazard', plain: 'Unusually high temperatures that threaten health, productivity, equipment and energy systems.' },
        wind:        { term: 'Wind', full: 'Windstorm', group: 'Hazard', plain: 'Damaging winds from storms or downbursts that can strike structures and power lines.' },
        coastal:     { term: 'Coastal', full: 'Coastal hazard', group: 'Hazard', plain: 'Risks at the shoreline — storm surge, coastal erosion and sea-level rise.' },
        cyclone:     { term: 'Cyclone', full: 'Tropical cyclone', group: 'Hazard', plain: 'An intense rotating storm (also called hurricane or typhoon) bringing extreme wind, rain and surge.' },
        earthquake:  { term: 'Earthquake', full: 'Seismic event', group: 'Hazard', plain: 'Ground shaking from the sudden release of energy along a fault line.' },
        volcanic:    { term: 'Volcanic', full: 'Volcanic hazard', group: 'Hazard', plain: 'Risks from eruptions — ash, lava, pyroclastic flows and associated gases.' },
        dust:        { term: 'Dust', full: 'Dust storm', group: 'Hazard', plain: 'Airborne mineral dust that can affect air quality, solar output and transport.' }
    };

    // Terms we auto-enhance anywhere in body text: pure acronyms plus a short,
    // non-overlapping list of technical phrases. Matched case-insensitively on
    // word boundaries; longest patterns first so phrases win over fragments.
    var AUTO_ACRONYMS = [
        'CSRD', 'ESRS', 'DNSH', 'EUDR', 'CSDDD', 'XBRL', 'iXBRL', 'EIOPA',
        'ICMA', 'TCFD', 'ISSB', 'ESMA'
    ];
    var AUTO_PHRASES = [
        { text: 'double materiality', key: 'double-materiality' },
        { text: 'second party opinion', key: 'spo' },
        { text: 'scenario analysis', key: 'scenario-analysis' },
        { text: 'transition risk', key: 'transition-risk' },
        { text: 'physical risk', key: 'physical-risk' },
        { text: 'earth observation', key: 'earth-observation' },
        { text: 'multi-hazard', key: 'multi-hazard' },
        { text: 'per-peril', key: 'per-peril' },
        { text: 'actuarial', key: 'actuarial' },
        { text: 'geolocation', key: 'geolocation' }
    ];

    var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1, A: 1, TEXTAREA: 1, INPUT: 1, SELECT: 1, BUTTON: 1, OPTION: 1 };

    function escapeRegex(s) {
        return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
    function normalizeTerm(s) {
        return s.toLowerCase().replace(/[\s-]+/g, '-');
    }
    function phrasePattern(text) {
        return text.split(/[\s-]+/).map(escapeRegex).join('[\\s-]+');
    }

    var termKeyMap = {};
    AUTO_ACRONYMS.forEach(function (a) { termKeyMap[normalizeTerm(a)] = normalizeTerm(a); });
    AUTO_PHRASES.forEach(function (p) { termKeyMap[normalizeTerm(p.text)] = p.key; });

    var termPatterns = AUTO_ACRONYMS.map(escapeRegex).concat(AUTO_PHRASES.map(function (p) { return phrasePattern(p.text); }));
    termPatterns.sort(function (a, b) { return b.length - a.length; });
    var autoRegex = new RegExp('\\b(' + termPatterns.join('|') + ')\\b', 'gi');

    function keyForMatch(text) {
        return termKeyMap[normalizeTerm(text)] || null;
    }

    function tipHtml(key) {
        var g = GLOSSARY[key];
        if (!g) return '';
        return '<span class="tt-term">' + g.term + '</span>' +
               '<span class="tt-full">' + g.full + '</span>' +
               g.plain +
               '<span class="tt-group">' + g.group + '</span>';
    }

    function buildTip() {
        var el = document.createElement('div');
        el.className = 'term-tip';
        el.setAttribute('role', 'tooltip');
        el.setAttribute('aria-hidden', 'true');
        el.style.visibility = 'hidden';
        document.body.appendChild(el);
        return el;
    }

    function positionTip(tip, anchor) {
        var r = anchor.getBoundingClientRect();
        var w = tip.offsetWidth;
        var left = r.left + window.scrollX;
        var top = r.bottom + window.scrollY + 8;
        if (left + w > window.innerWidth + window.scrollX - 12) {
            left = window.innerWidth + window.scrollX - w - 12;
        }
        if (left < window.scrollX + 12) left = window.scrollX + 12;
        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
    }

    function enhance() {
        var tip = buildTip();
        var hideTimer = null;

        function show(anchor, key) {
            tip.innerHTML = tipHtml(key);
            if (!tip.innerHTML) return;
            tip.style.visibility = 'visible';
            positionTip(tip, anchor);
        }
        function scheduleHide() {
            hideTimer = setTimeout(function () { tip.style.visibility = 'hidden'; }, 120);
        }
        function cancelHide() {
            if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        }

        // 1. Explicitly marked terms.
        var terms = document.querySelectorAll('.term[data-term]');
        Array.prototype.forEach.call(terms, function (el) {
            var key = el.getAttribute('data-term');
            if (!GLOSSARY[key]) return;
            el.setAttribute('tabindex', '0');
            el.addEventListener('mouseenter', function () { cancelHide(); show(el, key); });
            el.addEventListener('mouseleave', scheduleHide);
            el.addEventListener('focus', function () { cancelHide(); show(el, key); });
            el.addEventListener('blur', scheduleHide);
        });

        tip.addEventListener('mouseenter', cancelHide);
        tip.addEventListener('mouseleave', scheduleHide);

        // 2. Auto-enhance unmatched acronyms and technical phrases in body text.
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
                var p = node.parentElement;
                if (!p) return NodeFilter.FILTER_REJECT;
                if (SKIP_TAGS[p.tagName]) return NodeFilter.FILTER_REJECT;
                if (p.closest && (p.closest('.term') || p.closest('.term-tip') || p.closest('script'))) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        var textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);

        textNodes.forEach(function (node) {
            var text = node.nodeValue;
            autoRegex.lastIndex = 0;
            var match, last = 0, frag = document.createDocumentFragment();
            while ((match = autoRegex.exec(text)) !== null) {
                if (match.index > last) frag.appendChild(document.createTextNode(text.slice(last, match.index)));
                var key = keyForMatch(match[1]);
                if (key) {
                    var span = document.createElement('span');
                    span.className = 'term';
                    span.setAttribute('data-term', key);
                    span.setAttribute('tabindex', '0');
                    span.textContent = match[1];
                    span.addEventListener('mouseenter', function (ev) { cancelHide(); show(ev.currentTarget, ev.currentTarget.getAttribute('data-term')); });
                    span.addEventListener('mouseleave', scheduleHide);
                    span.addEventListener('focus', function (ev) { cancelHide(); show(ev.currentTarget, ev.currentTarget.getAttribute('data-term')); });
                    span.addEventListener('blur', scheduleHide);
                    frag.appendChild(span);
                } else {
                    frag.appendChild(document.createTextNode(match[1]));
                }
                last = match.index + match[1].length;
            }
            if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
            if (frag.childNodes.length) node.parentNode.replaceChild(frag, node);
        });
    }

    function renderGlossaryPage() {
        var root = document.getElementById('glossaryRoot');
        if (!root) return;
        var keys = Object.keys(GLOSSARY).sort(function (a, b) {
            return GLOSSARY[a].term.localeCompare(GLOSSARY[b].term);
        });
        var groups = {};
        keys.forEach(function (k) {
            var g = GLOSSARY[k];
            var letter = g.term.charAt(0).toUpperCase();
            (groups[letter] = groups[letter] || []).push(g);
        });
        var html = '<nav class="glossary-nav" aria-label="Glossary index">';
        Object.keys(groups).sort().forEach(function (letter) {
            html += '<a href="#gl-' + letter + '">' + letter + '</a>';
        });
        html += '</nav>';
        Object.keys(groups).sort().forEach(function (letter) {
            html += '<section class="glossary-letter" id="gl-' + letter + '"><h2>' + letter + '</h2>';
            groups[letter].forEach(function (g) {
                html += '<article class="glossary-entry">' +
                    '<h3>' + g.term + ' <span class="tt-full">' + g.full + '</span></h3>' +
                    '<p>' + g.plain + '</p>' +
                    '<span class="tt-group">' + g.group + '</span></article>';
            });
            html += '</section>';
        });
        root.innerHTML = html;
    }

    function init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () { enhance(); renderGlossaryPage(); });
        } else {
            enhance();
            renderGlossaryPage();
        }
    }

    window.TALAIX_GLOSSARY = GLOSSARY;
    init();
})();
