// Node harness: exercises website/js/convert.js with stubbed browser
// globals. Invoked from tests/test_conversion_engine.py.
const fs = require('fs');
const path = require('path');

const store = {};
global.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; }
};
const tracked = [];
const shown = [];
global.HS = { track: (e, p) => tracked.push([e, p]) };
global.window = { HS: global.HS };
global.navigator = { doNotTrack: '0' };
global.location = { pathname: '/intelligence.html', hostname: 'localhost' };

const fakeMount = {
    querySelector: () => null,
    appendChild: (el) => { /* capture via textContent of span */ },
};
global.document = {
    getElementById: () => fakeMount,
    createElement: (tag) => {
        const el = { children: [], style: {}, className: '', textContent: '',
            addEventListener: () => {}, appendChild: (c) => el.children.push(c),
            remove: () => {} };
        return el;
    },
};

// convert.js probes the session before showing any strip (conversion prompts
// are guest-only). Stub a guest session: /v2/account is not OK.
global.fetch = () => Promise.resolve({ ok: false });

const src = fs.readFileSync(
    path.join(__dirname, '..', 'website', 'js', 'convert.js'), 'utf8');
eval(src);

const HC = global.window.HSConvert;
const out = { thresholds: HC._config.thresholds };

// Observe evaluate() by watching track calls: show() fires cta_viewed.
function tierShown() {
    const v = tracked.filter((t) => t[0] === 'cta_viewed')
        .map((t) => t[1].feature);
    return v.length ? v[v.length - 1] : null;
}

// evaluate()/show() resolve the (stubbed) session probe asynchronously;
// flush pending microtasks before reading what was shown.
const flush = () => new Promise((r) => setImmediate(r));

(async () => {
    HC.evaluate('statusArea');
    await flush();
    out.tier_at_zero = tierShown();
    HC.trackAction('location_analyzed');
    HC.evaluate('statusArea');
    await flush();
    out.tier_after_1 = tierShown();   // below account threshold (2) → null
    HC.trackAction('report_generated');
    HC.evaluate('statusArea');
    await flush();
    out.tier_after_2 = tierShown();   // 2 high-value → tier_account
    HC.trackAction('solution_viewed');
    HC.evaluate('statusArea');
    await flush();
    out.tier_after_3 = tierShown();   // 3 → tier_monitor
    HC.trackAction('funding_viewed');
    HC.trackAction('location_analyzed');
    HC.evaluate('statusArea');
    await flush();
    out.tier_after_5 = tierShown();   // 5 → tier_professional
    HC.trackAction('location_analyzed');
    HC.trackAction('report_generated');
    HC.trackAction('solution_viewed');
    HC.evaluate('statusArea');
    await flush();
    out.tier_after_8 = tierShown();   // 8 → tier_business
    out.events = [...new Set(tracked.map((t) => t[0]))];
    console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
