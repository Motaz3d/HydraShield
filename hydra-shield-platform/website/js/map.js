/* HydraShield — the Map (map.html).
 *
 * The map is the core product: full-viewport Leaflet + a control sidebar.
 * Hazard selector from GET /api/v2/hazards (availability honoured), year
 * selector derived from each hazard's temporal_coverage (never hardcoded),
 * and a lazy layer panel grouped HAZARD / ENVIRONMENT / EVIDENCE /
 * EXPOSURE. Every layer shows legend, source, resolution, status, temporal
 * class and provenance; every fetch renders honest loading / empty /
 * unavailable / key_required / error states. No invented data anywhere.
 *
 * Endpoints used:
 *   GET /api/v2/hazards · GET /api/v2/hazards/<id>
 *   GET /api/risk-grid?south&west&north&east&n=6          (fire-danger grid)
 *   GET /api/v2/events?hazard=wildfire&lat&lon&radius_km&year=
 *   GET /api/analyze?location= | ?lat&lon                 (geocode + NDMI)
 *   GET /api/exposure-features?lat&lon&radius_m           (OSM exposure)
 *   GET /api/fires?lat&lon&days&radius_km                 (active fires)
 *   GET /api/v2/analyze?hazard=<id>&lat&lon               (point layers)
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    var OBSERVED_BUCKET = { OBSERVED: 1, HISTORICAL: 1 };
    var MODELLED_BUCKET = { FORECAST: 1, PROJECTED: 1, SCENARIO: 1 };
    var GROUP_ORDER = ['HAZARD', 'ENVIRONMENT', 'EVIDENCE', 'EXPOSURE', 'PROJECTION'];

    var map = null;
    var legendControl = null;
    var hazards = [];
    var hazardDetail = null;          // descriptor + map_layers of selected hazard
    var layers = [];                  // layer records (see buildLayerPanel)
    var analysisCache = {};           // key → v1 or v2 analysis payload
    var locationMarker = null;
    var moveTimer = null;

    function el(id) { return document.getElementById(id); }

    function currentCenter() {
        var c = map.getCenter();
        return { lat: c.lat, lon: c.lng };
    }

    function selectedYear() {
        var v = el('yearSelect').value;
        return v === 'current' ? null : parseInt(v, 10);
    }

    function evidenceBucketOk(temporal) {
        var f = el('evidenceFilter').value;
        if (f === 'all') return true;
        if (f === 'observed') return !!OBSERVED_BUCKET[temporal];
        return !!MODELLED_BUCKET[temporal];
    }

    // ------------------------------------------------------------------
    // Map init
    // ------------------------------------------------------------------

    function initMap() {
        map = L.map('map').setView([50.45, 7.0], 7);
        if (window.HS && HS.track) HS.track('map_opened');
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 18,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);

        map.on('moveend', function () {
            if (moveTimer) clearTimeout(moveTimer);
            moveTimer = setTimeout(refreshActiveLayers, 1200);
        });

        el('sidebarToggle').addEventListener('click', function () {
            el('mapSidebar').classList.toggle('open');
        });
    }

    /* Re-fetch the cheap, centre/viewport-bound layers after the map moves. */
    function refreshActiveLayers() {
        layers.forEach(function (rec) {
            if (!rec.active) return;
            if (rec.spec.layer_id === 'wildfire.danger_grid' ||
                rec.spec.layer_id === 'wildfire.events' ||
                rec.spec.layer_id === 'platform.exposure_features' ||
                rec.spec.layer_id === 'platform.active_fires') {
                loadLayer(rec, true);
            }
        });
    }

    // ------------------------------------------------------------------
    // Hazard + year selectors
    // ------------------------------------------------------------------

    function loadHazards(preselect) {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) {
                el('hazardStatus').textContent = 'Hazard registry unavailable — layers cannot be built.';
                return;
            }
            hazards = res.body.hazards;
            var sel = el('hazardSelect');
            sel.innerHTML = hazards.map(function (h) {
                var avail = h.analysis && h.analysis.available;
                var label = h.name + (avail ? '' : ' — unavailable');
                return '<option value="' + esc(h.id) + '"' +
                    (avail ? '' : ' disabled title="' + esc(h.analysis.reason || 'Unavailable') + '"') +
                    '>' + esc(label) + '</option>';
            }).join('');
            var wanted = preselect || 'wildfire';
            if (hazards.some(function (h) { return h.id === wanted && h.analysis.available; })) {
                sel.value = wanted;
            }
            sel.addEventListener('change', function () { selectHazard(sel.value); });
            selectHazard(sel.value);
        }).catch(function () {
            el('hazardStatus').textContent = 'Hazard registry could not be reached.';
        });
    }

    function selectHazard(hazardId) {
        var h = hazards.filter(function (x) { return x.id === hazardId; })[0];
        el('hazardStatus').textContent = h && h.tagline ? h.tagline : '';
        teardownLayers();
        buildYearSelector(h ? h.temporal_coverage : {});
        fetchJSON(API + '/v2/hazards/' + encodeURIComponent(hazardId)).then(function (res) {
            if (!res.ok) {
                el('layerPanel').innerHTML =
                    '<div class="notice notice-error">Layer definitions unavailable: ' +
                    esc(res.body.error || 'unknown hazard') + '</div>';
                return;
            }
            hazardDetail = res.body;
            buildLayerPanel(hazardDetail);
        }).catch(function () {
            el('layerPanel').innerHTML =
                '<div class="notice notice-error">Layer definitions could not be reached.</div>';
        });
    }

    /* Years from the hazard's declared temporal_coverage — never hardcoded.
     * The observed-events dataset is preferred (VIIRS, then FIRMS, then any
     * event/modis dataset); otherwise the earliest declared start is used.
     * "Current" is always offered. */
    function coverageDatasets(coverage) {
        var keys = Object.keys(coverage || {});
        var tiers = [/viirs/i, /firms/i, /event/i, /modis/i];
        for (var t = 0; t < tiers.length; t++) {
            var hit = keys.filter(function (k) { return tiers[t].test(k); });
            if (hit.length) return hit;
        }
        return keys;
    }

    function buildYearSelector(coverage) {
        var currentYear = new Date().getFullYear();
        var use = coverageDatasets(coverage);
        var starts = [], end = currentYear;
        use.forEach(function (k) {
            var c = coverage[k] || {};
            var s = parseInt(c.start, 10);
            if (!isNaN(s)) starts.push(s);
            var e = parseInt(c.end, 10);
            if (!isNaN(e) && e < end) end = e;
        });
        var html = '<option value="current">Current</option>';
        if (starts.length) {
            var start = Math.min.apply(null, starts);
            for (var y = end; y >= start; y--) {
                html += '<option value="' + y + '">' + y + '</option>';
            }
            el('yearStatus').textContent =
                'Years derive from the declared dataset coverage (' + use.join(', ') + ').';
        } else {
            el('yearStatus').textContent = 'No historical coverage declared for this hazard.';
        }
        el('yearSelect').innerHTML = html;
    }

    // ------------------------------------------------------------------
    // Layer panel
    // ------------------------------------------------------------------

    function teardownLayers() {
        layers.forEach(function (rec) {
            if (rec.leafletLayer) map.removeLayer(rec.leafletLayer);
        });
        layers = [];
        if (legendControl) { legendControl.remove(); legendControl = null; }
        if (locationMarker) { /* keep the location marker across hazards */ }
    }

    /* Platform-wide layers appended to the hazard's declared map_layers. */
    function platformLayers(hazardId) {
        var out = [{
            layer_id: 'platform.exposure_features',
            label: 'Exposure features (OSM: hospitals, schools, fire stations, water)',
            group: 'EXPOSURE',
            kind: 'points',
            legend: {
                'Hospitals': '#e11d48', 'Schools': '#7c3aed',
                'Fire stations': '#ea580c', 'Water': '#0284c7'
            },
            source: 'OpenStreetMap (Overpass API)',
            url: 'https://www.openstreetmap.org/',
            resolution: 'Mapped features within 2 km of the map centre',
            status: 'available',
            temporal: 'OBSERVED',
            provenance: { note: 'Mapped OSM features; completeness varies by region — counts are a lower bound, not a census.' }
        }, {
            layer_id: 'platform.population_exposure',
            label: 'Population exposure (WorldPop 100 m estimates)',
            group: 'EXPOSURE',
            kind: 'grid',
            source: 'WorldPop gridded population (reference-year estimates)',
            url: 'https://hub.worldpop.org/',
            resolution: '100 m grid aggregated to cells within 3 km of the map centre',
            status: 'available',
            temporal: 'MODELLED',
            provenance: { note: 'Gridded reference-year estimates — never exact counts; overlaid on the FWI hazard grid for population-by-hazard-class.' }
        }];
        if (hazardId === 'wildfire') {
            out.push({
                layer_id: 'platform.active_fires',
                label: 'Active fires (NASA FIRMS, near-real-time)',
                group: 'EVIDENCE',
                kind: 'points',
                source: 'NASA FIRMS VIIRS S-NPP + MODIS (per-sensor, never merged)',
                url: 'https://firms.modaps.eosdis.nasa.gov/',
                resolution: '375 m (VIIRS) / 1 km (MODIS)',
                status: 'available',
                temporal: 'OBSERVED',
                provenance: { note: 'Hotspot detections, not fire perimeters. Requires the server-side FIRMS key; a key_required state is shown honestly when absent.' }
            });
            out.push({
                layer_id: 'platform.smoke_scenario',
                label: 'Smoke corridor — scenario (hypothetical fire)',
                group: 'HAZARD',
                kind: 'geojson',
                source: 'Open-Meteo wind profile (screening transport model)',
                url: 'https://open-meteo.com/',
                resolution: '~11 km NWP grid; corridor is a screening envelope',
                status: 'available',
                temporal: 'SCENARIO',
                provenance: { note: 'MODELLED what-if: no fire is observed at this location. Sharp-turn self-intersections possible; never a deterministic path.' }
            });
            out.push({
                layer_id: 'platform.smoke_observed',
                label: 'Smoke corridor — observed fires (FIRMS)',
                group: 'EVIDENCE',
                kind: 'geojson',
                source: 'NASA FIRMS detections + Open-Meteo wind profile',
                url: 'https://firms.modaps.eosdis.nasa.gov/',
                resolution: '375 m detections; ~11 km wind grid',
                status: 'key_required',
                temporal: 'OBSERVED',
                provenance: { note: 'Requires the server-side FIRMS key; an honest unavailable state is shown without it. Observed and scenario smoke are never mixed.' }
            });
        }
        return out;
    }

    function buildLayerPanel(detail) {
        var specs = (detail.map_layers || []).concat(platformLayers(detail.id));
        var panel = el('layerPanel');
        panel.innerHTML = '';
        if (!specs.length) {
            panel.innerHTML = '<div class="layer-state" style="padding-left:0;">No map layers declared for this hazard.</div>';
            return;
        }

        var groups = {};
        specs.forEach(function (spec) {
            var g = spec.group || 'OTHER';
            if (!groups[g]) groups[g] = [];
            groups[g].push(spec);
        });

        var order = GROUP_ORDER.filter(function (g) { return groups[g]; })
            .concat(Object.keys(groups).filter(function (g) { return GROUP_ORDER.indexOf(g) < 0; }));

        order.forEach(function (g) {
            var title = document.createElement('div');
            title.className = 'layer-group-title';
            title.textContent = g;
            panel.appendChild(title);
            groups[g].forEach(function (spec) { panel.appendChild(layerRow(spec)); });
        });

        // Default-on layers (e.g. the fire-danger grid for wildfire).
        layers.forEach(function (rec) {
            if (rec.spec.default_on && !rec.checkbox.disabled) {
                rec.checkbox.checked = true;
                enableLayer(rec);
            }
        });
    }

    function layerRow(spec) {
        var rec = {
            spec: spec,
            leafletLayer: null,
            loaded: false,
            active: false,
            checkbox: null,
            stateEl: null
        };
        layers.push(rec);

        var wrap = document.createElement('div');

        var row = document.createElement('div');
        row.className = 'layer-row';

        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.setAttribute('aria-label', spec.label);
        rec.checkbox = cb;

        var label = document.createElement('label');
        label.className = 'layer-label';
        label.textContent = spec.label;
        if (spec.status !== 'available') {
            label.classList.add('disabled');
        }

        var infoBtn = document.createElement('button');
        infoBtn.type = 'button';
        infoBtn.className = 'layer-info-btn';
        infoBtn.textContent = 'info';
        infoBtn.setAttribute('aria-label', 'Layer details: ' + spec.label);

        row.appendChild(cb);
        row.appendChild(label);
        row.appendChild(infoBtn);
        wrap.appendChild(row);

        var detail = document.createElement('div');
        detail.className = 'layer-detail';
        detail.hidden = true;
        detail.innerHTML = layerDetailHTML(spec);
        wrap.appendChild(detail);

        var state = document.createElement('div');
        state.className = 'layer-state';
        rec.stateEl = state;
        wrap.appendChild(state);

        if (spec.status !== 'available') {
            cb.disabled = true;
            state.textContent = spec.status === 'key_required'
                ? 'Requires a server-side key — the honest state is shown when enabled.'
                : (spec.status || 'unavailable');
            // key_required layers stay toggleable: enabling shows the honest
            // API state. Only hard-unavailable definitions are disabled.
            if (spec.status === 'key_required') {
                cb.disabled = false;
            }
        }

        infoBtn.addEventListener('click', function () { detail.hidden = !detail.hidden; });
        cb.addEventListener('change', function () {
            if (cb.checked) {
                enableLayer(rec);
                if (window.HS && HS.track) HS.track('map_layer_enabled',
                    { feature: rec.spec.layer_id, hazard: rec.spec.group });
            } else disableLayer(rec);
        });

        applyEvidenceFilter();
        return wrap;
    }

    function layerDetailHTML(spec) {
        var html = '';
        if (spec.legend) {
            html += '<div class="legend-swatches">' +
                Object.keys(spec.legend).map(function (k) {
                    return '<span class="swatch"><i style="background:' + esc(spec.legend[k]) + '"></i>' + esc(k) + '</span>';
                }).join('') + '</div>';
        }
        if (spec.source) {
            html += '<div>Source: ' + (spec.url
                ? '<a class="text-link" href="' + esc(spec.url) + '" target="_blank" rel="noopener">' + esc(spec.source) + '</a>'
                : esc(spec.source)) + '</div>';
        }
        if (spec.resolution) html += '<div>Resolution: ' + esc(spec.resolution) + '</div>';
        if (spec.date) html += '<div>Date: ' + esc(spec.date) + '</div>';
        html += '<div style="margin-top:4px;">' +
            chip(spec.temporal || 'OBSERVED') + ' ' + chip(spec.status || 'available', (spec.status || 'available').toUpperCase().replace('_', ' ')) +
            '</div>';
        if (spec.provenance && spec.provenance.note) {
            html += '<div style="margin-top:4px;">' + esc(spec.provenance.note) + '</div>';
        }
        return html;
    }

    /* Observed/modelled toggle: disables layers outside the chosen bucket. */
    function applyEvidenceFilter() {
        layers.forEach(function (rec) {
            var t = rec.spec.temporal || 'OBSERVED';
            var ok = evidenceBucketOk(t);
            rec.checkbox.disabled = !ok || (rec.spec.status !== 'available' && rec.spec.status !== 'key_required');
            if (!ok && rec.active) {
                rec.checkbox.checked = false;
                disableLayer(rec);
            }
        });
    }

    // ------------------------------------------------------------------
    // Layer enable / load
    // ------------------------------------------------------------------

    function enableLayer(rec) {
        rec.active = true;
        if (!rec.leafletLayer) rec.leafletLayer = L.layerGroup();
        rec.leafletLayer.addTo(map);
        loadLayer(rec, false);
    }

    function disableLayer(rec) {
        rec.active = false;
        if (rec.leafletLayer) map.removeLayer(rec.leafletLayer);
        setState(rec, '');
        if (rec.spec.layer_id === 'wildfire.danger_grid' && legendControl) {
            legendControl.remove();
            legendControl = null;
        }
    }

    function setState(rec, html) {
        if (rec.stateEl) rec.stateEl.innerHTML = html;
    }

    function loadLayer(rec, isRefresh) {
        var id = rec.spec.layer_id;
        setState(rec, 'Loading…');
        if (id === 'wildfire.danger_grid') return loadDangerGrid(rec);
        if (id === 'wildfire.events') return loadEventsLayer(rec);
        if (id === 'wildfire.ndmi') return loadNdmiLayer(rec, isRefresh);
        if (id === 'platform.exposure_features') return loadExposureFeatures(rec);
        if (id === 'platform.active_fires') return loadActiveFires(rec);
        if (id === 'platform.population_exposure') return loadPopulationExposure(rec);
        if (id === 'platform.smoke_scenario') return loadSmokeCorridor(rec, false);
        if (id === 'platform.smoke_observed') return loadSmokeCorridor(rec, true);
        if (rec.spec.endpoint && rec.spec.endpoint.indexOf('/api/v2/analyze') === 0) {
            return loadPointAnalysisLayer(rec);
        }
        // Declared layer with no fetchable product wired — say so honestly.
        rec.loaded = true;
        setState(rec, 'Declared layer — no fetchable spatial product is wired for it yet. ' +
            'See the layer info and the source registry.');
    }

    /* ---- Fire-danger grid: GeoJSON choropleth from /api/risk-grid ------ */
    function loadDangerGrid(rec) {
        var c = currentCenter();
        var b = map.getBounds();
        var halfLat = Math.min(Math.abs(b.getNorth() - b.getSouth()) / 2, 0.7);
        var halfLon = Math.min(Math.abs(b.getEast() - b.getWest()) / 2, 0.7);
        var url = API + '/risk-grid?south=' + (c.lat - halfLat).toFixed(4) +
            '&west=' + (c.lon - halfLon).toFixed(4) +
            '&north=' + (c.lat + halfLat).toFixed(4) +
            '&east=' + (c.lon + halfLon).toFixed(4) + '&n=6';
        fetchJSON(url).then(function (res) {
            if (!rec.active) return;
            if (!res.ok || res.body.error) {
                rec.loaded = false;
                setState(rec, 'Fire-danger grid unavailable: ' + esc(res.body.error || 'request failed'));
                return;
            }
            rec.leafletLayer.clearLayers();
            var g = res.body;
            var geo = L.geoJSON(g, {
                style: function (f) {
                    var p = f.properties;
                    return {
                        color: 'rgba(0,0,0,0.15)', weight: 1,
                        fillColor: p.risk === null ? '#64748b' : HS.riskColor(p.risk_class),
                        fillOpacity: 0.35
                    };
                },
                onEachFeature: function (f, l) {
                    var p = f.properties;
                    l.bindPopup('<b>RISK CELL</b><br>HydraShield: ' +
                        (p.risk === null ? 'n/a' : p.risk + '/100 (' + esc(p.risk_class) + ')') +
                        '<br>FWI: ' + (p.fwi === null ? 'n/a' : p.fwi) +
                        ' · slope ' + esc(p.slope_deg) + '°' +
                        '<br><span style="color:#94a3b8">Composite indicator — not a probability of fire.<br>' +
                        'Cell ~' + esc(g.grid.cell_size_km) + ' km; FWI from real Open-Meteo data.</span>');
                }
            });
            rec.leafletLayer.addLayer(geo);
            rec.loaded = true;
            setState(rec, 'Grid: FWI from Open-Meteo daily data (cell ~' +
                esc(g.grid.cell_size_km) + ' km), slope from DEM. Current conditions; cached 1 h.');
            updateLegend(rec);
        }).catch(function () {
            if (rec.active) setState(rec, 'Fire-danger grid request failed.');
        });
    }

    /* On-map legend built from the layer's declared classes. */
    function updateLegend(rec) {
        if (legendControl) { legendControl.remove(); legendControl = null; }
        if (rec.spec.layer_id !== 'wildfire.danger_grid' || !rec.spec.legend) return;
        var legend = rec.spec.legend;
        legendControl = L.control({ position: 'bottomright' });
        legendControl.onAdd = function () {
            var div = L.DomUtil.create('div', 'map-legend');
            div.innerHTML = '<div class="legend-title">Fire danger (FWI-based)</div>' +
                Object.keys(legend).map(function (k) {
                    return '<div class="swatch"><i style="background:' + esc(legend[k]) + '"></i>' + esc(k) + '</div>';
                }).join('') +
                '<div style="margin-top:4px;color:#64748b;">Composite indicator — not a probability of fire.</div>';
            return div;
        };
        legendControl.addTo(map);
    }

    /* ---- Historical fire events: /api/v2/events ------------------------ */
    function loadEventsLayer(rec) {
        var c = currentCenter();
        var year = selectedYear();
        var url = API + '/v2/events?hazard=wildfire&lat=' + c.lat.toFixed(4) +
            '&lon=' + c.lon.toFixed(4) + '&radius_km=50' +
            (year ? '&year=' + year : '');
        fetchJSON(url).then(function (res) {
            if (!rec.active) return;
            var body = res.body || {};
            if (body.status === 'key_required') {
                rec.loaded = false;
                setState(rec, esc(body.reason || 'NASA FIRMS key not configured') +
                    (body.signup ? ' <a class="text-link" href="' + esc(body.signup) +
                        '" target="_blank" rel="noopener">Get a free key</a>' : '') +
                    (body.fallback ? '<br>' + esc(body.fallback) : ''));
                return;
            }
            if (!res.ok || body.status === 'unavailable' || body.status === 'error') {
                rec.loaded = false;
                setState(rec, 'Historical events unavailable: ' + esc(body.reason || body.error || 'request failed') +
                    (body.coverage_note ? '<br>' + esc(body.coverage_note) : ''));
                return;
            }
            rec.leafletLayer.clearLayers();
            var events = body.events || [];
            events.forEach(function (ev) {
                var marker = L.circleMarker([ev.lat, ev.lon], {
                    radius: 8, color: '#ef4444', weight: 2,
                    fillColor: '#f97316', fillOpacity: 0.55
                }).bindPopup(eventPopupHTML(ev));
                rec.leafletLayer.addLayer(marker);
            });
            rec.loaded = true;
            var yr = (body.query && body.query.year) || year;
            setState(rec, events.length
                ? events.length + ' observed event(s), ' + (body.detection_count != null ? body.detection_count + ' detection(s), ' : '') +
                  'year ' + esc(yr) + ', 50 km radius.'
                : 'No observed events for this year/radius (' + esc(yr) + ', 50 km).');
        }).catch(function () {
            if (rec.active) setState(rec, 'Historical events request failed.');
        });
    }

    function eventPopupHTML(ev) {
        var filter = el('evidenceFilter').value;
        var sev = ev.severity || {};
        var html = '<b>' + esc(ev.name || 'Fire event') + '</b><br>' +
            esc(ev.start_date) + (ev.end_date && ev.end_date !== ev.start_date ? ' → ' + esc(ev.end_date) : '') +
            ' (' + esc(ev.duration_days) + ' day' + (ev.duration_days === 1 ? '' : 's') + ') ' +
            chip(ev.classification || 'OBSERVED') + '<br>';
        if (sev.detections != null) {
            html += 'Detections: ' + esc(sev.detections) + ' over ' + esc(sev.detection_days) +
                ' day(s) · peak FRP ' + esc(sev.max_frp_mw) + ' MW (' + esc(sev.sensor) + ', ' + esc(sev.resolution) + ')<br>';
        }
        if (ev.lessons && ev.lessons.length) {
            html += 'Lessons recorded: ' + ev.lessons.length + '<br>';
        }
        if (filter !== 'modelled' && ev.conditions_observed && ev.conditions_observed.daily) {
            html += '<span style="color:#15803d">Observed conditions (ERA5): ' +
                ev.conditions_observed.daily.length + ' day(s) recorded.</span><br>';
        }
        if (filter !== 'observed' && ev.context_modelled && ev.context_modelled.fwi_daily) {
            var fwis = ev.context_modelled.fwi_daily;
            var peak = fwis.reduce(function (a, b) { return (b.fwi > a.fwi ? b : a); }, fwis[0]);
            html += '<span style="color:#0369a1">Modelled context (FWI on ERA5): peak FWI ' +
                esc(peak.fwi) + ' (' + esc(peak.danger_class) + ') on ' + esc(peak.date) + '.</span><br>';
        }
        if (ev.cause && ev.cause.status === 'UNKNOWN') {
            html += 'Cause: ' + chip('UNKNOWN') + (ev.cause.note ? ' <span style="color:#64748b">' + esc(ev.cause.note) + '</span>' : '') + '<br>';
        }
        html += '<a href="' + API + '/v2/events/' + esc(ev.event_id) +
            '" target="_blank" rel="noopener">Raw evidence (JSON) →</a>';
        return html;
    }

    /* ---- NDMI raster: Sentinel-2 scene rectangles via /api/analyze ----- */
    function ndmiColor(v) {
        var t = Math.max(0, Math.min(1, (v + 0.2) / 0.8));
        var r = Math.round(180 - t * 150);
        var g = Math.round(90 + t * 110);
        return 'rgb(' + r + ',' + g + ',60)';
    }

    function fetchV1Analysis() {
        var c = currentCenter();
        var key = 'v1@' + c.lat.toFixed(3) + ',' + c.lon.toFixed(3);
        if (analysisCache[key]) return Promise.resolve({ ok: true, body: analysisCache[key] });
        return fetchJSON(API + '/analyze?lat=' + c.lat.toFixed(4) + '&lon=' + c.lon.toFixed(4))
            .then(function (res) {
                if (res.ok && !res.body.error) analysisCache[key] = res.body;
                return res;
            });
    }

    function loadNdmiLayer(rec, isRefresh) {
        fetchV1Analysis().then(function (res) {
            if (!rec.active) return;
            if (!res.ok || res.body.error) {
                rec.loaded = false;
                setState(rec, 'NDMI scene unavailable: ' + esc(res.body.error || 'analysis failed'));
                return;
            }
            var sat = res.body.satellite || {};
            if (!(sat.ndmi_grid && sat.grid_bounds)) {
                rec.loaded = false;
                setState(rec, 'No Sentinel-2 NDMI scene available for this location — the satellite block reports: ' +
                    esc(sat.error || sat.note || 'unavailable') + '.');
                return;
            }
            rec.leafletLayer.clearLayers();
            var b = sat.grid_bounds;
            var n = sat.ndmi_grid.length;
            for (var i = 0; i < n; i++) {
                for (var j = 0; j < sat.ndmi_grid[i].length; j++) {
                    var v = sat.ndmi_grid[i][j];
                    if (v === null) continue;
                    var lat0 = b.lat_max - (i / n) * (b.lat_max - b.lat_min);
                    var lat1 = b.lat_max - ((i + 1) / n) * (b.lat_max - b.lat_min);
                    var lon0 = b.lon_min + (j / n) * (b.lon_max - b.lon_min);
                    var lon1 = b.lon_min + ((j + 1) / n) * (b.lon_max - b.lon_min);
                    rec.leafletLayer.addLayer(L.rectangle([[lat0, lon0], [lat1, lon1]], {
                        stroke: false, fillColor: ndmiColor(v), fillOpacity: 0.55
                    }).bindPopup('<b>SENTINEL-2</b><br>Observation: ' +
                        esc(String(sat.observation_date || '').slice(0, 10)) +
                        '<br>NDMI: ' + v.toFixed(2) + ' (fuel-moisture proxy)' +
                        '<br><span style="color:#94a3b8">10 m resolution · real scene pixels (OBSERVED)</span>'));
                }
            }
            rec.loaded = true;
            setState(rec, 'NDMI 10 m scene of ' + esc(String(sat.observation_date || '').slice(0, 10)) +
                ' (Sentinel-2). Brown = dry, green = moist.');
        }).catch(function () {
            if (rec.active) setState(rec, 'NDMI request failed.');
        });
    }

    /* ---- Exposure features: /api/exposure-features --------------------- */
    var EXPOSURE_COLORS = {
        hospitals: '#e11d48', schools: '#7c3aed',
        fire_stations: '#ea580c', water_features: '#0284c7'
    };

    function loadExposureFeatures(rec) {
        var c = currentCenter();
        fetchJSON(API + '/exposure-features?lat=' + c.lat.toFixed(4) +
            '&lon=' + c.lon.toFixed(4) + '&radius_m=2000').then(function (res) {
                if (!rec.active) return;
                if (!res.ok || res.body.error) {
                    rec.loaded = false;
                    setState(rec, 'Exposure features unavailable: ' + esc(res.body.error || 'request failed'));
                    return;
                }
                rec.leafletLayer.clearLayers();
                var feats = res.body.features || [];
                feats.forEach(function (f) {
                    var color = EXPOSURE_COLORS[f.category] || '#0ea5e9';
                    rec.leafletLayer.addLayer(L.circleMarker([f.lat, f.lon], {
                        radius: 6, color: color, weight: 2, fillOpacity: 0.7
                    }).bindPopup('<b>' + esc(f.name || f.category.replace(/_/g, ' ')) + '</b><br>' +
                        esc(f.category.replace(/_/g, ' ')) +
                        '<br><span style="color:#94a3b8">OpenStreetMap (mapped feature; completeness varies)</span>'));
                });
                rec.loaded = true;
                setState(rec, feats.length
                    ? feats.length + ' mapped feature(s) within ' + ((res.body.radius_m || 2000) / 1000) + ' km. ' +
                      esc(res.body.note || '')
                    : 'No mapped exposure features within this radius (OSM completeness varies).');
            }).catch(function () {
                if (rec.active) setState(rec, 'Exposure features request failed.');
            });
    }

    /* ---- Active fires: /api/fires (wildfire only) ---------------------- */
    function loadActiveFires(rec) {
        var c = currentCenter();
        fetchJSON(API + '/fires?lat=' + c.lat.toFixed(4) +
            '&lon=' + c.lon.toFixed(4) + '&days=5&radius_km=50').then(function (res) {
                if (!rec.active) return;
                var body = res.body || {};
                if (!res.ok || body.status === 'unavailable') {
                    rec.loaded = false;
                    var reason = (body.provenance && body.provenance.limitations) ||
                        (body.entries && body.entries[0] && body.entries[0].reason) ||
                        body.error || 'Active-fire evidence unavailable.';
                    var signup = body.entries && body.entries[0] && body.entries[0].signup;
                    setState(rec, esc(reason) +
                        (signup ? ' <a class="text-link" href="' + esc(signup) +
                            '" target="_blank" rel="noopener">Get a free key</a>' : ''));
                    return;
                }
                rec.leafletLayer.clearLayers();
                var count = 0;
                (body.entries || []).forEach(function (entry) {
                    if (entry.status !== 'ok') return;
                    (entry.detections || []).slice(0, 500).forEach(function (d) {
                        count++;
                        rec.leafletLayer.addLayer(L.circleMarker([d.lat, d.lon], {
                            radius: 5, color: '#dc2626', weight: 1.5,
                            fillColor: '#f59e0b', fillOpacity: 0.7
                        }).bindPopup('<b>ACTIVE-FIRE DETECTION</b><br>' +
                            esc(entry.sensor) + ' · ' + esc(d.acq_date) + ' ' + esc(d.acq_time_utc || '') + ' UTC' +
                            '<br>Confidence: ' + esc(d.confidence) + ' · FRP ' + esc(d.frp_mw) + ' MW' +
                            '<br><span style="color:#94a3b8">Hotspot detection — not a fire perimeter.</span>'));
                    });
                });
                rec.loaded = true;
                var note = count
                    ? count + ' detection(s) in the last 5 days, 50 km radius.'
                    : 'No active-fire detections in the last 5 days within 50 km.';
                if (body.disagreement) note += '<br>' + esc(body.disagreement);
                setState(rec, note);
            }).catch(function () {
                if (rec.active) setState(rec, 'Active-fire request failed.');
            });
    }

    /* ---- Population exposure: /api/population-exposure (WorldPop) ------ */
    function loadPopulationExposure(rec) {
        var c = currentCenter();
        fetchJSON(API + '/population-exposure?lat=' + c.lat.toFixed(4) +
            '&lon=' + c.lon.toFixed(4) + '&radius_km=3').then(function (res) {
                if (!rec.active) return;
                var body = res.body || {};
                if (!res.ok || body.error) {
                    rec.loaded = false;
                    setState(rec, 'Population exposure unavailable: ' +
                        esc(body.error || 'request failed') +
                        ' (WorldPop country raster may be downloading — retry shortly.)');
                    return;
                }
                rec.leafletLayer.clearLayers();
                var cells = ((body.population_grid || {}).cells) || [];
                var maxPop = 1;
                cells.forEach(function (cell) { maxPop = Math.max(maxPop, cell.population || 0); });
                cells.slice(0, 600).forEach(function (cell) {
                    var frac = (cell.population || 0) / maxPop;
                    rec.leafletLayer.addLayer(L.rectangle(
                        [[cell.south, cell.west], [cell.north, cell.east]],
                        {
                            color: 'rgba(0,0,0,0.1)', weight: 0.5,
                            fillColor: '#8b5cf6',
                            fillOpacity: 0.08 + 0.5 * Math.sqrt(frac)
                        }
                    ).bindPopup('<b>POPULATION CELL (ESTIMATE)</b><br>' +
                        'Estimated population: ' + esc(cell.population) +
                        '<br><span style="color:#94a3b8">WorldPop 100 m gridded estimate, reference year ' +
                        esc(body.reference_year || 'n/a') + ' — never an exact count.</span>'));
                });
                rec.loaded = true;
                var byClass = body.population_by_hazard_class || {};
                var parts = Object.keys(byClass).map(function (k) {
                    return esc(k) + ': ' + esc(byClass[k]);
                });
                setState(rec,
                    'Estimated population within 3 km: ' + esc(body.estimated_population) +
                    ' (WorldPop reference year ' + esc(body.reference_year || 'n/a') + ').' +
                    (parts.length ? '<br>By hazard class — ' + parts.join(' · ') : '') +
                    (body.overlay_note ? '<br>' + esc(body.overlay_note) : ''));
            }).catch(function () {
                if (rec.active) setState(rec, 'Population-exposure request failed.');
            });
    }

    /* ---- Smoke corridors: /api/smoke-scenario + /api/smoke ------------- */
    function loadSmokeCorridor(rec, observed) {
        var c = currentCenter();
        var path = observed ? '/smoke' : '/smoke-scenario';
        fetchJSON(API + path + '?lat=' + c.lat.toFixed(4) +
            '&lon=' + c.lon.toFixed(4) + '&hours=24').then(function (res) {
                if (!rec.active) return;
                var body = res.body || {};
                if (res.status === 503 || body.status === 'unavailable' || !res.ok || body.error) {
                    rec.loaded = false;
                    setState(rec, esc(body.reason || body.error ||
                        'Observed-fire smoke unavailable (NASA FIRMS key not configured).'));
                    return;
                }
                rec.leafletLayer.clearLayers();
                var corridors = [];
                if (body.transport && body.transport.corridor_polygon) {
                    corridors.push({
                        polygon: body.transport.corridor_polygon,
                        label: observed ? 'OBSERVED fire smoke corridor' : 'SCENARIO smoke corridor (hypothetical fire)'
                    });
                }
                (body.fires || []).forEach(function (f) {
                    var t = f.transport || {};
                    if (t.corridor_polygon) {
                        corridors.push({
                            polygon: t.corridor_polygon,
                            label: 'Smoke corridor — observed detection ' + esc(f.acq_date || '')
                        });
                    }
                    if (f.lat !== undefined && f.lon !== undefined) {
                        rec.leafletLayer.addLayer(L.circleMarker([f.lat, f.lon], {
                            radius: 6, color: '#dc2626', weight: 2,
                            fillColor: '#f59e0b', fillOpacity: 0.8
                        }).bindPopup('<b>OBSERVED FIRE (SMOKE SOURCE)</b><br>' +
                            esc(f.acq_date || '') + ' · FRP ' + esc(f.frp_mw || 'n/a') + ' MW'));
                    }
                });
                corridors.forEach(function (cor) {
                    rec.leafletLayer.addLayer(L.polygon(cor.polygon, {
                        color: observed ? '#b45309' : '#7c3aed', weight: 2,
                        dashArray: '6 4', fillColor: observed ? '#f59e0b' : '#a78bfa',
                        fillOpacity: 0.15
                    }).bindPopup('<b>' + cor.label.toUpperCase() + '</b><br>' +
                        esc((body.window ? body.window.from + ' → ' + body.window.to + ' UTC' : '')) +
                        '<br><span style="color:#94a3b8">Screening envelope from the real wind profile — ' +
                        'not a deterministic path. ' + esc(body.mode_label || '') + '</span>'));
                });
                rec.loaded = true;
                setState(rec, corridors.length
                    ? corridors.length + ' corridor(s); window ' +
                        esc(body.window ? body.window.from + ' → ' + body.window.to : 'n/a') +
                        ' UTC. ' + esc(body.mode_label || '')
                    : 'No corridor computable for this location/window (insufficient wind steps).');
            }).catch(function () {
                if (rec.active) setState(rec, 'Smoke-corridor request failed.');
            });
    }

    /* ---- Non-wildfire point layers: /api/v2/analyze -------------------- */
    function loadPointAnalysisLayer(rec) {
        var c = currentCenter();
        var hazardId = hazardDetail.id;
        var key = 'v2:' + hazardId + '@' + c.lat.toFixed(3) + ',' + c.lon.toFixed(3);
        var cached = analysisCache[key];
        var promise = cached
            ? Promise.resolve({ ok: true, status: 200, body: cached })
            : fetchJSON(API + '/v2/analyze?hazard=' + encodeURIComponent(hazardId) +
                '&lat=' + c.lat.toFixed(4) + '&lon=' + c.lon.toFixed(4));
        promise.then(function (res) {
            if (!rec.active) return;
            var body = res.body || {};
            if (res.status === 503 || body.status === 'unavailable' || body.status === 'key_required') {
                rec.loaded = false;
                setState(rec, esc(body.unavailable_reason || body.error || 'Analysis unavailable for this hazard.'));
                return;
            }
            if (!res.ok || body.error) {
                rec.loaded = false;
                setState(rec, 'Analysis unavailable: ' + esc(body.error || 'request failed'));
                return;
            }
            analysisCache[key] = body;
            rec.leafletLayer.clearLayers();
            var lvl = body.level || {};
            var marker = L.marker([c.lat, c.lon]).bindPopup(
                '<b>' + esc((hazardDetail.name || hazardId) + ' — point screening') + '</b><br>' +
                (lvl.label ? 'Level: <b>' + esc(lvl.label) + '</b>' +
                    (lvl.score != null ? ' (' + esc(lvl.score) + (lvl.score_max ? '/' + esc(lvl.score_max) : '') + ')' : '') + '<br>' : '') +
                esc(body.summary || '') +
                '<br><span style="color:#94a3b8">Point screening at the map centre — not a spatial layer. ' +
                (lvl.basis ? esc(lvl.basis) + ' ' : '') +
                '</span><br><a href="intelligence.html#' + esc(hazardId) + '">Full breakdown on the Intelligence page →</a>');
            rec.leafletLayer.addLayer(marker);
            marker.openPopup();
            rec.loaded = true;
            setState(rec, 'Point screening shown at the map centre (' + c.lat.toFixed(3) + ', ' +
                c.lon.toFixed(3) + '). This layer is an analysis summary, not a spatial grid.');
        }).catch(function () {
            if (rec.active) setState(rec, 'Analysis request failed.');
        });
    }

    // ------------------------------------------------------------------
    // Location search
    // ------------------------------------------------------------------

    function goToLocation(query) {
        var status = el('locStatus');
        status.textContent = 'Resolving location…';
        el('locBtn').disabled = true;
        HS.resolveLocation(query).then(function (res) {
            el('locBtn').disabled = false;
            if (!res.ok) {
                status.textContent = res.error || 'Location could not be resolved.';
                return;
            }
            map.setView([res.lat, res.lon], 11);
            if (locationMarker) map.removeLayer(locationMarker);
            locationMarker = L.marker([res.lat, res.lon]).addTo(map)
                .bindPopup('<b>' + esc(res.name) + '</b>').openPopup();
            HS.rememberLocation({ name: res.name, lat: res.lat, lon: res.lon });
            status.innerHTML = 'Location: <b>' + esc(res.name) + '</b> (' +
                res.lat.toFixed(4) + ', ' + res.lon.toFixed(4) + ').';
            // Cache the returned analysis for the NDMI layer (same point).
            if (res.analysis && !res.analysis.error) {
                analysisCache['v1@' + res.lat.toFixed(3) + ',' + res.lon.toFixed(3)] = res.analysis;
            }
            refreshActiveLayers();
        });
    }

    // ------------------------------------------------------------------
    // Init
    // ------------------------------------------------------------------

    function init() {
        initMap();

        el('locBtn').addEventListener('click', function () {
            var q = el('locInput').value.trim();
            if (q) goToLocation(q);
        });
        el('locInput').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                var q = el('locInput').value.trim();
                if (q) goToLocation(q);
            }
        });
        el('yearSelect').addEventListener('change', function () {
            layers.forEach(function (rec) {
                if (rec.active && rec.spec.layer_id === 'wildfire.events') loadLayer(rec, true);
            });
        });
        el('evidenceFilter').addEventListener('change', applyEvidenceFilter);

        // URL params: ?location=… · ?hazard=…
        var params = new URLSearchParams(location.search);
        loadHazards(params.get('hazard') || undefined);
        var q = params.get('location');
        if (q) {
            el('locInput').value = q;
            goToLocation(q);
        }
    }

    init();
})();
