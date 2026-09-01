/* Talaix — JavaScript SDK + <hydrashield-risk> web component.
 *
 * UMD-lite: attaches `window.Talaix` in browsers, exports via
 * `module.exports` under Node, and works as a plain <script>. Zero
 * dependencies (fetch-based). The custom element registers only when
 * `customElements` exists (guard for non-browser environments).
 *
 * Contract: docs/API_V2.md. Error semantics mirror the Python SDK:
 * non-2xx responses carrying {"error", "status"} throw TalaixError;
 * honest unavailability ({"status": "unavailable", …}, even on HTTP 503)
 * is returned as data — callers render it, never catch it.
 */
(function (global) {
    'use strict';

    var DEFAULT_BASE_URL = 'https://talaix.com';
    var USER_AGENT = 'hydrashield-js-sdk/0.2.0';

    function TalaixError(status, message) {
        this.name = 'TalaixError';
        this.status = status;
        this.message = message;
        if (Error.captureStackTrace) Error.captureStackTrace(this, TalaixError);
    }
    TalaixError.prototype = Object.create(Error.prototype);
    TalaixError.prototype.constructor = TalaixError;
    TalaixError.prototype.toString = function () {
        return 'TalaixError: HTTP ' + this.status + ': ' + this.message;
    };

    /* Query string: insertion order preserved, values percent-encoded
     * (same encoding as the Python SDK's urlencode for these inputs). */
    function qs(params) {
        var parts = [];
        for (var i = 0; i < params.length; i++) {
            var k = params[i][0], v = params[i][1];
            if (v === null || v === undefined) continue;
            parts.push(k + '=' + encodeURIComponent(String(v)));
        }
        return parts.length ? '?' + parts.join('&') : '';
    }

    function createClient(options) {
        options = options || {};
        var baseUrl = (options.baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, '');
        var apiKey = options.apiKey || null;

        function url(path, params) {
            return baseUrl + path + qs(params || []);
        }

        function get(path, params) {
            var headers = { 'Accept': 'application/json' };
            if (apiKey) headers['X-API-Key'] = apiKey;
            return fetch(url(path, params), { method: 'GET', headers: headers })
                .then(function (resp) {
                    return resp.text().then(function (text) {
                        var body = {};
                        try { body = text ? JSON.parse(text) : {}; } catch (e) { body = {}; }
                        if (!resp.ok) {
                            if (body && typeof body === 'object' && 'error' in body) {
                                throw new TalaixError(resp.status, String(body.error));
                            }
                            /* Honest unavailable/key-required states are data. */
                            return body;
                        }
                        return body;
                    });
                });
        }

        function post(path, payload) {
            var headers = { 'Accept': 'application/json',
                            'Content-Type': 'application/json' };
            if (apiKey) headers['X-API-Key'] = apiKey;
            return fetch(url(path), { method: 'POST', headers: headers,
                                      body: JSON.stringify(payload) })
                .then(function (resp) {
                    return resp.text().then(function (text) {
                        var body = {};
                        try { body = text ? JSON.parse(text) : {}; } catch (e) { body = {}; }
                        if (!resp.ok) {
                            if (body && typeof body === 'object' && 'error' in body) {
                                throw new TalaixError(resp.status, String(body.error));
                            }
                            return body;
                        }
                        return body;
                    });
                });
        }

        /* TX Job Object polling: job → (succeeded → result) | failed |
         * timeout. Never resolves to a fabricated result. */
        function txWaitPoll(jobId, deadline, intervalMs, onPoll) {
            var statusUrl = '/api/tx/jobs/' + encodeURIComponent(jobId);
            return get(statusUrl).then(function (status) {
                if (onPoll) onPoll(status);
                if (status.status === 'succeeded') {
                    return get(statusUrl + '/result');
                }
                if (status.status === 'failed') {
                    throw new TalaixError(409, 'Job ' + jobId + ' failed: ' +
                        status.error);
                }
                if (Date.now() >= deadline) {
                    throw new TalaixError(408, 'Job ' + jobId +
                        ' not finished in time (last status: ' +
                        status.status + ')');
                }
                return new Promise(function (resolve) {
                    setTimeout(resolve, intervalMs);
                }).then(function () {
                    return txWaitPoll(jobId, deadline, intervalMs, onPoll);
                });
            });
        }

        return {
            baseUrl: baseUrl,

            /* v2 — multi-hazard platform API */
            hazards: function () { return get('/api/v2/hazards'); },
            hazard: function (id) {
                return get('/api/v2/hazards/' + encodeURIComponent(String(id)));
            },
            analyze: function (hazard, lat, lon) {
                return get('/api/v2/analyze',
                    [['hazard', hazard], ['lat', lat], ['lon', lon]]);
            },
            events: function (hazard, lat, lon, radiusKm, year) {
                return get('/api/v2/events', [
                    ['hazard', hazard], ['lat', lat], ['lon', lon],
                    ['radius_km', radiusKm === undefined ? 50 : radiusKm],
                    ['year', year === undefined ? null : year]
                ]);
            },
            event: function (id) {
                return get('/api/v2/events/' + encodeURIComponent(String(id)));
            },
            economy: function (lat, lon, radiusKm) {
                return get('/api/v2/economy', [
                    ['lat', lat], ['lon', lon],
                    ['radius_km', radiusKm === undefined ? 5 : radiusKm]
                ]);
            },
            solutions: function (lat, lon, hazards) {
                return get('/api/v2/solutions', [
                    ['lat', lat], ['lon', lon],
                    ['hazards', (hazards && hazards.length) ? hazards.join(',') : null]
                ]);
            },
            sources: function () { return get('/api/v2/sources'); },

            /* TX Engine API (/api/tx/*) — uniform TxResult envelope +
             * the standard Job Object for deep analyses. */
            txHealth: function () { return get('/api/tx/health'); },
            txVersion: function () { return get('/api/tx/version'); },
            txHazards: function () { return get('/api/tx/hazards'); },
            txSources: function () { return get('/api/tx/sources'); },
            txRegistry: function () { return get('/api/tx/registry'); },
            txProducts: function () { return get('/api/tx/products'); },
            txAnalyze: function (lat, lon, options) {
                options = options || {};
                var params = [['lat', lat], ['lon', lon],
                    ['depth', options.depth || 'standard']];
                (options.hazards || []).forEach(function (h) {
                    params.push(['hazard', h]);
                });
                (options.analyses || []).forEach(function (a) {
                    params.push(['analysis', a]);
                });
                if (options.name) params.push(['name', options.name]);
                return get('/api/tx/analyze', params);
            },
            txRun: function (lat, lon, options) {
                options = options || {};
                var body = { lat: lat, lon: lon,
                             depth: options.depth || 'standard' };
                if (options.hazards && options.hazards.length) {
                    body.hazards = options.hazards;
                }
                if (options.analyses && options.analyses.length) {
                    body.analyses = options.analyses;
                }
                if (options.name) body.name = options.name;
                return post('/api/tx/run', body);
            },
            txJob: function (jobId) {
                return get('/api/tx/jobs/' + encodeURIComponent(String(jobId)));
            },
            txResult: function (jobId) {
                return get('/api/tx/jobs/' + encodeURIComponent(String(jobId)) +
                    '/result');
            },
            /* txWait(jobOrId, {timeout, interval, onPoll}) — seconds. */
            txWait: function (jobOrId, options) {
                options = options || {};
                var jobId = (jobOrId && typeof jobOrId === 'object') ?
                    jobOrId.job_id : String(jobOrId);
                var deadline = Date.now() +
                    (options.timeout === undefined ? 600 : options.timeout) * 1000;
                var intervalMs =
                    (options.interval === undefined ? 2 : options.interval) * 1000;
                return txWaitPoll(jobId, deadline, intervalMs,
                    options.onPoll || null);
            },

            /* v1 — public wildfire/intelligence endpoints */
            health: function () { return get('/api/health'); },
            riskGrid: function (south, west, north, east, n) {
                return get('/api/risk-grid', [
                    ['south', south], ['west', west], ['north', north],
                    ['east', east], ['n', n === undefined ? 6 : n]
                ]);
            },
            riskSnapshot: function () { return get('/api/risk-snapshot'); },
            history: function (lat, lon, days) {
                return get('/api/history', [
                    ['lat', lat], ['lon', lon],
                    ['days', days === undefined ? 90 : days]
                ]);
            },
            /* URL string for the PDF report (GET /api/report returns a PDF,
             * not JSON — the client does not fetch it). */
            reportUrl: function (lat, lon, reportType, history) {
                return url('/api/report', [
                    ['lat', lat], ['lon', lon],
                    ['type', reportType || 'decision'],
                    ['history', history === false ? null : '1']
                ]);
            },
            populationExposure: function (lat, lon, radiusKm) {
                return get('/api/population-exposure', [
                    ['lat', lat], ['lon', lon],
                    ['radius_km', radiusKm === undefined ? 3 : radiusKm]
                ]);
            },
            smokeScenario: function (lat, lon, hours) {
                return get('/api/smoke-scenario', [
                    ['lat', lat], ['lon', lon],
                    ['hours', hours === undefined ? 24 : hours]
                ]);
            }
        };
    }

    /* ------------------------------------------------------------------
     * <hydrashield-risk> — embeddable risk card (shadow DOM, sanitized:
     * everything untrusted goes through textContent, never innerHTML).
     *
     * Attributes: lat, lon, hazard (default wildfire),
     *             base-url (default https://talaix.com)
     * ------------------------------------------------------------------ */
    var RiskElement = null;

    var CHIP_KINDS = ['observed', 'documented', 'reported', 'modelled',
        'inferred', 'unknown', 'historical', 'forecast', 'projected',
        'scenario'];

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function renderChips(container, data) {
        var seen = {};
        function add(label) {
            var token = String(label || '').trim().toLowerCase()
                .replace(/[\s-]+/g, '_');
            if (token === 'modeled') token = 'modelled';
            if (!token || seen[token]) return;
            seen[token] = true;
            var chip = el('span',
                'hs-chip' + (CHIP_KINDS.indexOf(token) >= 0 ? ' hs-chip-' + token : ''),
                token.toUpperCase());
            container.appendChild(chip);
        }
        var prov = data && data.provenance;
        if (prov && typeof prov === 'object') {
            Object.keys(prov).forEach(function (key) {
                var p = prov[key];
                if (p && p.kind) add(p.kind);
            });
        }
        if (data && data.status === 'unavailable') add('unknown');
    }

    function defineRiskElement() {
        if (RiskElement || typeof customElements === 'undefined') return RiskElement;

        RiskElement = class extends HTMLElement {
            static get observedAttributes() {
                return ['lat', 'lon', 'hazard', 'base-url'];
            }

            connectedCallback() {
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    var style = document.createElement('style');
                    style.textContent = [
                        ':host{display:block;font-family:system-ui,sans-serif;',
                        'border:1px solid #e2e8f0;border-radius:8px;padding:12px;',
                        'max-width:340px;color:#0f172a;background:#fff}',
                        '.hs-hazard{font-size:0.8rem;text-transform:uppercase;',
                        'letter-spacing:0.05em;color:#64748b}',
                        '.hs-level{font-size:1.4rem;font-weight:700;margin:4px 0}',
                        '.hs-basis{font-size:0.85rem;color:#334155;margin:4px 0}',
                        '.hs-state{font-size:0.9rem;color:#64748b}',
                        '.hs-attr{margin-top:8px;font-size:0.75rem;color:#94a3b8}',
                        '.hs-attr a{color:#3b82f6}',
                        '.hs-chip{display:inline-block;font-size:0.65rem;',
                        'border-radius:999px;padding:1px 8px;margin:2px 2px 0 0;',
                        'background:#e2e8f0;color:#334155}',
                        '.hs-chip-observed{background:#dcfce7;color:#166534}',
                        '.hs-chip-modelled,.hs-chip-scenario{background:#dbeafe;',
                        'color:#1e40af}',
                        '.hs-chip-forecast,.hs-chip-projected{background:#f3e8ff;',
                        'color:#6b21a8}'
                    ].join('');
                    this.shadowRoot.appendChild(style);
                    this._root = el('div');
                    this.shadowRoot.appendChild(this._root);
                }
                this._load();
            }

            attributeChangedCallback() {
                if (this.shadowRoot) this._load();
            }

            _clear() {
                while (this._root.firstChild) this._root.removeChild(this._root.firstChild);
            }

            _renderState(text) {
                this._clear();
                this._root.appendChild(el('div', 'hs-state', text));
                this._renderAttribution(null);
            }

            _renderAttribution(data) {
                var attr = el('div', 'hs-attr');
                var link = document.createElement('a');
                link.href = 'https://talaix.com';
                link.rel = 'noopener';
                link.target = '_blank';
                link.textContent = 'Data: talaix.com';
                attr.appendChild(link);
                var chips = el('span');
                renderChips(chips, data);
                attr.appendChild(chips);
                this._root.appendChild(attr);
            }

            _load() {
                var lat = this.getAttribute('lat');
                var lon = this.getAttribute('lon');
                var hazard = this.getAttribute('hazard') || 'wildfire';
                var baseUrl = this.getAttribute('base-url') || DEFAULT_BASE_URL;
                if (lat === null || lon === null) {
                    this._renderState('Set the lat and lon attributes.');
                    return;
                }
                this._renderState('Loading…');
                var self = this;
                createClient({ baseUrl: baseUrl })
                    .analyze(hazard, lat, lon)
                    .then(function (data) {
                        if (!data || data.status === 'unavailable' ||
                            data.status === 'key_required') {
                            self._renderState(
                                (data && (data.unavailable_reason || data.summary)) ||
                                'Data unavailable for this location.');
                            if (data) self._renderAttributionExtra(data);
                            return;
                        }
                        self._clear();
                        self._root.appendChild(
                            el('div', 'hs-hazard', data.hazard || hazard));
                        var level = data.level || {};
                        var label = level.label || 'Unknown';
                        var scoreText = (level.score !== null && level.score !== undefined)
                            ? label + ' · ' + level.score +
                              (level.score_max ? ' / ' + level.score_max : '')
                            : label;
                        self._root.appendChild(el('div', 'hs-level', scoreText));
                        if (level.basis) {
                            self._root.appendChild(el('div', 'hs-basis', level.basis));
                        }
                        self._renderAttribution(data);
                    })
                    .catch(function (err) {
                        self._renderState(
                            'Could not load risk data (' +
                            (err && err.message ? err.message : 'network error') + ').');
                    });
            }

            _renderAttributionExtra(data) {
                /* chips for the unavailable path (attribution already added) */
                var chips = this._root.querySelector('.hs-attr span');
                if (chips) renderChips(chips, data);
            }
        };

        customElements.define('hydrashield-risk', RiskElement);
        return RiskElement;
    }

    var api = {
        createClient: createClient,
        TalaixError: TalaixError,
        DEFAULT_BASE_URL: DEFAULT_BASE_URL,
        USER_AGENT: USER_AGENT,
        /* Defined only when customElements exists (non-browser guard). */
        RiskElement: defineRiskElement()
    };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) {
        global.Talaix = api;
    }
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : null));
