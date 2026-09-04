/* Talaix — the Map (map.html).
 *
 * The map is the core product: a compact Leaflet canvas (reduced height,
 * not full-viewport) next to a simplified control sidebar, with a
 * collapsible "Advanced analysis & tools" strip below for deeper work
 * (multi-hazard snapshot, site comparison, share/export, plain-language
 * glossary). Hazard selector from GET /api/v2/hazards (availability
 * honoured, retried on failure), year selector derived from each hazard's
 * temporal_coverage (never hardcoded), and a lazy layer panel with
 * collapsible groups HAZARD / ENVIRONMENT / EVIDENCE / EXPOSURE. Every
 * layer shows legend, source, resolution, status, temporal class and
 * provenance; every fetch renders honest loading / empty / unavailable /
 * key_required / error states. No invented data anywhere.
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
    var targetBox = null;              // target marker of the selected place
    var moveTimer = null;
    var reverseTimer = null;
    var reverseCache = {};             // "lat,lon" → place name (client cache)
    var lastCentreName = null;
    var centreStatusAutoSet = false;   // true when locStatus shows the auto-updated centre place
    var centreChip = null;
    var cursorChip = null;
    var initialYear = null;            // ?year= URL param, applied once options exist

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

    // Free base-map sources (no API key); the user picks the backdrop.
    // Every entry carries its required attribution.
    function baseMaps() {
        var osmAttr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
        return {
            'OpenStreetMap': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 18,
                attribution: osmAttr
            }),
            'Topographic (OpenTopoMap)': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                maxZoom: 17,
                attribution: osmAttr + ' &middot; style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
            }),
            'Light (CARTO)': L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 20, subdomains: 'abcd',
                attribution: osmAttr + ' &middot; &copy; <a href="https://carto.com/attributions">CARTO</a>'
            }),
            'Dark (CARTO)': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 20, subdomains: 'abcd',
                attribution: osmAttr + ' &middot; &copy; <a href="https://carto.com/attributions">CARTO</a>'
            }),
            'Satellite (Esri)': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                maxZoom: 19,
                attribution: 'Imagery &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
            })
        };
    }

    // Target reticle fixed at the map centre: it frames the place being
    // viewed; the chip beneath it shows the place name + coordinates,
    // updated live while the map moves.
    function initCentreTarget() {
        var container = map.getContainer();
        var reticle = L.DomUtil.create('div', 'map-reticle', container);
        reticle.innerHTML =
            '<div class="map-reticle-corner tl"></div>' +
            '<div class="map-reticle-corner tr"></div>' +
            '<div class="map-reticle-corner bl"></div>' +
            '<div class="map-reticle-corner br"></div>' +
            '<div class="map-reticle-dot"></div>';
        centreChip = L.DomUtil.create('div', 'map-centre-chip', container);
        L.DomEvent.disableClickPropagation(reticle);
        L.DomEvent.disableClickPropagation(centreChip);

        // Cursor readout (bottom-right): the exact number on the ground.
        cursorChip = L.DomUtil.create('div', 'map-cursor-coords hidden', container);
        L.DomEvent.disableClickPropagation(cursorChip);
        map.on('mousemove', function (e) {
            cursorChip.classList.remove('hidden');
            cursorChip.textContent = e.latlng.lat.toFixed(5) + ', ' + e.latlng.lng.toFixed(5);
        });
        map.on('mouseout', function () { cursorChip.classList.add('hidden'); });

        map.on('move', updateCentreChip);
        map.on('moveend', function () {
            updateCentreChip();
            if (reverseTimer) clearTimeout(reverseTimer);
            reverseTimer = setTimeout(updateCentrePlace, 600);
        });
        updateCentreChip();
        updateCentrePlace();
    }

    function updateCentreChip() {
        var c = map.getCenter();
        var name = lastCentreName || 'Resolving place…';
        centreChip.innerHTML =
            '<div class="mcc-name">' + esc(name) + '</div>' +
            '<div class="mcc-coords">' + c.lat.toFixed(4) + ', ' + c.lng.toFixed(4) + '</div>';
        renderActOnPoint(c.lat, c.lng);
    }

    /* Sidebar panel: deep-link from the map centre into the product tools. */
    function renderActOnPoint(lat, lon) {
        var id = 'actOnPointPanel';
        var panel = el(id);
        if (!panel) {
            panel = document.createElement('div');
            panel.id = id;
            panel.className = 'map-sidebar-section';
            var layersHeading = el('layerPanel').previousElementSibling;
            if (layersHeading && layersHeading.tagName === 'H2') {
                layersHeading.parentNode.insertBefore(panel, layersHeading);
            } else {
                el('mapSidebar').appendChild(panel);
            }
        }
        var coord = lat.toFixed(4) + ',' + lon.toFixed(4);
        panel.innerHTML =
            '<h2>Act on this point</h2>' +
            '<p class="muted small" style="margin:0 0 6px 0;">' + esc(coord) + '</p>' +
            '<div class="layer-state" style="padding-left:0;">' +
            '<a class="text-link" href="green-finance.html?location=' + encodeURIComponent(coord) + '">Green Finance check</a> · ' +
            '<a class="text-link" href="insurance.html?location=' + encodeURIComponent(coord) + '">Insurance profile</a> · ' +
            '<a class="text-link" href="forensics.html?location=' + encodeURIComponent(coord) + '">Forensic case</a> · ' +
            '<a class="text-link" href="press.html?location=' + encodeURIComponent(coord) + '">Press pack</a> · ' +
            '<a class="text-link" href="sustainability.html">Sustainability report</a>' +
            '</div>';
    }

    /* Reverse-geocode the map centre (debounced after moveend; cached
     * client-side per rounded coordinate). Honest fallback: coordinates.
     * The resolved place name is reflected into the Location input and
     * status unless the user has explicitly searched for a location. */
    function reflectCentrePlace(name, lat, lon) {
        var input = el('locInput');
        if (document.activeElement !== input) {
            input.value = name;
        }
        var status = el('locStatus');
        if (centreStatusAutoSet || !status.textContent) {
            status.textContent = 'Map centre: ' + name + ' (' + lat.toFixed(4) + ', ' + lon.toFixed(4) + ')';
            centreStatusAutoSet = true;
        }
    }

    function updateCentrePlace() {
        var c = map.getCenter();
        var key = c.lat.toFixed(3) + ',' + c.lng.toFixed(3);
        if (reverseCache[key] !== undefined) {
            lastCentreName = reverseCache[key];
            reflectCentrePlace(lastCentreName, c.lat, c.lng);
            updateCentreChip();
            return;
        }
        fetchJSON(API + '/reverse?lat=' + c.lat.toFixed(4) + '&lon=' + c.lng.toFixed(4))
            .then(function (res) {
                var name = (res.ok && res.body.location && res.body.location.name) ||
                    (c.lat.toFixed(4) + ', ' + c.lng.toFixed(4));
                reverseCache[key] = name;
                lastCentreName = name;
                reflectCentrePlace(name, c.lat, c.lng);
                updateCentreChip();
            })
            .catch(function () {
                lastCentreName = c.lat.toFixed(4) + ', ' + c.lng.toFixed(4);
                reflectCentrePlace(lastCentreName, c.lat, c.lng);
                updateCentreChip();
            });
    }

    function initMap() {
        map = L.map('map').setView([50.45, 7.0], 7);
        if (window.HS && HS.track) HS.track('map_opened');
        if (window.HSConvert) HSConvert.show({
            mount: 'mapSidebar', context: 'map_monitor',
            text: 'See a place worth watching? Create a monitoring alert with a free account.',
            cta: 'Create a monitoring alert', href: 'account.html#sms'
        });
        if (window.HSConvert) HSConvert.evaluate('mapSidebar');
        var bases = baseMaps();
        bases['OpenStreetMap'].addTo(map);
        L.control.layers(bases, null, { position: 'topright' }).addTo(map);
        initCentreTarget();

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
                rec.spec.layer_id === 'cyclone.active' ||
                rec.spec.layer_id === 'platform.trade_ports' ||
                rec.spec.layer_id === 'platform.exposure_features' ||
                rec.spec.layer_id === 'platform.active_fires') {
                loadLayer(rec, true);
            }
        });
    }

    // ------------------------------------------------------------------
    // Hazard + year selectors
    // ------------------------------------------------------------------

    function loadHazards(preselect, attempt) {
        attempt = attempt || 1;
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) {
                hazardRegistryFailed(preselect, attempt,
                    'Hazard registry unavailable — layers cannot be built.');
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
            hazardRegistryFailed(preselect, attempt, 'Hazard registry could not be reached.');
        });
    }

    /* The registry is the root of every layer — retry automatically with
     * backoff, then offer a manual Retry instead of leaving a dead page. */
    function hazardRegistryFailed(preselect, attempt, message) {
        var status = el('hazardStatus');
        if (attempt < 3) {
            status.textContent = message + ' Retrying…';
            setTimeout(function () { loadHazards(preselect, attempt + 1); }, 1500 * attempt);
            return;
        }
        status.textContent = '';
        var span = document.createElement('span');
        span.textContent = message + ' ';
        status.appendChild(span);
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-quiet adv-btn';
        btn.style.padding = '4px 10px';
        btn.textContent = 'Retry';
        btn.addEventListener('click', function () { loadHazards(preselect, 1); });
        status.appendChild(btn);
        el('layerPanel').innerHTML =
            '<div class="layer-state" style="padding-left:0;">Layers cannot be built until the hazard registry responds.</div>';
    }

    function selectHazard(hazardId) {
        var h = hazards.filter(function (x) { return x.id === hazardId; })[0];
        el('hazardStatus').textContent = h && h.tagline ? h.tagline : '';
        teardownLayers();
        buildYearSelector(h ? h.temporal_coverage : {});
        fetchJSON(API + '/v2/hazards/' + encodeURIComponent(hazardId)).then(function (res) {
            if (!res.ok) {
                layerDefsFailed(hazardId,
                    'Layer definitions unavailable: ' + (res.body.error || 'unknown hazard'));
                return;
            }
            hazardDetail = res.body;
            buildLayerPanel(hazardDetail);
        }).catch(function () {
            layerDefsFailed(hazardId, 'Layer definitions could not be reached.');
        });
    }

    /* Layer-definition fetch failed: show the honest state with a manual
     * retry instead of a dead panel. */
    function layerDefsFailed(hazardId, message) {
        var panel = el('layerPanel');
        panel.innerHTML = '';
        var notice = document.createElement('div');
        notice.className = 'notice notice-error';
        notice.style.marginBottom = '0';
        notice.textContent = message + ' ';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-quiet adv-btn';
        btn.style.padding = '4px 10px';
        btn.textContent = 'Retry';
        btn.addEventListener('click', function () { selectHazard(hazardId); });
        notice.appendChild(btn);
        panel.appendChild(notice);
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
        // A ?year= deep-link applies once this hazard's options exist.
        if (initialYear) {
            var ys = el('yearSelect');
            for (var i = 0; i < ys.options.length; i++) {
                if (ys.options[i].value === initialYear) {
                    ys.value = initialYear;
                    break;
                }
            }
            initialYear = null;
        }
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
        if (targetBox) { /* keep the target marker across hazards */ }
        renderEvidenceSummary();
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
        }, {
            layer_id: 'platform.trade_ports',
            label: 'Trade infrastructure — ports & harbours (OSM)',
            group: 'EXPOSURE',
            kind: 'points',
            legend: { 'Harbour / port': '#0e7490', 'Port facility': '#155e75' },
            source: 'OpenStreetMap (Overpass API)',
            url: 'https://www.openstreetmap.org/',
            resolution: 'Mapped port/harbour features within 50 km of the map centre',
            status: 'available',
            temporal: 'OBSERVED',
            provenance: { note: 'The mapped backbone of international trade movement; a lower bound (OSM completeness varies). Live vessel movements (AIS) are not wired — they require a shipping-data provider.' }
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

        order.forEach(function (g, gi) {
            var hasDefaultOn = groups[g].some(function (s) { return s.default_on; });
            var open = hasDefaultOn || gi === 0;

            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'layer-group-toggle';
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            toggle.innerHTML = '<span class="group-arrow" aria-hidden="true">▸</span>' +
                '<span>' + esc(g) + '</span>' +
                '<span class="group-count">' + groups[g].length + '</span>';

            var body = document.createElement('div');
            body.className = 'layer-group-body';
            body.hidden = !open;
            groups[g].forEach(function (spec) { body.appendChild(layerRow(spec)); });

            toggle.addEventListener('click', function () {
                var isOpen = toggle.getAttribute('aria-expanded') === 'true';
                toggle.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
                body.hidden = isOpen;
            });

            panel.appendChild(toggle);
            panel.appendChild(body);
        });

        // Default-on layers (per each hazard's layer spec; the fire-danger
        // grid is opt-in — its spec sets default_on: false).
        layers.forEach(function (rec) {
            if (rec.spec.default_on && !rec.checkbox.disabled) {
                rec.checkbox.checked = true;
                enableLayer(rec);
            }
        });
        renderEvidenceSummary();
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

        // Evidence class at a glance (observed / modelled / scenario …) so
        // the panel never hides what kind of evidence a layer is.
        var temporalChip = document.createElement('span');
        temporalChip.innerHTML = chip(spec.temporal || 'OBSERVED');

        var infoBtn = document.createElement('button');
        infoBtn.type = 'button';
        infoBtn.className = 'layer-info-btn';
        infoBtn.textContent = 'info';
        infoBtn.setAttribute('aria-label', 'Layer details: ' + spec.label);

        row.appendChild(cb);
        row.appendChild(label);
        row.appendChild(temporalChip);
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
        renderEvidenceSummary();
    }

    // ------------------------------------------------------------------
    // Layer enable / load
    // ------------------------------------------------------------------

    function enableLayer(rec) {
        rec.active = true;
        if (!rec.leafletLayer) rec.leafletLayer = L.layerGroup();
        rec.leafletLayer.addTo(map);
        var p = loadLayer(rec, false);
        if (p && p.then) p.then(rebuildLegend);
        renderEvidenceSummary();
    }

    function disableLayer(rec) {
        rec.active = false;
        if (rec.leafletLayer) map.removeLayer(rec.leafletLayer);
        setState(rec, '');
        rebuildLegend();
        renderEvidenceSummary();
    }

    /* Compact evidence readout in the advanced-strip toggle bar: how many
     * active layers are observed / modelled / scenario, so the evidence
     * mix is visible without opening anything. */
    function renderEvidenceSummary() {
        var box = el('mapAdvEvidence');
        if (!box) return;
        var counts = {};
        layers.forEach(function (rec) {
            if (!rec.active) return;
            var t = rec.spec.temporal || 'OBSERVED';
            counts[t] = (counts[t] || 0) + 1;
        });
        var parts = Object.keys(counts).map(function (t) {
            return counts[t] + ' ' + t.toLowerCase().replace('_', ' ');
        });
        box.textContent = parts.length
            ? 'Active evidence: ' + parts.join(' · ') + ' — screening only'
            : 'No active layers';
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
        if (id === 'cyclone.active') return loadCycloneLayer(rec);
        if (id === 'platform.trade_ports') return loadTradePorts(rec);
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
                    l.bindPopup('<b>RISK CELL</b><br>Talaix: ' +
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
            rebuildLegend();
        }).catch(function () {
            if (rec.active) setState(rec, 'Fire-danger grid request failed.');
        });
    }

    /* On-map legend built from every active, loaded layer that declares a
     * legend — one block per layer, rebuilt on enable/disable/load. */
    function rebuildLegend() {
        if (legendControl) { legendControl.remove(); legendControl = null; }
        var withLegend = layers.filter(function (rec) {
            return rec.active && rec.loaded && rec.spec.legend;
        });
        if (!withLegend.length) return;
        legendControl = L.control({ position: 'bottomright' });
        legendControl.onAdd = function () {
            var div = L.DomUtil.create('div', 'map-legend');
            div.innerHTML = withLegend.map(function (rec) {
                var isGrid = rec.spec.layer_id === 'wildfire.danger_grid';
                var title = isGrid ? 'Fire danger (FWI-based)'
                    : String(rec.spec.label).split('(')[0].trim();
                return '<div class="legend-block">' +
                    '<div class="legend-title">' + esc(title) + '</div>' +
                    Object.keys(rec.spec.legend).map(function (k) {
                        return '<div class="swatch"><i style="background:' +
                            esc(rec.spec.legend[k]) + '"></i>' + esc(k) + '</div>';
                    }).join('') +
                    (isGrid ? '<div class="legend-note">Composite indicator — not a probability of fire.</div>' : '') +
                    '</div>';
            }).join('');
            return div;
        };
        legendControl.addTo(map);
    }

    /* ---- Active tropical cyclones: /api/v2/events?hazard=cyclone ------- */
    function loadCycloneLayer(rec) {
        var c = currentCenter();
        var url = API + '/v2/events?hazard=cyclone&lat=' + c.lat.toFixed(4) +
            '&lon=' + c.lon.toFixed(4) + '&radius_km=3000';
        fetchJSON(url).then(function (res) {
            if (!rec.active) return;
            var body = res.body || {};
            if (!res.ok || body.status !== 'ok') {
                rec.loaded = false;
                setState(rec, esc(body.reason || 'Cyclone monitoring unavailable.'));
                return;
            }
            rec.leafletLayer.clearLayers();
            var colors = { red: '#ef4444', orange: '#f97316', green: '#22c55e' };
            (body.events || []).forEach(function (ev) {
                var color = colors[String(ev.alert_level || '').toLowerCase()] || '#eab308';
                L.circleMarker([ev.lat, ev.lon], {
                    radius: 9, color: color, weight: 3, fillColor: color, fillOpacity: 0.25
                }).bindPopup(
                    '<div class="loc-pop">' +
                    '<div class="loc-pop-title">' + esc(ev.name) + '</div>' +
                    '<table class="loc-pop-table">' +
                    '<tr><th>Alert level</th><td>' + esc(ev.alert_level || 'n/a') + '</td></tr>' +
                    '<tr><th>Window</th><td>' + esc(String(ev.from_date || '').slice(0, 10)) +
                    ' &rarr; ' + esc(String(ev.to_date || '').slice(0, 10)) + '</td></tr>' +
                    '<tr><th>Affected</th><td>' + esc(ev.countries || '—') + '</td></tr>' +
                    '<tr><th>Distance</th><td>' + esc(String(Math.round(ev.distance_km))) + ' km</td></tr>' +
                    '<tr><th>Source</th><td>' + esc(ev.warning_centre || 'GDACS') + ' via GDACS</td></tr>' +
                    '</table>' +
                    (ev.report_url
                        ? '<a class="text-link" href="' + esc(ev.report_url) +
                          '" target="_blank" rel="noopener">Official GDACS report &rarr;</a><br>'
                        : '') +
                    '<span style="color:#94a3b8">Monitoring position — not a forecast.</span>' +
                    '</div>'
                ).addTo(rec.leafletLayer);
            });
            rec.loaded = true;
            var n = (body.events || []).length;
            setState(rec, n
                ? n + ' active/ongoing tropical cyclone(s) within 3,000 km — GDACS monitoring (cached 1 h).'
                : 'No active tropical cyclone within 3,000 km — GDACS monitoring (cached 1 h).');
        }).catch(function () {
            if (rec.active) setState(rec, 'Cyclone monitoring request failed.');
        });
    }

    /* ---- Trade infrastructure: /api/trade-infrastructure (OSM) --------- */
    function loadTradePorts(rec) {
        var c = currentCenter();
        var url = API + '/trade-infrastructure?lat=' + c.lat.toFixed(4) +
            '&lon=' + c.lon.toFixed(4) + '&radius_m=50000';
        fetchJSON(url).then(function (res) {
            if (!rec.active) return;
            if (!res.ok || res.body.error) {
                rec.loaded = false;
                setState(rec, 'Trade infrastructure unavailable: ' +
                    esc((res.body && res.body.error) || 'request failed'));
                return;
            }
            rec.leafletLayer.clearLayers();
            var colors = { harbour: '#0e7490', port_facility: '#155e75' };
            (res.body.features || []).forEach(function (f) {
                var color = colors[f.kind] || '#0e7490';
                L.circleMarker([f.lat, f.lon], {
                    radius: 6, color: color, weight: 2, fillColor: color, fillOpacity: 0.35
                }).bindPopup(
                    '<div class="loc-pop">' +
                    '<div class="loc-pop-title">' +
                    esc(f.name || (f.kind === 'port_facility' ? 'Port facility' : 'Harbour / port')) +
                    '</div>' +
                    '<table class="loc-pop-table">' +
                    '<tr><th>Type</th><td>' +
                    (f.kind === 'port_facility' ? 'Port facility' : 'Harbour / port') + '</td></tr>' +
                    '<tr><th>Coordinates</th><td>' + f.lat.toFixed(4) + ', ' + f.lon.toFixed(4) +
                    '</td></tr>' +
                    '<tr><th>Source</th><td>OpenStreetMap (Overpass)</td></tr>' +
                    '</table>' +
                    '<span style="color:#94a3b8">Mapped trade infrastructure — a lower bound, ' +
                    'not a port census. Live vessel tracking (AIS) is not wired.</span>' +
                    '</div>'
                ).addTo(rec.leafletLayer);
            });
            rec.loaded = true;
            setState(rec, (res.body.features || []).length +
                ' mapped port/harbour feature(s) within 50 km (OSM, cached).');
        }).catch(function () {
            if (rec.active) setState(rec, 'Trade infrastructure request failed.');
        });
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
    // Advanced strip (snapshot / compare / share & export)
    // ------------------------------------------------------------------

    function truncate(s, n) {
        s = String(s || '');
        return s.length > n ? s.slice(0, n - 1) + '…' : s;
    }

    /* Multi-hazard snapshot: screen the map centre against every available
     * hazard so the user can decide which layers are worth switching on. */
    function runSnapshot() {
        var btn = el('advSnapshotBtn');
        var out = el('advSnapshotResult');
        var c = currentCenter();
        var available = hazards.filter(function (h) { return h.analysis && h.analysis.available; });
        if (!available.length) {
            out.innerHTML = '<div class="notice notice-warn" style="margin-bottom:0;">' +
                'The hazard registry is not loaded — no snapshot without it. Retry the registry from the sidebar status.</div>';
            return;
        }
        btn.disabled = true;
        out.innerHTML = '<div class="layer-state" style="padding-left:0;">Screening ' +
            available.length + ' hazard(s) at ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) + '…</div>';
        var jobs = available.map(function (h) {
            return fetchJSON(API + '/v2/analyze?hazard=' + encodeURIComponent(h.id) +
                '&lat=' + c.lat.toFixed(4) + '&lon=' + c.lon.toFixed(4))
                .then(function (res) { return { h: h, res: res }; })
                .catch(function () { return { h: h, res: null }; });
        });
        Promise.all(jobs).then(function (rows) {
            btn.disabled = false;
            out.innerHTML = rows.map(function (row) {
                return snapshotRow(row.h, row.res);
            }).join('') +
                '<p class="muted small" style="margin:8px 0 0;">Point screening at the map centre — ' +
                'not a spatial assessment. “Layers →” loads that hazard’s layers in the sidebar.</p>';
            if (window.HS && HS.track) HS.track('map_snapshot', { hazards: available.length });
        });
    }

    function snapshotRow(h, res) {
        var name = '<span class="snap-name">' + esc(h.name) + '</span>';
        var link = '<a class="text-link snap-link" href="map.html?hazard=' + encodeURIComponent(h.id) +
            '" data-hazard="' + esc(h.id) + '">Layers →</a>';
        var body, status, detail;
        if (!res) {
            status = chip('error', 'request failed');
            detail = 'The analysis service could not be reached.';
        } else {
            body = res.body || {};
            if (res.status === 503 || body.status === 'unavailable' || body.status === 'key_required') {
                status = chip(body.status === 'key_required' ? 'key_required' : 'unavailable');
                detail = esc(body.unavailable_reason || body.error || 'Unavailable for this hazard.');
            } else if (!res.ok || body.error) {
                status = chip('error');
                detail = esc(body.error || 'Analysis failed.');
            } else {
                var lvl = body.level || {};
                var label = lvl.label
                    ? '<b>' + esc(lvl.label) + '</b>' +
                      (lvl.score != null ? ' (' + esc(lvl.score) + (lvl.score_max ? '/' + esc(lvl.score_max) : '') + ')' : '')
                    : 'n/a';
                status = label;
                detail = esc(truncate(body.summary || '—', 150));
            }
        }
        return '<div class="adv-snap-row">' + name + status +
            '<span class="snap-summary">' + detail + '</span>' + link + '</div>';
    }

    /* Site comparison: the selected hazard at the map centre vs a second
     * site — a quick screening before a full insurance profile. */
    function runCompare() {
        var q = el('advCompareInput').value.trim();
        var out = el('advCompareResult');
        if (!q) {
            out.innerHTML = '<div class="notice notice-warn" style="margin-bottom:0;">Enter a second site to compare with the map centre.</div>';
            return;
        }
        if (!hazardDetail || !hazardDetail.id) {
            out.innerHTML = '<div class="notice notice-warn" style="margin-bottom:0;">Hazard definitions are not loaded yet — retry shortly.</div>';
            return;
        }
        var btn = el('advCompareBtn');
        var hazardId = hazardDetail.id;
        var c = currentCenter();
        btn.disabled = true;
        out.innerHTML = '<div class="layer-state" style="padding-left:0;">Resolving ' + esc(q) + '…</div>';
        HS.resolveLocation(q).then(function (loc) {
            if (!loc.ok) {
                btn.disabled = false;
                out.innerHTML = '<div class="notice notice-error" style="margin-bottom:0;">' +
                    esc(loc.error || 'Location could not be resolved.') + '</div>';
                return;
            }
            out.innerHTML = '<div class="layer-state" style="padding-left:0;">Comparing ' +
                esc(hazardDetail.name || hazardId) + ' at both sites…</div>';
            var analyzeAt = function (lat, lon) {
                return fetchJSON(API + '/v2/analyze?hazard=' + encodeURIComponent(hazardId) +
                    '&lat=' + lat.toFixed(4) + '&lon=' + lon.toFixed(4))
                    .catch(function () { return null; });
            };
            Promise.all([analyzeAt(c.lat, c.lon), analyzeAt(loc.lat, loc.lon)]).then(function (results) {
                btn.disabled = false;
                out.innerHTML = '<table class="adv-compare-table"><thead><tr>' +
                    '<th>Site</th><th>Level</th><th>Summary</th></tr></thead><tbody>' +
                    compareRow('Map centre (' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) + ')', results[0]) +
                    compareRow(esc(loc.name), results[1]) +
                    '</tbody></table>' +
                    '<p class="muted small" style="margin:8px 0 0;">Point screening for ' +
                    esc(hazardDetail.name || hazardId) +
                    ' — verify with a full profile before any underwriting decision.</p>';
                if (window.HS && HS.track) HS.track('map_compare', { hazard: hazardId });
            });
        }).catch(function () {
            btn.disabled = false;
            out.innerHTML = '<div class="notice notice-error" style="margin-bottom:0;">The analysis service could not be reached.</div>';
        });
    }

    function compareRow(site, res) {
        if (!res) {
            return '<tr><td>' + site + '</td><td colspan="2">' + chip('error', 'request failed') + '</td></tr>';
        }
        var body = res.body || {};
        if (res.status === 503 || body.status === 'unavailable' || body.status === 'key_required') {
            return '<tr><td>' + site + '</td><td colspan="2">' +
                chip(body.status === 'key_required' ? 'key_required' : 'unavailable') + ' ' +
                esc(body.unavailable_reason || body.error || 'Unavailable for this hazard.') + '</td></tr>';
        }
        if (!res.ok || body.error) {
            return '<tr><td>' + site + '</td><td colspan="2">' + chip('error') + ' ' +
                esc(body.error || 'Analysis failed.') + '</td></tr>';
        }
        var lvl = body.level || {};
        var label = lvl.label
            ? '<b>' + esc(lvl.label) + '</b>' +
              (lvl.score != null ? ' (' + esc(lvl.score) + (lvl.score_max ? '/' + esc(lvl.score_max) : '') + ')' : '')
            : 'n/a';
        return '<tr><td>' + site + '</td><td>' + label + '</td><td>' +
            esc(truncate(body.summary || '—', 180)) + '</td></tr>';
    }

    /* Shareable view URL: location + hazard + year restore the current view. */
    function viewUrl() {
        var c = currentCenter();
        var params = new URLSearchParams();
        params.set('location', c.lat.toFixed(4) + ',' + c.lon.toFixed(4));
        if (hazardDetail && hazardDetail.id) params.set('hazard', hazardDetail.id);
        var y = el('yearSelect').value;
        if (y && y !== 'current') params.set('year', y);
        return location.origin + location.pathname + '?' + params.toString();
    }

    function copyText(text, okMsg) {
        var out = el('advShareStatus');
        var done = function () {
            out.innerHTML = '<div class="notice notice-info" style="margin-bottom:0;">' + esc(okMsg) + '</div>';
        };
        var fail = function () {
            out.innerHTML = '<div class="notice notice-warn" style="margin-bottom:0;">' +
                'Copy failed — copy it manually:<br><code>' + esc(text) + '</code></div>';
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, fail);
            return;
        }
        var ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try {
            if (document.execCommand('copy')) done(); else fail();
        } catch (e) { fail(); }
        document.body.removeChild(ta);
    }

    /* GeoJSON export of the active, loaded layers only — each feature keeps
     * the layer id, temporal class and source it came from. */
    function exportGeoJSON() {
        var out = el('advShareStatus');
        var feats = [];
        layers.forEach(function (rec) {
            if (!rec.active || !rec.loaded || !rec.leafletLayer) return;
            var gj;
            try { gj = rec.leafletLayer.toGeoJSON(); } catch (e) { return; }
            var list = gj.type === 'FeatureCollection' ? gj.features : [gj];
            list.forEach(function (f) {
                f.properties = f.properties || {};
                f.properties.talaix_layer = rec.spec.layer_id;
                f.properties.talaix_temporal = rec.spec.temporal || 'OBSERVED';
                f.properties.talaix_source = rec.spec.source || '';
                feats.push(f);
            });
        });
        if (!feats.length) {
            out.innerHTML = '<div class="notice notice-warn" style="margin-bottom:0;">' +
                'Nothing to export — enable at least one spatial layer first. ' +
                'Declared layers without a wired spatial product export nothing.</div>';
            return;
        }
        var fc = {
            type: 'FeatureCollection',
            generator: 'Talaix map — open-source screening evidence, verify before use',
            exported_at: new Date().toISOString(),
            features: feats
        };
        var blob = new Blob([JSON.stringify(fc, null, 2)], { type: 'application/geo+json' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'talaix-map-' + (hazardDetail ? hazardDetail.id : 'layers') +
            '-' + new Date().toISOString().slice(0, 10) + '.geojson';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
        out.innerHTML = '<div class="notice notice-info" style="margin-bottom:0;">Exported ' +
            feats.length + ' feature(s) from the active layers.</div>';
        if (window.HS && HS.track) HS.track('map_export_geojson', { features: feats.length });
    }

    function initAdvancedStrip() {
        var toggle = el('mapAdvToggle');
        var body = el('mapAdvBody');
        toggle.addEventListener('click', function () {
            var isOpen = toggle.getAttribute('aria-expanded') === 'true';
            toggle.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
            body.hidden = isOpen;
        });

        el('advSnapshotBtn').addEventListener('click', runSnapshot);
        el('advSnapshotResult').addEventListener('click', function (e) {
            var a = e.target.closest ? e.target.closest('[data-hazard]') : null;
            if (!a) return;
            e.preventDefault();
            var id = a.getAttribute('data-hazard');
            if (hazards.some(function (h) { return h.id === id && h.analysis.available; })) {
                el('hazardSelect').value = id;
                selectHazard(id);
            }
        });
        el('advCompareBtn').addEventListener('click', runCompare);
        el('advCompareInput').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') runCompare();
        });
        el('advShareLinkBtn').addEventListener('click', function () {
            copyText(viewUrl(), 'View link copied — it restores location, hazard, year and mode.');
        });
        el('advCopyCoordsBtn').addEventListener('click', function () {
            var c = currentCenter();
            copyText(c.lat.toFixed(5) + ', ' + c.lon.toFixed(5), 'Map-centre coordinates copied.');
        });
        el('advExportBtn').addEventListener('click', exportGeoJSON);
        renderEvidenceSummary();
    }

    // ------------------------------------------------------------------
    // Location search
    // ------------------------------------------------------------------

    /* Target-style marker for the selected place: corner-bracket frame +
     * centre dot (a "gun target" on the exact spot); the popup opens beneath it. */
    function targetIcon() {
        return L.divIcon({
            className: 'target-marker',
            html: '<div class="target-marker-corner tl"></div>' +
                  '<div class="target-marker-corner tr"></div>' +
                  '<div class="target-marker-corner bl"></div>' +
                  '<div class="target-marker-corner br"></div>' +
                  '<div class="target-marker-dot"></div>',
            iconSize: [40, 40],
            iconAnchor: [20, 20],
            popupAnchor: [0, 26]
        });
    }

    /* Organized popup: title + labelled rows instead of a bare name. */
    function locationPopupHTML(res) {
        return '<div class="loc-pop">' +
            '<div class="loc-pop-title">' + esc(res.name) + '</div>' +
            '<table class="loc-pop-table">' +
            '<tr><th>Latitude</th><td>' + res.lat.toFixed(5) + '</td></tr>' +
            '<tr><th>Longitude</th><td>' + res.lon.toFixed(5) + '</td></tr>' +
            '<tr><th>Source</th><td>' + esc(res.source || 'Nominatim (OpenStreetMap)') + '</td></tr>' +
            '</table>' +
            '<a class="text-link" href="intelligence.html?location=' +
            encodeURIComponent(res.lat.toFixed(5) + ',' + res.lon.toFixed(5)) +
            '">Analyze this place &rarr;</a></div>';
    }

    function goToLocation(query) {
        var status = el('locStatus');
        status.textContent = 'Resolving location…';
        centreStatusAutoSet = false;
        el('locBtn').disabled = true;
        HS.resolveLocation(query).then(function (res) {
            el('locBtn').disabled = false;
            if (!res.ok) {
                status.textContent = res.error || 'Location could not be resolved.';
                return;
            }
            map.setView([res.lat, res.lon], 11);
            if (targetBox) map.removeLayer(targetBox);
            targetBox = L.marker([res.lat, res.lon], { icon: targetIcon() }).addTo(map)
                .bindPopup(locationPopupHTML(res)).openPopup();
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
        initAdvancedStrip();

        // The canvas height is viewport-relative (clamp) — keep Leaflet's
        // size in sync when the window is resized.
        var resizeTimer = null;
        window.addEventListener('resize', function () {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () { if (map) map.invalidateSize(); }, 200);
        });

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

        // URL params: ?location=… · ?hazard=… · ?year=…
        var params = new URLSearchParams(location.search);
        initialYear = params.get('year');
        loadHazards(params.get('hazard') || undefined);
        var q = params.get('location');
        if (q) {
            el('locInput').value = q;
            goToLocation(q);
        }
    }

    init();
})();
