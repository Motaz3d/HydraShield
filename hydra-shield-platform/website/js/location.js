/* HydraShield — Location Intelligence component (platform-level).
 *
 * One reusable location workflow for every surface (Intelligence, Map,
 * Events, Solutions, Economy, Funding, Reports, Monitoring):
 *
 *   named place search  →  coordinates  →  map selection
 *
 * The user never needs to know lat/lon. The component normalizes input
 * into a canonical location object:
 *
 *   { lat, lon, name, hierarchy[], crs: "EPSG:4326", source, precision,
 *     resolved_at }
 *
 * hierarchy comes from the geocoder's own display name parts (never
 * fabricated); precision is stated honestly (place-name match vs exact
 * coordinates).
 *
 * Usage: HS.location.mount('mountId', { onResolve: fn(loc) })
 */
(function () {
    'use strict';

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function parseLatLon(text) {
        var m = String(text || '').trim().match(
            /^(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)$/);
        if (!m) return null;
        var lat = parseFloat(m[1]), lon = parseFloat(m[2]);
        if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
        return { lat: lat, lon: lon };
    }

    function normalize(result, inputText) {
        /* result: HS.resolveLocation payload → canonical location. */
        var direct = parseLatLon(inputText);
        var hierarchy = (result.name || '').split(',').map(function (p) {
            return p.trim();
        }).filter(Boolean);
        return {
            lat: result.lat,
            lon: result.lon,
            name: result.name,
            hierarchy: hierarchy,
            crs: 'EPSG:4326',
            source: direct ? 'user-entered coordinates'
                           : 'Nominatim (OpenStreetMap geocoding)',
            precision: direct ? 'exact coordinates'
                              : 'place-name match (review the name)',
            resolved_at: new Date().toISOString()
        };
    }

    function mount(elId, opts) {
        var mountEl = document.getElementById(elId);
        if (!mountEl) return;
        opts = opts || {};

        mountEl.innerHTML =
            '<div class="location-widget">' +
            '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
            '<input type="text" id="' + elId + '_q" class="location-input" ' +
            'placeholder="City, region, place — or lat,lon (e.g. 49.85, 6.03)" ' +
            'aria-label="Location" style="flex:1;min-width:220px;">' +
            '<button type="button" class="btn-action" id="' + elId + '_go">Locate</button>' +
            (opts.mapLink !== false
                ? '<a class="btn-action btn-quiet" id="' + elId + '_map" href="map.html">Select on map</a>'
                : '') +
            '</div>' +
            '<p class="muted small" style="margin:6px 0 0;">Don\'t know the ' +
            'coordinates? Search for a city, region or place — or select a ' +
            'point on the map.</p>' +
            '<div id="' + elId + '_out" style="margin-top:8px;"></div>' +
            '</div>';

        var q = document.getElementById(elId + '_q');
        var out = document.getElementById(elId + '_out');

        function resolve() {
            var text = q.value.trim();
            if (!text) return;
            out.innerHTML = '<span class="muted small">Resolving location…</span>';
            HS.resolveLocation(text).then(function (res) {
                if (!res.ok) {
                    out.innerHTML = '<div class="notice notice-error">' +
                        esc(res.error || 'Location could not be resolved.') + '</div>';
                    return;
                }
                var loc = normalize(res, text);
                loc._input = text;
                out.innerHTML = cardHTML(loc);
                if (opts.mapLink !== false) {
                    document.getElementById(elId + '_map').href =
                        'map.html?location=' + encodeURIComponent(
                            loc.lat.toFixed(4) + ',' + loc.lon.toFixed(4));
                }
                if (opts.onResolve) opts.onResolve(loc);
            }).catch(function () {
                out.innerHTML = '<div class="notice notice-error">Location service ' +
                    'could not be reached.</div>';
            });
        }

        document.getElementById(elId + '_go').addEventListener('click', resolve);
        q.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') resolve();
        });
    }

    function cardHTML(loc) {
        return '<div class="notice notice-info" style="text-align:left;">' +
            '<strong>' + esc(loc.name) + '</strong><br>' +
            '<span class="muted small">' +
            loc.lat.toFixed(4) + ', ' + loc.lon.toFixed(4) + ' · ' +
            esc(loc.precision) + ' · source: ' + esc(loc.source) +
            (loc.hierarchy && loc.hierarchy.length > 1
                ? ' · ' + esc(loc.hierarchy.join(' › ')) : '') +
            '</span></div>';
    }

    /* Enhance an existing location input (progressive UX without changing
     * the page's own action flow): adds guidance, a resolution card and a
     * map link beneath the input. The page keeps its own button; the
     * canonical location object is delivered via opts.onResolve. */
    function enhance(inputId, outId, opts) {
        var input = document.getElementById(inputId);
        var out = document.getElementById(outId);
        if (!input || !out) return;
        opts = opts || {};
        out.innerHTML =
            '<p class="muted small" style="margin:6px 0 0;">Search a city, ' +
            'region or place — or paste lat,lon — or ' +
            '<a class="text-link" id="' + outId + '_map" href="map.html">select on the map</a>.</p>' +
            '<div id="' + outId + '_card"></div>';
        var card = document.getElementById(outId + '_card');

        function resolve() {
            var text = input.value.trim();
            if (!text) return;
            HS.resolveLocation(text).then(function (res) {
                if (!res.ok) return;  // the page's own flow reports errors
                var loc = normalize(res, text);
                loc._input = text;
                card.innerHTML = cardHTML(loc);
                document.getElementById(outId + '_map').href =
                    'map.html?location=' + encodeURIComponent(
                        loc.lat.toFixed(4) + ',' + loc.lon.toFixed(4));
                if (opts.onResolve) opts.onResolve(loc);
            }).catch(function () { /* page flow handles */ });
        }
        input.addEventListener('change', resolve);
    }

    window.HS = window.HS || {};
    window.HS.location = { mount: mount, enhance: enhance, normalize: normalize };
})();
