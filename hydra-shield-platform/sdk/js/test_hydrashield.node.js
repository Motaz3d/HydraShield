/* Offline tests for sdk/js/hydrashield.js — plain Node script, no runner:
 *
 *     node sdk/js/test_hydrashield.node.js
 *
 * Stubs global.fetch with a recorder, asserts URL construction, error
 * semantics, headers, and the non-browser custom-element guard. Exits 0 on
 * success, 1 on the first failure summary.
 */
'use strict';

const assert = require('node:assert');

/* fetch recorder: queue items are plain payloads (200) or
 * { __status: n, body: {...} } for non-2xx responses. */
const calls = [];
let queue = [];
global.fetch = (url, options) => {
    calls.push({ url, options });
    const item = queue.length ? queue.shift() : { ok: true };
    const status = item.__status || 200;
    const body = item.__status ? item.body : item;
    return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        text: () => Promise.resolve(JSON.stringify(body))
    });
};

const HS = require('./hydrashield.js');

const BASE = 'https://hydrashield.earth';
let passed = 0;
let chain = Promise.resolve();

/* Strictly sequential: each test resets the recorder, then runs. */
function test(name, fn) {
    chain = chain.then(() => {
        calls.length = 0;
        queue = [];
        return Promise.resolve()
            .then(fn)
            .then(() => { passed++; console.log('ok - ' + name); })
            .catch((err) => {
                console.error('FAIL - ' + name + ': ' + err.message);
                process.exit(1);
            });
    });
}

const path = (call) => call.url.slice(BASE.length);

/* --- URL construction ------------------------------------------------- */

test('createClient exposes the full method set', () => {
    const c = HS.createClient({});
    ['hazards', 'hazard', 'analyze', 'events', 'event', 'economy',
        'solutions', 'sources', 'health', 'riskGrid', 'riskSnapshot',
        'history', 'reportUrl', 'populationExposure', 'smokeScenario'
    ].forEach((m) => assert.strictEqual(typeof c[m], 'function', m));
});

test('hazards URL', () => HS.createClient({}).hazards()
    .then(() => assert.strictEqual(path(calls[0]), '/api/v2/hazards')));

test('hazard URL', () => HS.createClient({}).hazard('wildfire')
    .then(() => assert.strictEqual(path(calls[0]), '/api/v2/hazards/wildfire')));

