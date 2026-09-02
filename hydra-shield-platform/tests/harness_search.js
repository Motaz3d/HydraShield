// Node harness: exercises website/js/search.js with stubbed browser globals.
// Invoked from tests/test_search_palette.py.
const fs = require('fs');
const path = require('path');

const store = {};
global.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; }
};

// Minimal document/window stubs so search.js can load without touching the DOM.
global.window = {
    HS_NAV_LINKS: [
        { id: 'intelligence', href: 'intelligence.html', label: 'Intelligence' },
        { id: 'map', href: 'map.html', label: 'Map' },
        { id: 'greenfinance', href: 'green-finance.html', label: 'Green Finance' }
    ],
    HS: { lastLocation: () => ({ lat: 45.42, lon: 12.33, name: 'Venice' }) }
};
global.document = {
    addEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({
        className: '',
        classList: { add: () => {}, remove: () => {} },
        setAttribute: () => {},
        getAttribute: () => null,
        addEventListener: () => {},
        appendChild: () => {},
        querySelector: () => null,
        querySelectorAll: () => []
    }),
    body: { appendChild: () => {}, classList: { add: () => {}, remove: () => {} } }
};
global.navigator = {};
global.location = { hostname: 'localhost', href: '/' };

const src = fs.readFileSync(
    path.join(__dirname, '..', 'website', 'js', 'search.js'), 'utf8');
eval(src);

const HS = global.window.HSSearch;
const out = {};

// Synthetic index covering all groups to test filtering and capping.
const entries = [
    { id: 'nav-1', label: 'Intelligence', hint: 'Page', group: 'Navigation', href: 'intelligence.html', keywords: [] },
    { id: 'nav-2', label: 'Map', hint: 'Page', group: 'Navigation', href: 'map.html', keywords: [] },
    { id: 'nav-3', label: 'Green Finance', hint: 'Page', group: 'Navigation', href: 'green-finance.html', keywords: [] },
    { id: 'act-1', label: 'Verify an asset', hint: 'Green Finance', group: 'Actions', href: 'green-finance.html', keywords: ['verify', 'green'] },
    { id: 'act-2', label: 'Map Check', hint: 'Map', group: 'Actions', href: 'mapcheck.html', keywords: ['map', 'satellite'] },
    { id: 'loc-1', label: 'Verify Venice', hint: 'Last analysed', group: 'Location', href: 'green-finance.html?location=Venice', keywords: [] },
    { id: 'gloss-1', label: 'NDVI', hint: 'Index', group: 'Glossary', href: 'academy.html#ndvi', keywords: ['vegetation'] },
    { id: 'brief-1', label: 'Pilot Brief', hint: 'Evidence brief', group: 'Briefs', href: 'briefs.html?id=pilot', keywords: ['pilot'] }
];

// 1. Empty query returns all static groups, preserving order.
out.empty = HS.filterIndex(entries, '');

// 2. Substring filtering across label and keywords.
out.verify = HS.filterIndex(entries, 'verify');
out.map = HS.filterIndex(entries, 'map');

// 3. Unknown query with three fallback actions (map, verify, analyze).
const fallback = HS._buildFallbackItems('Ljubljana');
out.fallback = fallback;
out.no_match = HS.filterIndex(entries.concat(fallback), 'Ljubljana');

// 4. Cap of 7 per group: create 10 Navigation entries.
const manyNav = [];
for (let i = 0; i < 10; i++) {
    manyNav.push({ id: 'nav-x' + i, label: 'Page ' + i, hint: 'Page', group: 'Navigation', href: '#', keywords: [] });
}
out.capped = HS.filterIndex(manyNav, '');

// 5. Location actions built from the stubbed HS.lastLocation().
out.location_actions = HS._buildLocationItems();

// 6. Action list is non-empty and contains expected portals.
const actions = HS._buildActionItems();
out.action_labels = actions.map((a) => a.label);

// 7. Hazard items built from the /api/v2/hazards contract.
out.hazard_items = HS._buildHazardItems({ hazards: [
    { id: 'wildfire', name: 'Wildfire', tagline: 'Fire danger screening' },
    { id: 'flood', name: 'Flood', tagline: 'Flood exposure screening' }
] });

// 8. Source items: candidates/rejected are audit metadata, not capabilities.
out.source_items = HS._buildSourceItems({ sources: [
    { name: 'NASA FIRMS', provider: 'NASA', url: 'https://firms.modaps.eosdis.nasa.gov', status: 'integrated', kind: 'satellite' },
    { name: 'Candidate Feed', provider: 'X', url: 'https://example.com', status: 'candidate' },
    { name: 'Rejected Feed', provider: 'Y', url: 'https://y.example.com', status: 'rejected' }
] });

console.log(JSON.stringify(out));
