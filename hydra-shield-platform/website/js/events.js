/* HydraShield — Historical Event Intelligence (events.html).
 *
 * Location + year + radius controls → GET /api/v2/events. Event cards show
 * dates/duration, classification chip, severity, observed conditions vs
 * modelled context as two visually distinct labelled sub-blocks, lessons
 * with basis chips, the cause block (UNKNOWN shown with its note — never
 * hidden), the full evidence list and the uncertainty note. Each event
 * links to /api/v2/events/<id> ("raw evidence").
 *
 * Endpoints used:
 *   GET /api/v2/hazards                          (hazard + year controls)
 *   GET /api/analyze?location=…                  (place-name geocoding)
 *   GET /api/v2/events?hazard&lat&lon&radius_km&year
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    var hazards = [];

    function el(id) { return document.getElementById(id); }

    // ------------------------------------------------------------------
    // Controls (hazard + year, both data-driven)
    // ------------------------------------------------------------------

    function loadHazards() {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) {
                el('controlsNote').textContent = 'Hazard registry unavailable.';
                return;
            }
            hazards = res.body.hazards;
            var sel = el('hazardSelect');
            sel.innerHTML = hazards.map(function (h) {
                var ok = h.events && h.events.available;
                return '<option value="' + esc(h.id) + '"' +
                    (ok ? '' : ' disabled title="' + esc((h.events && h.events.reason) || 'Historical events unavailable') + '"') +
                    '>' + esc(h.name) + (ok ? '' : ' — events unavailable') + '</option>';
            }).join('');
            // Prefer the first hazard whose events are actually available.
            var first = hazards.filter(function (h) { return h.events && h.events.available; })[0];
            if (first) sel.value = first.id;
            sel.addEventListener('change', function () { buildYearSelector(); });
            buildYearSelector();
        }).catch(function () {
            el('controlsNote').textContent = 'Hazard registry could not be reached.';
        });
    }

    /* Years from the selected hazard's declared temporal_coverage (the
     * observed-events dataset preferred: VIIRS → FIRMS → event → MODIS) —
     * never hardcoded. */
    function buildYearSelector() {
        var h = hazards.filter(function (x) { return x.id === el('hazardSelect').value; })[0];
        var coverage = (h && h.temporal_coverage) || {};
        var currentYear = new Date().getFullYear();
        var keys = Object.keys(coverage);
        var use = keys;
        var tiers = [/viirs/i, /firms/i, /event/i, /modis/i];
        for (var t = 0; t < tiers.length; t++) {
            var hit = keys.filter(function (k) { return tiers[t].test(k); });
            if (hit.length) { use = hit; break; }
        }
        var starts = [], end = currentYear;
        use.forEach(function (k) {
            var c = coverage[k] || {};
            var s = parseInt(c.start, 10);
            if (!isNaN(s)) starts.push(s);
            var e = parseInt(c.end, 10);
            if (!isNaN(e) && e < end) end = e;
        });
        var html = '';
        if (starts.length) {
            var start = Math.min.apply(null, starts);
            for (var y = end; y >= start; y--) html += '<option value="' + y + '">' + y + '</option>';
            el('controlsNote').textContent =
                'Year range derives from the declared dataset coverage (' + use.join(', ') + '). ' +
                'Out-of-coverage years are answered with an honest unavailable state by the API.';
        } else {
            html = '<option value="' + currentYear + '">' + currentYear + '</option>';
            el('controlsNote').textContent = 'No historical coverage declared for this hazard.';
        }
        el('yearSelect').innerHTML = html;
    }

    // ------------------------------------------------------------------
    // Search
    // ------------------------------------------------------------------

    function search() {
        var q = el('locInput').value.trim();
        if (!q) {
            renderStatus('error', 'Enter a location — a place name or lat,lon coordinates.');
            return;
        }
        var radius = parseFloat(el('radiusInput').value) || 50;
        var year = parseInt(el('yearSelect').value, 10);
        var hazard = el('hazardSelect').value;
        renderStatus('info', 'Resolving location…');
        el('searchBtn').disabled = true;
        el('eventsArea').innerHTML = '';

        HS.resolveLocation(q).then(function (loc) {
            if (!loc.ok) {
                el('searchBtn').disabled = false;
                renderStatus('error', loc.error || 'Location could not be resolved.');
                return;
            }
            renderStatus('info', 'Loading events for ' + loc.name + '…');
            var url = API + '/v2/events?hazard=' + encodeURIComponent(hazard) +
                '&lat=' + loc.lat.toFixed(4) + '&lon=' + loc.lon.toFixed(4) +
                '&radius_km=' + encodeURIComponent(radius) +
                (year ? '&year=' + year : '');
            return fetchJSON(url).then(function (res) {
                el('searchBtn').disabled = false;
                renderEvents(res.body || {}, res.ok, loc);
            });
        }).catch(function () {
            el('searchBtn').disabled = false;
            renderStatus('error', 'The events service could not be reached.');
        });
    }

    function renderStatus(kind, msg) {
        el('statusArea').innerHTML =
            '<div class="notice notice-' + kind + '">' + esc(msg) + '</div>';
    }

    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------

    function renderEvents(body, ok, loc) {
        var area = el('eventsArea');

        if (body.status === 'key_required') {
            renderStatus('warn', '');
            el('statusArea').innerHTML =
                '<div class="notice notice-warn"><strong>Observed events require a server-side key.</strong><br>' +
                esc(body.reason || '') +
                (body.signup ? ' <a class="text-link" href="' + esc(body.signup) +
                    '" target="_blank" rel="noopener">Get a free NASA FIRMS key</a>.' : '') +
                (body.fallback ? '<br>' + esc(body.fallback) : '') + '</div>';
            return;
        }
        if (!ok || body.status === 'unavailable' || body.status === 'error') {
            renderStatus('warn', 'Events unavailable: ' + (body.reason || body.error || 'request failed') +
                (body.coverage_note ? ' ' + body.coverage_note : ''));
            return;
        }

        var events = body.events || [];
        var query = body.query || {};
        if (!events.length) {
            renderStatus('empty', 'No observed events for ' + (query.year || 'this year') +
                ' within ' + (query.radius_km || '?') + ' km of ' + loc.name +
                '. This is an honest empty result — the datasets were queried and returned no events.');
            return;
        }

        el('statusArea').innerHTML =
            '<div class="notice notice-info">' + events.length + ' event(s) · ' +
            (body.detection_count != null ? body.detection_count + ' satellite detection(s) · ' : '') +
            esc(loc.name) + ' · year ' + esc(query.year) + ' · ' + esc(query.radius_km) + ' km radius' +
            (body.generated_at ? ' · derived ' + esc(body.generated_at.slice(0, 10)) : '') + '</div>';

        area.innerHTML = events.map(eventCardHTML).join('');

        if (window.HS && HS.track) HS.track('historical_year_selected',
            { hazard: body.hazard, lat: loc.lat, lon: loc.lon });
        if (window.HSConvert) HSConvert.show({
            mount: 'statusArea', context: 'monitor_area',
            text: 'Track this area — get an alert when conditions change meaningfully.',
            cta: 'Monitor this area', href: 'account.html#sms'
        });

        // Wire the per-event daily-table expanders lazily (they are plain
        // <details> elements — no JS needed, but keep the hook minimal).
    }

    function eventCardHTML(ev) {
        var sev = ev.severity || {};
        var html = '<div class="panel">';

        // Header: name, dates, duration, classification.
        html += '<h2>' + esc(ev.name || 'Event') + '</h2>';
        html += '<div class="badge-row">' +
            chip(ev.classification || 'OBSERVED') +
            '<span class="muted small">' + esc(ev.start_date) +
            (ev.end_date && ev.end_date !== ev.start_date ? ' → ' + esc(ev.end_date) : '') +
            ' · ' + esc(ev.duration_days) + ' day' + (ev.duration_days === 1 ? '' : 's') +
            ' · ' + esc(ev.lat) + ', ' + esc(ev.lon) + '</span></div>';

        // Severity.
        if (sev.detections != null) {
            html += '<h3>Severity</h3><div class="table-scroll"><table class="kv-table">' +
                '<tr><th>Satellite detections</th><td>' + esc(sev.detections) +
                ' over ' + esc(sev.detection_days) + ' day(s)</td></tr>' +
                '<tr><th>Peak fire radiative power</th><td>' + esc(sev.max_frp_mw) + ' MW' +
                (sev.mean_frp_mw != null ? ' (mean ' + esc(sev.mean_frp_mw) + ' MW)' : '') + '</td></tr>' +
                '<tr><th>Sensor</th><td>' + esc(sev.sensor) + ' · ' + esc(sev.resolution) + '</td></tr>' +
                '</table></div>';
        }

        // Observed conditions vs modelled context — visually distinct blocks.
        html += renderObservedBlock(ev.conditions_observed);
        html += renderModelledBlock(ev.context_modelled);

        // Cause — UNKNOWN shown with its note, never hidden.
        var cause = ev.cause || {};
        html += '<div class="sub-block ' + (cause.status === 'UNKNOWN' ? 'sub-unknown' : 'sub-observed') + '">' +
            '<div class="sub-block-title">Cause ' + chip(cause.status || 'UNKNOWN') + '</div>' +
            (cause.value ? '<div>' + esc(cause.value) +
                (cause.source ? ' <span class="muted small">(' + esc(cause.source) + ')</span>' : '') + '</div>' : '') +
            (cause.note ? '<div class="muted small">' + esc(cause.note) + '</div>' : '') +
            '</div>';

        // Lessons with basis chips.
        if (ev.lessons && ev.lessons.length) {
            html += '<h3>Lessons</h3>';
            html += ev.lessons.map(function (l) {
                return '<div class="sub-block"><div>' + esc(l.text) + '</div>' +
                    '<div class="badge-row" style="margin-top:6px;">' + chip(l.basis || 'UNKNOWN') +
                    (l.source ? '<span class="muted small">' + esc(l.source) + '</span>' : '') +
                    '</div></div>';
            }).join('');
        }

        // Evidence list.
        if (ev.evidence && ev.evidence.length) {
            html += '<details class="expander"><summary>Evidence (' + ev.evidence.length + ' record' +
                (ev.evidence.length === 1 ? '' : 's') + ')</summary>';
            html += ev.evidence.map(function (rec) {
                var period = rec.reference_period
                    ? (rec.reference_period.start || '') + (rec.reference_period.end && rec.reference_period.end !== rec.reference_period.start ? ' → ' + rec.reference_period.end : '')
                    : '';
                return '<div class="sub-block">' +
                    '<div class="badge-row">' + chip(rec.claim_status || 'UNKNOWN') + ' ' +
                    chip(rec.temporal || 'OBSERVED') +
                    '<span class="muted small">' + esc(rec.class || '') + '</span></div>' +
                    '<div style="margin-top:6px;"><strong>' + esc(rec.source || '') + '</strong>' +
                    (rec.dataset ? ' · ' + esc(rec.dataset) : '') + '</div>' +
                    '<div class="muted small">' +
                    [rec.method && 'Method: ' + rec.method,
                     rec.resolution && 'Resolution: ' + rec.resolution,
                     period && 'Period: ' + period,
                     rec.limitations && 'Limitations: ' + rec.limitations]
                        .filter(Boolean).map(esc).join('<br>') + '</div>' +
                    (rec.provider_url ? '<a class="text-link" href="' + esc(rec.provider_url) +
                        '" target="_blank" rel="noopener">Provider →</a>' : '') +
                    '</div>';
            }).join('');
            html += '</details>';
        }

        // Uncertainty note.
        if (ev.uncertainty) {
            html += '<div class="disclaimer-box">Uncertainty: ' + esc(ev.uncertainty) + '</div>';
        }

        // Raw evidence link.
        html += '<div style="margin-top:14px;"><a class="text-link" href="' + API + '/v2/events/' +
            esc(ev.event_id) + '" target="_blank" rel="noopener">Raw evidence (JSON) →</a></div>';

        html += '</div>';
        return html;
    }

    function renderObservedBlock(co) {
        if (!co || !Object.keys(co).length) return '';
        if (co.status) {
            return '<div class="sub-block sub-unknown"><div class="sub-block-title">Observed conditions ' +
                chip(co.status === 'not_enriched' ? 'UNAVAILABLE' : co.status) + '</div>' +
                '<div class="muted small">' + esc(co.reason || '') + '</div></div>';
        }
        var daily = co.daily || [];
        var html = '<div class="sub-block sub-observed">' +
            '<div class="sub-block-title">Observed conditions ' + chip('OBSERVED') + '</div>' +
            '<div class="muted small">' + esc(co.source || '') +
            (co.limitations ? ' — ' + esc(co.limitations) : '') + '</div>';
        if (daily.length) {
            html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Date</th><th>Tmax (°C)</th><th>RH mean (%)</th><th>Wind max (km/h)</th><th>Rain (mm)</th>' +
                '</tr></thead><tbody>' +
                daily.map(function (d) {
                    return '<tr><td>' + esc(d.date) + '</td><td>' + esc(d.temp_max_c) + '</td><td>' +
                        esc(d.rh_mean_pct) + '</td><td>' + esc(d.wind_max_kmh) + '</td><td>' + esc(d.rain_mm) + '</td></tr>';
                }).join('') + '</tbody></table></div>';
        }
        html += '</div>';
        return html;
    }

    function renderModelledBlock(cm) {
        if (!cm || !Object.keys(cm).length) return '';
        var fwi = cm.fwi_daily || [];
        var html = '<div class="sub-block sub-modelled">' +
            '<div class="sub-block-title">Modelled context ' + chip('MODELLED') + '</div>' +
            (cm.method ? '<div class="muted small">' + esc(cm.method) + '</div>' : '');
        if (fwi.length) {
            html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Date</th><th>FWI</th><th>Danger class</th></tr></thead><tbody>' +
                fwi.map(function (d) {
                    return '<tr><td>' + esc(d.date) + '</td><td>' + esc(d.fwi) + '</td><td>' +
                        esc(d.danger_class) + '</td></tr>';
                }).join('') + '</tbody></table></div>';
        }
        html += '</div>';
        return html;
    }

    // ------------------------------------------------------------------
    // Init
    // ------------------------------------------------------------------

    function init() {
        loadHazards();
        el('searchBtn').addEventListener('click', search);
        el('locInput').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') search();
        });
        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q) {
            el('locInput').value = q;
            search();
        }
    }

    init();
})();