test('analyze URL', () => HS.createClient({}).analyze('wildfire', 37.6, -6.5)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/v2/analyze?hazard=wildfire&lat=37.6&lon=-6.5')));

test('events URL with year', () =>
    HS.createClient({}).events('wildfire', 37.6, -6.5, 50, 2024)
        .then(() => assert.strictEqual(path(calls[0]),
            '/api/v2/events?hazard=wildfire&lat=37.6&lon=-6.5&radius_km=50&year=2024')));

test('events URL defaults', () => HS.createClient({}).events('flood', 49.75, 6.64)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/v2/events?hazard=flood&lat=49.75&lon=6.64&radius_km=50')));

test('event URL', () => HS.createClient({}).event('wf-2024-00042')
    .then(() => assert.strictEqual(path(calls[0]), '/api/v2/events/wf-2024-00042')));

test('economy URL', () => HS.createClient({}).economy(49.6, 6.1)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/v2/economy?lat=49.6&lon=6.1&radius_km=5')));

test('solutions URL with hazards', () =>
    HS.createClient({}).solutions(49.6, 6.1, ['wildfire', 'drought'])
        .then(() => assert.strictEqual(path(calls[0]),
            '/api/v2/solutions?lat=49.6&lon=6.1&hazards=wildfire%2Cdrought')));

test('solutions URL without hazards', () => HS.createClient({}).solutions(49.6, 6.1)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/v2/solutions?lat=49.6&lon=6.1')));

test('sources URL', () => HS.createClient({}).sources()
    .then(() => assert.strictEqual(path(calls[0]), '/api/v2/sources')));

test('health URL', () => HS.createClient({}).health()
    .then(() => assert.strictEqual(path(calls[0]), '/api/health')));

test('riskGrid URL', () => HS.createClient({}).riskGrid(49.9, 5.9, 50.1, 6.1)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/risk-grid?south=49.9&west=5.9&north=50.1&east=6.1&n=6')));

test('riskSnapshot URL', () => HS.createClient({}).riskSnapshot()
    .then(() => assert.strictEqual(path(calls[0]), '/api/risk-snapshot')));

test('history URL', () => HS.createClient({}).history(37.6, -6.5)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/history?lat=37.6&lon=-6.5&days=90')));

test('reportUrl string', () => {
    const c = HS.createClient({});
    assert.strictEqual(c.reportUrl(37.6, -6.5),
        BASE + '/api/report?lat=37.6&lon=-6.5&type=decision&history=1');
    assert.strictEqual(c.reportUrl(37.6, -6.5, 'simple', false),
        BASE + '/api/report?lat=37.6&lon=-6.5&type=simple');
});

test('populationExposure URL', () => HS.createClient({}).populationExposure(37.6, -6.5)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/population-exposure?lat=37.6&lon=-6.5&radius_km=3')));

test('smokeScenario URL', () => HS.createClient({}).smokeScenario(37.6, -6.5)
    .then(() => assert.strictEqual(path(calls[0]),
        '/api/smoke-scenario?lat=37.6&lon=-6.5&hours=24')));

test('custom baseUrl (trailing slash trimmed)', () => {
    const c = HS.createClient({ baseUrl: 'http://localhost:8051/' });
    return c.health().then(() =>
        assert.strictEqual(calls[0].url, 'http://localhost:8051/api/health'));
});

/* --- Error semantics --------------------------------------------------- */

test('{"error"} body on 4xx throws HydraShieldError', () => {
    queue = [{ __status: 404, body: { error: "Unknown hazard 'xyz'.", status: 404 } }];
    return HS.createClient({}).analyze('xyz', 0, 0)
        .then(() => { throw new Error('should have thrown'); })
        .catch((err) => {
            assert.ok(err instanceof HS.HydraShieldError);
            assert.strictEqual(err.status, 404);
            assert.ok(err.message.includes('Unknown hazard'));
        });
});

test('{"error"} body on 5xx throws HydraShieldError', () => {
    queue = [{ __status: 502, body: { error: 'Analysis failed', status: 502 } }];
    return HS.createClient({}).riskSnapshot()
        .then(() => { throw new Error('should have thrown'); })
        .catch((err) => {
            assert.ok(err instanceof HS.HydraShieldError);
            assert.strictEqual(err.status, 502);
        });
});

test('unavailable 503 payload returned as data (never throws)', () => {
    queue = [{
        __status: 503,
        body: { hazard: 'wildfire', status: 'unavailable',
                unavailable_reason: 'upstream source unreachable' }
    }];
    return HS.createClient({}).analyze('wildfire', 37.6, -6.5)
        .then((data) => {
            assert.strictEqual(data.status, 'unavailable');
            assert.ok(data.unavailable_reason);
        });
});

/* --- Headers ----------------------------------------------------------- */

test('X-API-Key header sent when apiKey set', () =>
    HS.createClient({ apiKey: 'hs_test_key' }).hazards()
        .then(() => assert.strictEqual(
            calls[0].options.headers['X-API-Key'], 'hs_test_key')));

test('no X-API-Key header by default', () =>
    HS.createClient({}).hazards()
        .then(() => assert.strictEqual(
            calls[0].options.headers['X-API-Key'], undefined)));

/* --- Non-browser guard --------------------------------------------------- */

test('custom element defined only when customElements exists', () => {
    assert.strictEqual(typeof customElements, 'undefined',
        'test must run outside a browser');
    assert.strictEqual(HS.RiskElement, null,
        'RiskElement must stay unregistered without customElements');
    assert.strictEqual(typeof HS.createClient, 'function',
        'the SDK client still works without a DOM');
});

test('window.HydraShield attached (globalThis under Node)', () => {
    assert.strictEqual(globalThis.HydraShield, HS);
});

/* --- Summary ------------------------------------------------------------ */

chain = chain.then(() => {
    console.log(passed + ' tests passed');
});
