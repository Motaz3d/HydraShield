/* HydraShield — shared API helpers for the v2 platform pages.
 *
 * Single place for the API base sniffing (local dev vs production), HTML
 * escaping, evidence/status chips and fetch wrappers. New pages use this;
 * the legacy dashboard.js / risk-snapshot.js keep their own copies and are
 * intentionally untouched.
 *
 * Honesty contract: helpers never invent data — callers render the real
 * payload or an explicit empty/unavailable/error state.
 */
(function () {
    'use strict';

    var API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8051/api'
        : '/api';

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /* Normalise any status/temporal/kind value to a chip class token. */
    function chipToken(kind) {
        var k = String(kind == null ? 'unknown' : kind).trim().toLowerCase()
            .replace(/[\s-]+/g, '_');
        var alias = {
            modeled: 'modelled',
            derived: 'inferred',
            ok: 'observed'
        };
        return alias[k] || k;
    }

    /* Evidence / status chip. OBSERVED=green, MODELLED=blue, FORECAST=purple,
     * UNKNOWN/UNAVAILABLE=grey (see style.css "Evidence chips"). */
    function chip(kind, label) {
        var token = chipToken(kind);
        var text = label || String(kind == null ? 'UNKNOWN' : kind).toUpperCase();
        return '<span class="chip chip-' + esc(token) + '">' + esc(text) + '</span>';
    }

    /* fetch JSON with an {ok, status, body} result — never throws on HTTP
     * errors so callers can render the honest state. */
    function fetchJSON(url, options) {
        return fetch(url, options)
            .then(function (r) {
                return r.json().then(function (body) {
                    return { ok: r.ok, status: r.status, body: body };
                }).catch(function () {
                    return { ok: r.ok, status: r.status, body: {} };
                });
            });
    }

    /* Parse "lat,lon" text; returns {lat, lon} or null. */
    function parseLatLon(text) {
        var m = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/.exec(text || '');
        if (!m) return null;
        var lat = parseFloat(m[1]);
        var lon = parseFloat(m[2]);
        if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
        return { lat: lat, lon: lon };
    }

    /* Resolve a location input ("lat,lon" or place name) to
     * {lat, lon, name}. Place names go through GET /api/analyze?location=…
     * (the platform's Nominatim-backed geocoder; the full analysis result
     * is cached server-side, so repeat resolutions are cheap). */
    function resolveLocation(text) {
        var direct = parseLatLon(text);
        if (direct) {
            return Promise.resolve({
                ok: true,
                lat: direct.lat,
                lon: direct.lon,
                name: direct.lat.toFixed(4) + ', ' + direct.lon.toFixed(4)
            });
        }
        return fetchJSON(API + '/analyze?location=' + encodeURIComponent(text))
            .then(function (res) {
                var loc = res.body && res.body.location;
                if (res.ok && loc && loc.latitude != null && loc.longitude != null) {
                    return {
                        ok: true,
                        lat: loc.latitude,
                        lon: loc.longitude,
                        name: loc.name || text,
                        analysis: res.body   // callers may reuse (NDMI grid, wildfire context)
                    };
                }
                return {
                    ok: false,
                    error: (res.body && res.body.error) ||
                        'Location could not be resolved.'
                };
            })
            .catch(function () {
                return { ok: false, error: 'The analysis service could not be reached.' };
            });
    }

    function fmt(v, unit, digits) {
        if (v === null || v === undefined || v !== v) return '—';
        if (typeof v === 'number' && digits !== undefined) v = v.toFixed(digits);
        return v + (unit || '');
    }

    function riskColor(cls) {
        return { Low: '#22c55e', Moderate: '#eab308', High: '#f97316', Extreme: '#ef4444' }[cls] || '#94a3b8';
    }

    /* Remember the last analysed/searched map location so the account page
     * can offer "save current map location". */
    function rememberLocation(loc) {
        try {
            localStorage.setItem('hs_last_location', JSON.stringify(loc));
        } catch (e) { /* private mode — harmless */ }
    }

    function lastLocation() {
        try {
            var raw = localStorage.getItem('hs_last_location');
            return raw ? JSON.parse(raw) : null;
        } catch (e) { return null; }
    }

    window.HS = {
        API: API,
        esc: esc,
        chip: chip,
        chipToken: chipToken,
        fetchJSON: fetchJSON,
        parseLatLon: parseLatLon,
        resolveLocation: resolveLocation,
        fmt: fmt,
        riskColor: riskColor,
        rememberLocation: rememberLocation,
        lastLocation: lastLocation
    };
})();
