/* Talaix — Sector Exposure Screening (merged into the Intelligence hub).
 *
 * Lazy initializer exposed as HS.sector.init(mountEl). The first time the
 * Sector Exposure pseudo-tab is selected in intelligence.html this module
 * renders the full panel (controls + results) into #sectorPanel and loads the
 * hazard registry so per-sector hazard names can link back to their real
 * hazard analysis tabs.
 *
 * Backend used: GET /api/v2/sector-screen/?lat=&lon=&sectors=
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    var SECTORS = [
        { id: 'agriculture', label: 'Agriculture' },
        { id: 'real_estate_residential', label: 'Real estate — residential' },
        { id: 'real_estate_commercial', label: 'Real estate — commercial' },
        { id: 'tourism_hospitality', label: 'Tourism & hospitality' },
        { id: 'energy_solar', label: 'Energy — solar' },
        { id: 'energy_wind', label: 'Energy — wind' },
        { id: 'logistics_ports', label: 'Logistics & ports' },
        { id: 'mining', label: 'Mining' },
        { id: 'forestry_timber', label: 'Forestry & timber' }
    ];

    var E = {
        locInput: 'sec-loc-input',
        locAssist: 'sec-loc-assist',
        chips: 'sec-chips',
        runBtn: 'sec-run-btn',
        status: 'sec-status',
        result: 'sec-result'
    };

    var initialized = false;
    var selected = {};
    SECTORS.forEach(function (s) { selected[s.id] = true; });

    var hazards = [];
    var hazardByName = {};   // lower-cased name/id -> hazard id

    function el(name) { return document.getElementById(E[name]); }

    function loadHazards() {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) return;
            hazards = res.body.hazards;
            hazards.forEach(function (h) {
                if (!h.id) return;
                hazardByName[h.id.toLowerCase()] = h.id;
                if (h.name) hazardByName[h.name.toLowerCase()] = h.id;
            });
        }).catch(function () { /* hazard rows render as plain text */ });
    }

    function hazardLink(name) {
        if (!name) return '—';
        var id = hazardByName[name.toLowerCase()];
        if (id) {
            return '<a class="text-link" href="intelligence.html#' + esc(id) + '">' + esc(name) + '</a>';
        }
        return esc(name);
    }

    function renderStatus(kind, html) {
        el('status').innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function clearStatus() {
        el('status').innerHTML = '';
    }

    function renderChips() {
        var html = SECTORS.map(function (s) {
            var on = selected[s.id];
            return '<button type="button" class="sector-chip' + (on ? ' active' : '') + '" data-id="' + esc(s.id) + '">' +
                esc(s.label) + '</button>';
        }).join('');
        el('chips').innerHTML = html;
        el('chips').querySelectorAll('.sector-chip').forEach(function (btn) {
            btn.addEventListener('click', function () {
                selected[btn.getAttribute('data-id')] = !selected[btn.getAttribute('data-id')];
                renderChips();
            });
        });
    }

    function bandClass(band) {
        return { lower: 'observed', moderate: 'modelled', elevated: 'forecast', high: 'unknown' }[band] || 'unknown';
    }

    function runScreen() {
        var input = el('locInput').value.trim();
        var active = SECTORS.filter(function (s) { return selected[s.id]; }).map(function (s) { return s.id; });
        if (!input) {
            renderStatus('error', 'Enter a location — a place name or lat,lon coordinates.');
            return;
        }
        if (active.length === 0) {
            renderStatus('error', 'Select at least one sector.');
            return;
        }
        el('runBtn').disabled = true;
        clearStatus();
        renderStatus('info', 'Resolving location and building the sector screen…');

        HS.resolveLocation(input).then(function (loc) {
            if (!loc.ok) {
                el('runBtn').disabled = false;
                renderStatus('error', esc(loc.error || 'Location could not be resolved.'));
                return;
            }
            var url = API + '/v2/sector-screen/?lat=' + loc.lat.toFixed(4) +
                '&lon=' + loc.lon.toFixed(4) +
                '&sectors=' + encodeURIComponent(active.join(',')) +
                '&name=' + encodeURIComponent(loc.name);
            return fetchJSON(url).then(function (res) {
                el('runBtn').disabled = false;
                if (!res.ok) {
                    renderStatus('error', esc((res.body && res.body.error) || 'Screen failed'));
                    return;
                }
                renderScreen(res.body, loc);
            });
        }).catch(function () {
            el('runBtn').disabled = false;
            renderStatus('error', 'The screening service could not be reached.');
        });
    }

    function renderScreen(screen, loc) {
        var html = '';

        html += '<div class="panel">' +
            '<h2>Screen for ' + esc(loc.name) + '</h2>' +
            '<p class="muted small">Screen ID: ' + esc(screen.screen_id) + ' · ' +
            loc.lat.toFixed(4) + ', ' + loc.lon.toFixed(4) + '</p>' +
            '<p class="muted small">' + esc(screen.disclaimer) + '</p>' +
            '</div>';

        // Per-sector cards
        html += '<div class="content-grid">';
        (screen.sectors || []).forEach(function (sector) {
            var exp = sector.screening_exposure || {};
            html += '<div class="content-card">' +
                '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">' +
                '<h3>' + esc(sector.label) + '</h3>' +
                chip(bandClass(exp.band), (exp.band || 'unknown').toUpperCase()) +
                '</div>' +
                '<p class="muted small">Score ' + esc(exp.score) + ' — ' + esc(exp.note) + '</p>' +
                '<table class="sector-table"><thead><tr><th>Hazard</th><th>Weight</th><th>Level</th><th>Status</th></tr></thead><tbody>';
            (sector.hazard_exposures || []).forEach(function (h) {
                html += '<tr>' +
                    '<td>' + hazardLink(h.hazard) + '</td>' +
                    '<td>' + esc(h.weight) + '</td>' +
                    '<td>' + esc(h.level_label || '—') + '</td>' +
                    '<td>' + chip(h.claim_status, h.claim_status) + '</td>' +
                    '</tr>';
            });
            html += '</tbody></table>' +
                '<p class="muted small" style="margin-top:10px;"><strong>Evidence use:</strong> ' + esc(sector.investor_note) + '</p>' +
                '</div>';
        });
        html += '</div>';

        // Trajectory panel
        var traj = screen.trajectory || {};
        html += '<div class="panel"><h2>Physical trajectory</h2>';
        html += '<p>' + esc(traj.trend_note || '') + '</p>';
        html += '<div class="content-grid" style="margin-top:14px;">';

        var climate = traj.climate || {};
        html += '<div class="content-card">' +
            '<h4>Climate</h4>';
        if (climate.claim_status === 'UNKNOWN') {
            html += '<p class="muted small">' + esc(climate.reason || 'Climate trajectory unavailable.') + '</p>';
        } else {
            html += '<p class="muted small">Anomaly vs ' + esc(climate.baseline_period || 'baseline') + '</p>' +
                '<p>Temperature: ' + (climate.mean_tmax_anomaly_c != null ? (climate.mean_tmax_anomaly_c >= 0 ? '+' : '') + climate.mean_tmax_anomaly_c + ' °C' : '—') + '</p>' +
                '<p>Precipitation: ' + (climate.precip_pct_of_baseline != null ? climate.precip_pct_of_baseline + '% of baseline' : '—') + '</p>';
        }
        html += '</div>';

        var forest = traj.forest || {};
        html += '<div class="content-card">' +
            '<h4>Forest cover</h4>';
        if (forest.claim_status === 'UNKNOWN') {
            html += '<p class="muted small">' + esc(forest.reason || 'Forest-loss data unavailable.') + '</p>';
        } else {
            html += '<p>Tree cover 2000: ' + (forest.tree_cover_2000_mean_pct != null ? forest.tree_cover_2000_mean_pct + '%' : '—') + '</p>' +
                '<p>Loss after 2020: ' + (forest.loss_after_2020 ? 'yes' : 'no') + '</p>';
            var fy = forest.loss_years || {};
            var fyKeys = Object.keys(fy).sort();
            if (fyKeys.length) {
                html += '<p class="muted small">Loss years: ' + esc(fyKeys.slice(0, 6).join(', ')) +
                    (fyKeys.length > 6 ? ' …' : '') + '</p>';
            }
        }
        html += '</div>';

        var urban = traj.urban_expansion || {};
        html += '<div class="content-card">' +
            '<h4>Urban expansion</h4>';
        if (urban.claim_status === 'UNKNOWN') {
            html += '<p class="muted small">' + esc(urban.reason || 'Building-count data unavailable.') + '</p>';
        } else {
            html += '<p>Buildings 2015: ' + (urban.epoch_2015 != null ? urban.epoch_2015.toLocaleString() : '—') + '</p>' +
                '<p>Buildings latest: ' + (urban.latest != null ? urban.latest.toLocaleString() : '—') + '</p>' +
                '<p>Growth: ' + (urban.growth_pct != null ? (urban.growth_pct >= 0 ? '+' : '') + urban.growth_pct + '%' : '—') + '</p>';
        }
        html += '</div>';

        var pop = traj.population || {};
        html += '<div class="content-card">' +
            '<h4>Population</h4>';
        if (pop.claim_status === 'UNKNOWN') {
            html += '<p class="muted small">' + esc(pop.reason || 'Population estimate unavailable.') + '</p>';
        } else {
            html += '<p>Estimate: ' + (pop.estimated_population != null ? pop.estimated_population.toLocaleString() : '—') + '</p>' +
                '<p class="muted small">' + esc(pop.note || '') + '</p>';
        }
        html += '</div>';

        html += '</div></div>';

        // Crime panel
        var crime = screen.crime || {};
        html += '<div class="panel"><h2>Crime layer</h2>';
        if (crime.jurisdiction_gap || crime.claim_status === 'UNKNOWN') {
            html += '<div class="notice notice-info"><p>' + esc(crime.reason || 'Official crime statistics unavailable for this jurisdiction.') + '</p></div>';
        } else {
            html += '<p class="muted small">' + esc(crime.source || '') + ' · ' + esc(crime.period || '') + '</p>' +
                '<p>Total recorded incidents: ' + (crime.total != null ? crime.total.toLocaleString() : '—') + '</p>';
            if ((crime.by_category || []).length) {
                html += '<table class="sector-table"><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>';
                crime.by_category.forEach(function (c) {
                    html += '<tr><td>' + esc(c.category) + '</td><td>' + c.count.toLocaleString() + '</td></tr>';
                });
                html += '</tbody></table>';
            }
            if ((crime.monthly_points || []).length) {
                html += '<p class="muted small" style="margin-top:10px;">Monthly totals: ' +
                    crime.monthly_points.map(function (m) { return m.month + ': ' + m.total; }).join(' · ') + '</p>';
            }
        }
        html += '</div>';

        // Declared gaps and methodology
        html += '<div class="panel"><h2>Methodology &amp; declared gaps</h2>';
        if ((screen.declared_gaps || []).length) {
            html += '<ul class="muted small">';
            screen.declared_gaps.forEach(function (g) {
                html += '<li><strong>' + esc(g.component || g.sector || 'data gap') + '</strong> — ' + esc(g.reason) + '</li>';
            });
            html += '</ul>';
        } else {
            html += '<p class="muted small">No declared gaps for this screen.</p>';
        }
        html += '<p class="muted small">' + esc(screen.methodology_note || '') + '</p>' +
            '<p class="muted small">' + esc(screen.honesty_contract || '') + '</p>' +
            '</div>';

        el('result').innerHTML = html;
    }

    function renderPanel() {
        return '<div class="panel">' +
            '<h2>Sector Exposure Screening</h2>' +
            '<p class="page-lead">' +
            'Physical evidence for investors, property owners and governments: ' +
            'sector-hazard sensitivity, current location-level hazards, and the ' +
            'physical trajectory over time — with official crime statistics only ' +
            'where an open official source exists.' +
            '</p>' +
            '<div class="notice notice-warn">' +
            '<strong>Not investment advice.</strong> This page provides physical-risk ' +
            'screening evidence only. It is not a valuation, not a prediction, and not ' +
            'a recommendation to invest, divest or transact. Crime figures come from ' +
            'official statistics only where an open source exists.' +
            '</div>' +
            '</div>' +
            '<div class="panel">' +
            '<h3>Screen a location</h3>' +
            '<div class="toolbar" style="align-items:flex-start; flex-wrap:wrap;">' +
            '<div class="form-group" style="flex:1; min-width:220px;">' +
            '<label for="' + E.locInput + '">Location</label>' +
            '<input type="text" id="' + E.locInput + '" placeholder="Place name or lat,lon (e.g. Clervaux, Luxembourg)">' +
            '</div>' +
            '<div id="' + E.locAssist + '" style="flex-basis:100%;"></div>' +
            '<div class="form-group" style="min-width:220px;">' +
            '<label>Sectors</label>' +
            '<div id="' + E.chips + '" class="sector-chips"></div>' +
            '</div>' +
            '<button class="btn-action" id="' + E.runBtn + '" style="margin-top:24px;">Run screen</button>' +
            '</div>' +
            '<div id="' + E.status + '"></div>' +
            '</div>' +
            '<div id="' + E.result + '"></div>';
    }

    function init(mount) {
        if (initialized) return;
        initialized = true;
        mount.innerHTML = renderPanel();

        renderChips();
        el('runBtn').addEventListener('click', runScreen);
        el('locInput').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') runScreen();
        });
        if (window.HS && HS.location) {
            HS.location.enhance(E.locInput, E.locAssist);
        }
        loadHazards();

        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q) {
            el('locInput').value = q;
            runScreen();
        }
    }

    window.HS = window.HS || {};
    window.HS.sector = { init: init };
})();
