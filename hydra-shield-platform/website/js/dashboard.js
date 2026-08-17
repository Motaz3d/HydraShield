/* HydraShield public dashboard — real-data client.
 *
 * Calls the HydraShield REST API (/api/analyze, /api/risk-grid, /api/watch)
 * and renders the report + interactive map. No simulated data: when the API
 * reports a component unavailable, the UI says so.
 */
(function () {
    'use strict';

    var API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8051/api'
        : '/api';

    var map = null;
    var layers = {};
    var lastResult = null;

    function el(id) { return document.getElementById(id); }

    function notice(msg, isError) {
        var n = el('notice');
        n.textContent = msg;
        n.className = 'notice ' + (isError ? 'notice-error' : 'notice-info');
        n.classList.remove('hidden');
    }

    function hideNotice() { el('notice').classList.add('hidden'); }

    function chip(kind) {
        var k = (kind || 'unavailable').toLowerCase();
        var label = k.charAt(0).toUpperCase() + k.slice(1);
        return '<span class="chip chip-' + k + '">' + label + '</span>';
    }

    function fmt(v, unit, digits) {
        if (v === null || v === undefined || v !== v) return '—';
        if (typeof v === 'number' && digits !== undefined) v = v.toFixed(digits);
        return v + (unit || '');
    }

    function riskColor(cls) {
        return { Low: '#22c55e', Moderate: '#eab308', High: '#f97316', Extreme: '#ef4444' }[cls] || '#94a3b8';
    }

    // ------------------------------------------------------------------
    // Progressive analysis (job-based, honest stage transitions)
    // ------------------------------------------------------------------
    var pollTimer = null;
    var pollDeadline = null;
    var currentJobId = null;

    function analyze(query) {
        var btn = el('analyzeBtn');
        btn.disabled = true;
        el('report').classList.add('hidden');
        el('foundPanel').classList.add('hidden');
        hideNotice();
        var payload;
        if (/^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$/.test(query)) {
            var parts = query.split(',');
            payload = { lat: parseFloat(parts[0]), lon: parseFloat(parts[1]) };
        } else {
            payload = { location: query };
        }
        // Stage rows appear immediately as PENDING; they only advance when
        // the backend reports real transitions.
        fetch(API + '/analysis-jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
            .then(function (res) {
                if (!res.ok || res.body.error) {
                    btn.disabled = false;
                    el('progressPanel').classList.add('hidden');
                    notice(res.body.error || 'Could not start the analysis.', true);
                    return;
                }
                currentJobId = res.body.id;
                renderStages(res.body.stages || []);
                el('progressPanel').classList.remove('hidden');
                pollDeadline = Date.now() + 5 * 60 * 1000; // 5 min polling cap
                pollJob();
            })
            .catch(function (err) {
                btn.disabled = false;
                el('progressPanel').classList.add('hidden');
                notice('Analysis request failed: ' + err, true);
            });
    }

    function pollJob() {
        if (!currentJobId) return;
        if (Date.now() > pollDeadline) {
            stopPolling();
            el('progressNote').innerHTML =
                'This is taking longer than usual — the analysis continues on the server. ' +
                'Completed results are cached. <a href="" onclick="location.reload();return false;">Retry</a>';
            el('cancelBtn').classList.add('hidden');
            el('analyzeBtn').disabled = false;
            return;
        }
        fetch(API + '/analysis-jobs/' + currentJobId)
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
            .then(function (res) {
                if (!res.ok || res.body.error) {
                    stopPolling();
                    el('progressPanel').classList.add('hidden');
                    el('analyzeBtn').disabled = false;
                    notice(res.body.error || 'Job not found.', true);
                    return;
                }
                renderStages(res.body.stages || []);
                if (res.body.status === 'complete') {
                    finishAnalysis(res.body);
                } else if (res.body.status === 'failed') {
                    stopPolling();
                    el('progressPanel').classList.add('hidden');
                    el('analyzeBtn').disabled = false;
                    notice(res.body.error || 'Analysis could not be completed. No risk score was generated.', true);
                } else {
                    pollTimer = setTimeout(pollJob, 1500);
                }
            })
            .catch(function () {
                pollTimer = setTimeout(pollJob, 3000); // transient network issue: keep polling
            });
    }

    function stopPolling() {
        if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    }

    function stageDetailText(stage) {
        var d = stage.detail || {};
        switch (stage.id) {
            case 'location': return d.name ? d.name + '  (' + d.latitude + ', ' + d.longitude + ')' : '';
            case 'weather': return d.temperature_c !== undefined && d.temperature_c !== null
                ? d.temperature_c + ' °C · wind ' + d.wind_kmh + ' km/h · humidity ' + d.humidity_pct + '%'
                : '';
            case 'fire_danger': return d.fwi !== undefined && d.fwi !== null
                ? 'FWI ' + d.fwi + ' (' + d.class + ') · ' + d.date : '';
            case 'terrain': return d.elevation_m !== undefined && d.elevation_m !== null
                ? 'Elevation ' + Math.round(d.elevation_m) + ' m · slope ' + d.slope_degrees + '°' : '';
            case 'satellite': return d.observation_date
                ? 'Observation ' + d.observation_date + ' · NDVI ' + d.ndvi + ' · NDMI ' + d.ndmi : '';
            case 'fuel': return d.fmc_pct !== undefined && d.fmc_pct !== null
                ? 'Fuel moisture ' + d.fmc_pct + '%' : '';
            case 'landcover': return d.dominant_label
                ? d.dominant_label + ' → fuel model ' + d.fuel_model : '';
            case 'fires': return d.count !== undefined
                ? d.count + ' detection(s) in ' + d.days + ' days' : '';
            case 'risk': return d.risk !== undefined && d.risk !== null ? 'Risk calculated' : '';
            case 'solutions': return d.recommendations !== undefined
                ? d.recommendations + ' evidence-based recommendation(s)' : '';
            default: return '';
        }
    }

    function renderStages(stages) {
        var icons = { pending: '○', running: '●', complete: '✓', unavailable: '⚠' };
        el('stageList').innerHTML = stages.map(function (s) {
            var cls = 'st-' + s.status;
            var detail = '';
            if (s.status === 'complete') detail = stageDetailText(s);
            if (s.status === 'unavailable') detail = 'unavailable' +
                (s.detail && s.detail.reason ? ' — ' + s.detail.reason : '') +
                ' (analysis continued with the available evidence)';
            return '<li class="stage-row ' + cls + '">' +
                '<span class="stage-icon">' + (icons[s.status] || '○') + '</span>' +
                '<span class="stage-main"><span class="stage-label">' + s.label +
                '<small>' + s.source + '</small></span>' +
                (detail ? '<div class="stage-detail">' + detail + '</div>' : '') +
                '</span></li>';
        }).join('');
    }

    function finishAnalysis(job) {
        stopPolling();
        el('progressPanel').classList.add('hidden');
        el('analyzeBtn').disabled = false;
        var r = job.result;
        lastResult = r;
        render(r);
        el('report').classList.remove('hidden');
        renderFoundSummary(r);
        renderReportCards(r);
        el('cacheNote').textContent = job.from_cache
            ? ' Using a recent analysis (generated ' + (job.generated_at || '') + ').'
            : '';
        el('foundPanel').classList.remove('hidden');
        el('foundPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function renderFoundSummary(r) {
        var a = r.analysis || {};
        var risk = a.risk || {};
        var fd = r.fire_danger || {};
        var ex = r.risk_explanation || {};
        var factors = ex.factors || [];
        var byKey = {};
        factors.forEach(function (f) { byKey[f.key] = f; });
        var main = null;
        factors.forEach(function (f) {
            if (f.affects_score && typeof f.contribution === 'number' &&
                (main === null || f.contribution > (main.contribution || 0))) main = f;
        });
        var exposure = r.exposure || {};
        var sat = r.satellite || {};
        var items = [
            ['🔥 Fire danger', fd.available ? fd.class + ' (FWI ' + fd.fwi + ')' : 'unavailable'],
            ['🌬 Main driver', main ? main.label + ' — ' + main.level : 'undetermined'],
            ['🌿 Fuel condition', byKey.fuel_dryness ? byKey.fuel_dryness.level + ' (' +
                fmt(byKey.fuel_dryness.value, '%', 1) + ')' : 'unavailable'],
            ['⛰ Terrain', byKey.terrain ? byKey.terrain.level + ' (' +
                fmt(byKey.terrain.value, '°', 1) + ')' : 'unavailable'],
            ['🏘 Exposure', exposure.status === 'ok'
                ? (exposure.exposure || {}).level + ' (mapped OSM data)' : 'unavailable'],
            ['🛰 Satellite', sat.error ? 'unavailable' : 'Observation ' +
                String(sat.observation_date || '').slice(0, 10)],
        ];
        el('foundGrid').innerHTML = items.map(function (it) {
            return '<div class="metric"><div class="v" style="font-size:1.05rem;">' + it[1] +
                '</div><div class="l">' + it[0] + '</div></div>';
        }).join('');
        var recs = (r.recommendations || []).slice(0, 3);
        el('foundActions').innerHTML = recs.length
            ? '<b>What should you do?</b><ol style="margin:.4rem 0 0;padding-left:1.2rem;">' +
              recs.map(function (rec) { return '<li>' + rec.what + '</li>'; }).join('') + '</ol>'
            : '<span style="color:var(--muted)">No condition-triggered actions right now.</span>';
    }

    function renderReportCards(r) {
        var lat = r.location.latitude, lon = r.location.longitude;
        var types = [
            { id: 'simple', name: 'Simple Report', aud: 'For people and property owners',
              contents: ['Risk & why', 'Main conditions', 'What to do', 'Sources & limitations'] },
            { id: 'decision', name: 'Decision-Support Report', aud: 'For municipalities and organizations',
              contents: ['Risk drivers & trend', 'Exposure & vulnerability', 'Modelled scenarios',
                         'Environmental solutions', 'Priority actions', 'Provenance'] },
            { id: 'scientific', name: 'Scientific Report', aud: 'For researchers and technical institutions',
              contents: ['Full methodology', 'FWI / Sentinel-2 / terrain methods', 'Validation status',
                         'Assumptions & limitations', 'References'] },
        ];
        el('reportCards').innerHTML = types.map(function (t) {
            var url = API + '/report?lat=' + lat + '&lon=' + lon + '&history=1&type=' + t.id;
            return '<div class="report-card"><h4>' + t.name + '</h4>' +
                '<div class="aud">' + t.aud + '</div>' +
                '<ul>' + t.contents.map(function (c) { return '<li>' + c + '</li>'; }).join('') + '</ul>' +
                '<a href="' + url + '" target="_blank" rel="noopener">Open PDF</a></div>';
        }).join('');
    }

    function render(r) {
        el('report').classList.remove('hidden');
        var a = r.analysis || {};
        var risk = a.risk || {};
        var fd = r.fire_danger || {};
        var prov = r.provenance || {};

        el('locName').textContent = r.location ? r.location.name : '';
        el('riskScore').textContent = fmt(risk.baseline, '', 0);
        var cls = risk.class || '—';
        var rc = el('riskClass');
        rc.textContent = cls.toUpperCase();
        rc.className = 'risk-class-label cls-' + cls;
        el('fwiVal').textContent = fd.available ? fmt(fd.fwi, '', 1) : 'unavailable';
        el('fwiClass').innerHTML = fd.available ? '(' + fd.class + ') ' + chip('derived') : chip('unavailable');
        var trend = r.fire_danger_trend || {};
        el('fwiTrend').textContent = trend.trend || 'unknown';
        el('generatedAt').textContent = (r.generated_at || '').replace('T', ' ').replace('Z', ' UTC');
        el('scoreDisclaimer').textContent = ((r.risk_explanation || {}).disclaimer) ||
            'This is a composite wildfire-risk indicator (0–100), not a probability of fire.';

        renderConditions(r);
        renderWhy(r.risk_explanation || {});
        renderChange(r.change || {});
        renderExposure(r.exposure || {});
        renderPeople(r.population || {});
        renderIgnition(r.ignition || {});
        renderSmoke(r.smoke_scenario || {});
        renderMicro(r.micro_area || {});
        renderProactive(r.recommendations || []);
        renderEcology(r.ecology || {});
        renderActionPlan(r.action_plan || {});
        renderScenarios(r.scenarios || []);
        renderDrivers(r);
        renderComparison(a);
        renderSpread(a);
        renderFires(r.active_fires || {});
        renderRecommendation(a, fd);
        renderScience(r);
        renderProvenance(prov);
        renderMap(r);
    }

    function renderConditions(r) {
        var w = r.weather || {};
        var t = r.terrain || {};
        var s = r.satellite || {};
        var a = r.analysis || {};
        var items = [
            ['Temperature', fmt(w.temperature_c, ' °C', 1), 'modeled'],
            ['Wind', fmt(w.wind_speed_kmh, ' km/h', 0) + ' ' + windArrow(w.wind_direction_deg), 'modeled'],
            ['Humidity', fmt(w.relative_humidity_pct, ' %', 0), 'modeled'],
            ['Precipitation', fmt(w.precipitation_mm, ' mm', 1), 'modeled'],
            ['Fuel moisture', fmt(a.fuel_moisture_baseline_pct, ' %', 1), s.error ? 'derived' : 'observed'],
            ['Vegetation (NDVI)', s.error ? 'unavailable' : fmt(s.ndvi, '', 2), s.error ? 'unavailable' : 'observed'],
            ['Elevation', fmt(t.elevation_m, ' m', 0), t.error ? 'unavailable' : 'observed'],
            ['Slope', fmt(t.slope_degrees, '°', 1), t.error ? 'unavailable' : 'observed']
        ];
        el('conditionsGrid').innerHTML = items.map(function (it) {
            return '<div class="metric' + (it[2] === 'unavailable' ? ' unavail' : '') + '">' +
                '<div class="v">' + it[1] + '</div>' +
                '<div class="l">' + it[0] + '</div>' + chip(it[2]) + '</div>';
        }).join('');
    }

    function windArrow(deg) {
        if (deg === null || deg === undefined) return '';
        var arrows = ['↓ N', '↙ NE', '← E', '↖ SE', '↑ S', '↗ SW', '→ W', '↘ NW'];
        return arrows[Math.round(((deg % 360) / 45)) % 8];
    }

    // ------------------------------------------------------------------
    // Why this score / What changed / Proactive / Automation
    // ------------------------------------------------------------------
    function lvlBadge(rank, label) {
        if (label === null || label === undefined) return '<span class="lvl lvl-none">unavailable</span>';
        var cls = (rank === null || rank === undefined) ? 'lvl-none' : 'lvl-' + rank;
        return '<span class="lvl ' + cls + '">' + label + '</span>';
    }

    function renderWhy(ex) {
        var box = el('whyScore');
        var factors = ex.factors || [];
        if (!factors.length) {
            box.innerHTML = '<span class="unavail">Score decomposition unavailable.</span>';
            return;
        }
        box.innerHTML = factors.map(function (f) {
            var val = (f.value === null || f.value === undefined) ? '—'
                : f.value + (f.unit ? ' ' + f.unit : '');
            var note = f.contribution_note ? f.contribution_note : '';
            return '<div class="factor-row">' +
                '<span class="fname">' + f.label + '</span>' +
                '<span class="fval">' + val + '</span>' +
                lvlBadge(f.level_rank, f.level) +
                '<span class="fnote">' + note + (f.affects_score ? '' : ' (context)') + '</span>' +
                '</div>';
        }).join('') +
        '<div class="score-disclaimer">' + (ex.disclaimer || '') + '</div>' +
        (ex.formula ? '<div class="footer-note">' + ex.formula + '</div>' : '');
    }

    function renderChange(ch) {
        var box = el('whatChanged');
        if (!ch.available) {
            box.innerHTML = '<span class="unavail">' +
                (ch.reason || 'Temporal comparison unavailable.') + '</span>';
            return;
        }
        var r = ch.risk || {};
        function delta(v, invert) {
            if (v === null || v === undefined) return '<span class="delta-stable">—</span>';
            var cls = v > 0 ? 'delta-up' : (v < 0 ? 'delta-down' : 'delta-stable');
            var arrow = v > 0 ? ' ↑' : (v < 0 ? ' ↓' : '');
            return '<span class="' + cls + '">' + (v > 0 ? '+' : '') + v + arrow + '</span>';
        }
        var html = '<div class="change-grid">' +
            '<div class="metric"><div class="v">' + fmt(r.today, '', 0) + '</div><div class="l">Risk today</div></div>' +
            '<div class="metric"><div class="v">' + delta(r.delta_24h) + '</div><div class="l">vs 24 h ago</div></div>' +
            '<div class="metric"><div class="v">' + delta(r.delta_7d) + '</div><div class="l">vs 7 days ago</div></div>' +
            '</div>';
        html += '<div class="kv">' + (ch.drivers_7d || []).map(function (d) {
            var thenNow = fmt(d.then, '', 1) + ' → ' + fmt(d.now, '', 1) + ' ' + (d.unit || '');
            return '<div><span class="k">' + d.label + ':</span> ' + thenNow + ' ' +
                (d.significant ? '<b class="delta-' + (d.direction === 'up' ? 'up' : 'down') + '">' +
                    (d.direction === 'up' ? '↑' : '↓') + '</b>' : '') + '</div>';
        }).join('') + '</div>';
        html += '<p style="margin:.8rem 0 0;font-size:.95rem;"><b>' + (ch.explanation || '') + '</b></p>';
        if (ch.ndmi_change && ch.ndmi_change.note) {
            html += '<div class="footer-note">' + ch.ndmi_change.note + '</div>';
        }
        html += '<div class="footer-note">' + (ch.basis_note || '') + '</div>';
        box.innerHTML = html;
    }

    function renderProactive(recs) {
        var box = el('proactiveList');
        if (!recs.length) {
            box.innerHTML = '<span class="unavail">No condition-triggered recommendations right now — ' +
                'no significant risk driver is currently detected.</span>';
            return;
        }
        box.innerHTML = recs.map(function (r) {
            return '<div class="rec-item">' +
                '<div class="what"><span class="prio prio-' + r.priority + '">' + r.priority + '</span> ' + r.what + '</div>' +
                '<div class="why"><b>Why:</b> ' + r.why + '</div>' +
                '<div class="meta"><b>Expected effect:</b> ' + r.expected_effect +
                '<br><b>Evidence:</b> ' + JSON.stringify(r.evidence) +
                '<br><b>Data sources:</b> ' + (r.data_sources || []).join(' · ') + '</div>' +
                '</div>';
        }).join('');
    }

    function renderActionPlan(plan) {
        var box = el('actionPlan');
        var actions = plan.actions || [];
        if (!actions.length) {
            box.innerHTML = '<span class="unavail">No action plan — risk level "' +
                (plan.level || 'routine') + '" requires no automated steps.</span>';
            return;
        }
        var html = '<p style="margin-top:0;font-size:.9rem;">Response level: <b>' +
            (plan.level || '—') + '</b>' +
            (plan.automation_enabled ? '' : ' · <span style="color:var(--muted)">automation not armed (framework only)</span>') +
            '</p>';
        html += actions.map(function (a) {
            var tag = a.type === 'automated'
                ? '<span class="prio tag-automated">automated</span>'
                : '<span class="prio tag-recommended">recommended</span>';
            var status = '<span class="prio tag-status">' + (a.status || '').replace(/_/g, ' ') + '</span>';
            return '<div class="action-item">' +
                '<div class="what">' + tag + ' ' + status + ' ' + a.action + '</div>' +
                '<div class="meta"><b>Trigger:</b> ' + JSON.stringify(a.trigger) +
                (a.note ? '<br>' + a.note : '') +
                '<br><b>Outcome:</b> ' + (a.outcome || 'unknown (not yet executed)') + '</div>' +
                '</div>';
        }).join('');
        html += '<div class="footer-note">' + (plan.honesty_note || '') + '</div>';
        box.innerHTML = html;
    }

    // ------------------------------------------------------------------
    // Exposure / Micro-area / Ecology / Scenarios
    // ------------------------------------------------------------------
    function renderExposure(x) {
        var box = el('exposureBlock');
        if (x.status !== 'ok') {
            box.innerHTML = '<span class="unavail">OpenStreetMap context unavailable — ' +
                (x.reason || '') + '.</span> ' + chip('unavailable');
            return;
        }
        var va = x.vulnerable_assets || {};
        var ac = x.access || {};
        var wui = x.wui_indicator || {};
        var wr = x.water_resources || {};
        box.innerHTML = '<div class="kv">' +
            '<div><span class="k">Buildings mapped (' + x.radius_m + ' m):</span> ' +
                (x.exposure || {}).buildings_mapped + ' — ' + (x.exposure || {}).level + ' ' + chip('observed') + '</div>' +
            '<div><span class="k">Critical facilities:</span> ' + (va.total || 0) +
                ' (hospitals ' + (va.hospitals || 0) + ', schools ' + (va.schools || 0) +
                ', fire stations ' + (va.fire_stations || 0) + ', power ' + (va.power_facilities || 0) + ') ' + chip('observed') + '</div>' +
            '<div><span class="k">Access:</span> ' +
                (ac.limited ? '<b style="color:var(--high)">constraints — ' + (ac.constraints || []).join('; ') + '</b>'
                            : 'no mapped constraint detected') + '</div>' +
            '<div><span class="k">Potential WUI:</span> ' + (wui.potential_wui ? '<b style="color:var(--high)">yes</b>' : 'no') +
                ' — ' + (wui.note || '') + '</div>' +
            '<div><span class="k">Water features mapped:</span> ' + (wr.features_mapped || 0) +
                ' <span style="color:var(--muted)">(availability for suppression not implied)</span></div>' +
            '</div>' +
            '<div class="footer-note">Counts are mapped OpenStreetMap features; completeness varies by region. ' +
            (x.separate_from_score_note || '') + '</div>';
    }

    function renderPeople(p) {
        var box = el('peopleBlock');
        if (p.status !== 'ok') {
            box.innerHTML = '<span class="unavail">Population exposure unavailable — ' +
                (p.reason || '') + '.</span> ' + chip('unavailable');
            return;
        }
        var html = '<div class="kv">' +
            '<div><span class="k">Estimated population (' + p.radius_km + ' km radius):</span> ' +
                fmt(p.estimated_population, '', 0) + ' ' + chip('modeled') + '</div>' +
            '<div><span class="k">Mean density:</span> ' + fmt(p.mean_density_per_km2, ' people/km²', 1) +
                (p.density_level ? ' — ' + p.density_level : '') + '</div>' +
            '<div><span class="k">Hazard class:</span> ' + (p.hazard_class || 'unknown') + '</div>';
        if (p.estimated_population_in_hazard_area !== null &&
            p.estimated_population_in_hazard_area !== undefined) {
            html += '<div><span class="k">Est. population in hazard area:</span> ' +
                fmt(p.estimated_population_in_hazard_area, '', 0) + '</div>';
        }
        if (p.mapped_buildings !== null && p.mapped_buildings !== undefined) {
            html += '<div><span class="k">Mapped buildings (OSM):</span> ' + p.mapped_buildings + '</div>';
        }
        html += '</div>';
        html += '<p style="margin:.7rem 0 0;font-size:.95rem;">Human-exposure priority: ' +
            '<span class="prio prio-' + p.human_exposure_priority + '">' + p.human_exposure_priority +
            '</span> <span style="color:var(--muted)">' + (p.human_exposure_note || '') + '</span></p>';
        var cf = p.critical_facilities;
        if (cf) {
            html += '<div class="kv"><div><span class="k">Critical facilities:</span> hospitals ' +
                (cf.hospitals || 0) + ', schools ' + (cf.schools || 0) + ', fire stations ' +
                (cf.fire_stations || 0) + ', power ' + (cf.power_facilities || 0) + ' ' + chip('observed') +
                '</div></div>' +
                '<div class="footer-note">' + (cf.note || '') + '</div>';
        }
        html += '<div class="footer-note">' + (p.estimate_note || '') + '</div>' +
            '<div class="footer-note">' + (p.exposure_note || '') + '</div>' +
            '<div class="footer-note">' + (p.separate_from_score_note || '') + '</div>';
        box.innerHTML = html;
    }

    function renderIgnition(ig) {
        var box = el('ignitionBlock');
        var classPrio = { low: 'prio-low', moderate: 'prio-moderate', elevated: 'prio-high', high: 'prio-critical' };
        var html = '';
        if (ig.status !== 'ok') {
            html += '<span class="unavail">Ignition-likelihood indicator unavailable — ' +
                (ig.reason || '') + '.</span> ' + chip('unavailable');
        } else {
            html += '<p style="margin-top:0;font-size:.95rem;">' +
                (ig.name || 'Relative Ignition-Likelihood Indicator') + ': <b>' +
                fmt(ig.indicator, '/100', 0) + '</b> ' +
                '<span class="prio ' + (classPrio[ig.class] || 'prio-routine') + '">' +
                (ig.class || '—') + '</span></p>';
            var comps = ig.components || {};
            var compLabels = { fire_weather: 'Fire weather', human_presence: 'Human presence', fuel_dryness: 'Fuel dryness' };
            html += Object.keys(comps).map(function (k) {
                var c = comps[k] || {};
                return '<div class="factor-row">' +
                    '<span class="fname">' + (compLabels[k] || k.replace(/_/g, ' ')) + '</span>' +
                    '<span class="fval">' + fmt(c.score, '', 0) + '/100</span>' +
                    '<span class="fnote">' + (c.basis || '') + ' · weight ' + fmt(c.weight, '', 2) + '</span>' +
                    '</div>';
            }).join('');
            if (ig.coverage_note) html += '<div class="footer-note">' + ig.coverage_note + '</div>';
            if (ig.landcover_note) html += '<div class="footer-note">' + ig.landcover_note + '</div>';
        }
        // Honesty text is mandatory — never dropped, never paraphrased.
        if (ig.not_a_probability) {
            html += '<div class="footer-note"><i>' + ig.not_a_probability + '</i></div>';
        }
        (ig.distinctions || []).forEach(function (d) {
            html += '<div class="footer-note">' + d + '</div>';
        });
        if (ig.lightning_note) html += '<div class="footer-note">' + ig.lightning_note + '</div>';
        var vs = ig.validation_status || {};
        if (vs.status) html += '<div class="footer-note"><b>' + vs.status + '</b></div>';
        box.innerHTML = html;
    }

    function renderSmoke(s) {
        var box = el('smokeBlock');
        if (!s || s.error || s.status !== 'ok') {
            box.innerHTML = '<span class="unavail">Smoke scenario unavailable — ' +
                ((s && s.error) || 'transport could not be computed') + '.</span> ' + chip('unavailable');
            return;
        }
        var t = s.transport || {};
        var w = s.window || {};
        var ov = s.overlays || {};
        var html = '<div class="modelled-label">' + (s.mode_label || 'SCENARIO / MODELLED') + '</div>' +
            '<p style="margin:0 0 .6rem;font-size:.9rem;">' + (s.scenario || '') + '</p>' +
            '<div class="kv">' +
            '<div><span class="k">Dominant transport:</span> ' + (t.dominant_transport_direction || '—') +
                ' (' + fmt(t.dominant_transport_heading_deg, '°', 0) + ')</div>' +
            '<div><span class="k">Mean transport speed:</span> ' + fmt(t.mean_transport_speed_kmh, ' km/h', 1) + '</div>' +
            '<div><span class="k">Window:</span> next ' + fmt(w.hours, ' h', 0) + ' (' + (w.timezone || 'UTC') + ')</div>' +
            '<div><span class="k">Confidence:</span> ' + (t.confidence || '—') +
                ' <span style="color:var(--muted)">— ' + (t.confidence_note || '') + '</span></div>' +
            '</div>';
        var pop = ov.population || {};
        if (pop.available) {
            html += '<div class="kv" style="margin-top:.5rem;"><div><span class="k">Population in corridor:</span> ' +
                fmt(pop.estimated_population_in_corridor, '', 0) +
                ' <span style="color:var(--muted)">(' + (pop.source || '') + ')</span></div></div>' +
                '<div class="footer-note">' + (pop.estimate_note || '') + '</div>';
        }
        var fac = ov.facilities || {};
        if (fac.available && fac.counts) {
            html += '<div class="kv" style="margin-top:.5rem;"><div><span class="k">Facilities in corridor:</span> hospitals ' +
                (fac.counts.hospitals || 0) + ', schools ' + (fac.counts.schools || 0) +
                ', fire stations ' + (fac.counts.fire_stations || 0) +
                ' <span style="color:var(--muted)">(' + (fac.source || '') + ')</span></div></div>';
        }
        html += '<div class="footer-note">' + (s.disclaimer || '') + '</div>';
        var safety = s.safety || {};
        if (safety.distinction_note) html += '<div class="footer-note">' + safety.distinction_note + '</div>';
        html += '<div class="footer-note">Observed-fire smoke transport is available via /api/smoke ' +
            'when a NASA FIRMS key is configured.</div>';
        box.innerHTML = html;
    }

    function renderMicro(m) {
        var box = el('microBlock');
        var mc = m.micro_context || {};
        var rows = (m.resolution_table || []).map(function (r) {
            return '<div><span class="k">' + r.layer + ':</span> ' + r.resolution +
                ' <span style="color:var(--muted)">(' + r.scope + ' — ' + r.source + ')</span></div>';
        }).join('');
        var varNote = mc.variability_note
            ? '<p style="margin:.6rem 0 0;font-size:.9rem;"><b>Measured 10 m variability:</b> ' + mc.variability_note + '</p>'
            : '<p style="margin:.6rem 0 0;color:var(--muted);">' + (mc.unavailable_note || '') + '</p>';
        box.innerHTML = '<div class="kv">' + rows + '</div>' + varNote +
            '<div class="footer-note">' + ((m.regional_context || {}).note || '') + '</div>';
    }

    function renderEcology(eco) {
        var box = el('ecologyBlock');
        if (eco.status !== 'ok') {
            box.innerHTML = '<span class="unavail">' + (eco.message || 'unavailable') + '</span>';
            return;
        }
        var site = eco.site_conditions || {};
        var html = '<p style="margin-top:0;font-size:.9rem;">Site: <b>' +
            (site.climate_zone || 'climate undetermined') + '</b> · moisture regime <b>' +
            (site.moisture_regime || 'undetermined') + '</b> · elevation ' +
            fmt(site.elevation_m, ' m', 0) + ' · land cover ' + (site.land_cover || 'n/a') + '</p>';
        function speciesRows(list, tag) {
            return (list || []).map(function (e) {
                return '<div class="rec-item">' +
                    '<div class="what">' + e.common_name + ' <i style="color:var(--muted)">(' + e.scientific_name + ')</i> ' +
                    '<span class="prio tag-' + (tag === 'not' ? 'status' : (tag === 'caution' ? 'recommended' : 'automated')) + '">' +
                    (tag === 'not' ? 'not recommended' : (tag === 'caution' ? 'with caution' : (e.native ? 'native fit' : 'suitable'))) + '</span></div>' +
                    '<div class="why"><b>Fire:</b> ' + (e.fire_considerations || '—') + '</div>' +
                    '<div class="meta"><b>Role:</b> ' + (e.environmental_role || '—') +
                    '<br><b>Drought tolerance:</b> ' + (e.drought_tolerance || '—') +
                    ' · <b>Water need:</b> ' + (e.water_requirement || '—') +
                    (e.site_fit && (e.site_fit.reasons_for || []).length ?
                        '<br><b>Site fit:</b> ' + e.site_fit.reasons_for.join('; ') : '') +
                    '<br><b>Evidence:</b> ' + (e.evidence || []).join('; ') +
                    ' · <b>Confidence:</b> ' + (e.confidence || '—') + '</div>' +
                    '</div>';
            }).join('');
        }
        html += speciesRows(eco.recommended, 'ok');
        html += speciesRows(eco.recommended_with_caution, 'caution');
        html += speciesRows(eco.not_recommended, 'not');
        html += '<div class="footer-note">' + (eco.fire_note || '') + ' ' + (eco.verification_note || '') + '</div>';
        box.innerHTML = html;
    }

    function renderScenarios(scenarios) {
        var box = el('scenarioList');
        if (!scenarios.length) {
            box.innerHTML = '<span class="unavail">No scenarios available.</span>';
            return;
        }
        box.innerHTML = scenarios.map(function (s) {
            if (s.status === 'modelled') {
                var res = s.result || {}, base = s.baseline || {};
                return '<div class="rec-item">' +
                    '<div class="what">' + s.name + ' <span class="prio tag-recommended">modelled</span></div>' +
                    '<div class="why">' + (s.intervention || '') + '</div>' +
                    '<div class="meta"><b>Risk:</b> ' + fmt(base.risk, '', 0) + ' → ' + fmt(res.risk, '', 0) +
                    ' (Δ ' + fmt(res.risk_delta, '', 1) + ') · <b>Spread:</b> ' +
                    fmt(base.ros_m_min, ' m/min', 2) + ' → ' + fmt(res.ros_m_min, ' m/min', 2) +
                    '<br><b>Assumptions:</b> ' + (s.assumptions || []).join(' ') +
                    '<br><b>Uncertainty:</b> ' + (s.uncertainty || '') + '</div></div>';
            }
            return '<div class="rec-item">' +
                '<div class="what">' + s.name + ' <span class="prio tag-status">not quantified</span></div>' +
                '<div class="why">' + (s.mechanism || s.reason || '') + '</div>' +
                '<div class="meta">' + (s.note || 'No effect size is invented.') + '</div></div>';
        }).join('') + '<div class="footer-note">MODELLED INTERVENTION SCENARIOS — never observed results.</div>';
    }

    // ------------------------------------------------------------------
    // Lessons from the past (/api/history)
    // ------------------------------------------------------------------
    function loadHistory() {
        if (!lastResult || !lastResult.location) return;
        var btn = el('historyBtn');
        btn.disabled = true;
        btn.textContent = 'Loading real history (ERA5 archive)…';
        var loc = lastResult.location;
        fetch(API + '/history?lat=' + loc.latitude + '&lon=' + loc.longitude + '&days=90')
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
            .then(function (res) {
                btn.disabled = false;
                btn.textContent = 'Reload history';
                if (!res.ok || res.body.error) {
                    el('historyBlock').innerHTML = '<span class="unavail">History unavailable: ' +
                        (res.body.error || res.ok) + '</span>';
                    return;
                }
                renderHistory(res.body);
            })
            .catch(function (err) {
                btn.disabled = false;
                btn.textContent = 'Load history for this location';
                el('historyBlock').innerHTML = '<span class="unavail">History request failed: ' + err + '</span>';
            });
    }

    function renderHistory(h) {
        var box = el('historyBlock');
        var lessons = h.lessons || [];
        var w = h.window || {};
        var html = '<div class="footer-note" style="margin-top:0;">Window: ' + w.start + ' → ' + w.end +
            ' (' + w.days + ' days) · ' + (h.high_risk_periods || []).length +
            ' high-risk period(s) detected. ' + (h.labels_note || '') + '</div>';
        if (!lessons.length) {
            html += '<p style="margin:.6rem 0 0;">No high-risk period (score ≥ 65) occurred in this window ' +
                'based on the real reanalysis.</p>';
        }
        html += lessons.map(function (l) {
            var p = l.period || {};
            var c = l.conditions || {};
            var s = l.hydrashield_score || {};
            var o = l.observed_fire || {};
            var recs = (l.would_recommend || []).map(function (r) {
                return '<div class="why">→ <span class="prio prio-' + r.priority + '">' + r.priority +
                    '</span> ' + r.what + ' <i>(' + r.label + ')</i></div>';
            }).join('');
            return '<div class="lesson-item">' +
                '<div class="what">' + p.start + ' → ' + p.end + ' (' + p.days + ' days)</div>' +
                '<div class="why">HydraShield risk (modelled): <b>' + s.value + '/100</b> on ' + s.peak_date +
                ' · FWI max ' + c.max_fwi + ' · mean wind ' + c.mean_wind_kmh + ' km/h · rain ' +
                c.total_rain_mm + ' mm <i>(' + c.label + ')</i></div>' +
                '<div class="why">Observed fire: ' + o.status + ' <i>(' + o.label + ')</i></div>' +
                recs +
                '<div class="meta">Interventions actually taken: ' +
                ((l.interventions_recorded || {}).note || 'unknown') + '</div>' +
                '</div>';
        }).join('');
        var fo = h.fire_observations || {};
        if (!fo.available) {
            html += '<div class="footer-note">Fire-observation layer unavailable — ' +
                (fo.reason || '') + '. Historical fire events are not shown; nothing is invented.</div>';
        }
        box.innerHTML = html;
    }

    function renderDrivers(r) {
        var fd = r.fire_danger || {};
        var w = r.weather || {};
        var a = r.analysis || {};
        var lc = r.landcover || {};
        var rows = [];
        if (fd.available) {
            rows.push(['Fire weather (FWI ' + fmt(fd.fwi, '', 1) + ', ' + fd.class + ')',
                'FFMC ' + fmt(fd.ffmc, '', 0) + ' · DMC ' + fmt(fd.dmc, '', 0) + ' · DC ' + fmt(fd.dc, '', 0)]);
        }
        rows.push(['Fuel moisture', fmt(a.fuel_moisture_baseline_pct, ' %', 1) + ' — ' + (a.fuel_moisture_source || '')]);
        rows.push(['Wind', fmt(w.wind_speed_kmh, ' km/h', 0)]);
        if (!lc.error) {
            rows.push(['Land cover', lc.dominant_label + ' (' + Math.round((lc.dominant_fraction || 0) * 100) + '% of area) — fuel model ' + (a.fire_spread || {}).fuel_model]);
        }
        var slope = (r.terrain || {}).slope_degrees;
        rows.push(['Terrain slope', fmt(slope, '°', 1)]);
        el('riskDrivers').innerHTML = rows.map(function (r2) {
            return '<div><span class="k">' + r2[0] + ':</span> ' + r2[1] + '</div>';
        }).join('');
    }

    function renderComparison(a) {
        var risk = a.risk || {};
        var base = risk.baseline, inter = risk.intervention;
        var bb = el('barBaseline'), bi = el('barIntervention');
        if (base === null || base === undefined) {
            bb.style.width = '60px'; bb.textContent = 'n/a';
            bi.style.width = '60px'; bi.textContent = 'n/a';
            el('riskReduction').textContent = '—';
        } else {
            bb.style.width = Math.max(base, 8) + '%';
            bb.textContent = 'Baseline ' + fmt(base, '', 0) + '/100';
            if (inter !== null && inter !== undefined) {
                bi.style.width = Math.max(inter, 8) + '%';
                bi.textContent = 'HydraShield ' + fmt(inter, '', 0) + '/100';
                el('riskReduction').textContent = fmt(risk.reduction_percent, ' %', 1);
            } else {
                bi.style.width = '60px'; bi.textContent = 'n/a';
                el('riskReduction').textContent = '—';
            }
        }
        el('waterUsed').textContent = fmt((a.wuer || {}).water_volume_m3, ' m³', 0);
        el('waterSaved').textContent = fmt(a.water_savings_pct, ' %', 1);
    }

    function renderSpread(a) {
        var fs = a.fire_spread || {};
        var el3 = (fs.spread_ellipse && fs.spread_ellipse.horizons || {})['3h'];
        var eli = (fs.spread_ellipse_intervention && fs.spread_ellipse_intervention.horizons || {})['3h'];
        var rows = [
            ['Rate of spread (current)', fmt(fs.ros_current_m_min, ' m/min', 1)],
            ['Rate of spread (with intervention)', fmt(fs.ros_intervention_m_min, ' m/min', 1)],
            ['Direction of spread', fmt((fs.spread_ellipse || {}).heading_deg, '°', 0)],
            ['3 h affected area (baseline)', el3 ? fmt(el3.area_km2, ' km²', 2) : '—'],
            ['3 h affected area (intervention)', eli ? fmt(eli.area_km2, ' km²', 2) : '—'],
            ['Evacuation safety margin', fmt((a.evacuation_safety_margin_min || {}).baseline, ' min', 0) +
                ' → ' + fmt((a.evacuation_safety_margin_min || {}).intervention, ' min', 0)]
        ];
        el('spreadSummary').innerHTML = rows.map(function (r) {
            return '<div><span class="k">' + r[0] + ':</span> ' + r[1] + '</div>';
        }).join('');
    }

    function renderFires(fires) {
        var box = el('firesBlock');
        if (!fires.available) {
            box.innerHTML = '<span class="unavail">Active-fire layer unavailable — ' +
                (fires.error || 'not configured') + '.</span> ' + chip('unavailable');
            return;
        }
        if (!fires.count) {
            box.innerHTML = 'No active fire detections within ' + fires.radius_km + ' km in the last ' +
                fires.days + ' days. ' + chip('observed');
            return;
        }
        var rows = fires.fires.slice(0, 20).map(function (f) {
            return '<div>' + (f.acq_date || '') + ' — FRP ' + fmt(f.frp_mw, ' MW', 1) +
                ' (' + fmt(f.lat, '', 3) + ', ' + fmt(f.lon, '', 3) + ')</div>';
        }).join('');
        box.innerHTML = '<div class="fires-list"><b>' + fires.count + ' detection(s)</b> within ' +
            fires.radius_km + ' km / ' + fires.days + ' days ' + chip('observed') + '<br>' + rows + '</div>';
    }

    function renderRecommendation(a, fd) {
        var risk = (a.risk || {});
        var score = risk.baseline;
        var title, text;
        if (score === null || score === undefined) {
            title = 'INSUFFICIENT DATA';
            text = 'Key inputs are unavailable; see the provenance table. No risk statement is made.';
        } else if (score >= 80) {
            title = 'EXTREME RISK — ACT NOW';
            text = 'Extreme fire danger. Activate all protection zones, pre-hydrate fuel corridors, brief crews and prepare evacuation communications.';
        } else if (score >= 65) {
            title = 'HIGH RISK — ACTIVATE PROTECTION';
            text = 'High fire danger. Activate HydraShield protection zones around critical assets and pre-position water resources.';
        } else if (score >= 45) {
            title = 'MODERATE RISK — PREPARE';
            text = 'Moderate fire danger. Prepare intervention teams, verify water availability and monitor the fire-danger trend.';
        } else {
            title = 'LOW RISK — MONITOR';
            text = 'Low fire danger. Standard monitoring is adequate.';
        }
        var drivers = [];
        if (fd.available && fd.fwi >= 21.3) drivers.push('elevated fire weather (FWI ' + fd.fwi.toFixed(0) + ')');
        if (a.fuel_moisture_baseline_pct !== null && a.fuel_moisture_baseline_pct !== undefined && a.fuel_moisture_baseline_pct < 15)
            drivers.push('dry fuel (' + a.fuel_moisture_baseline_pct + '% FMC)');
        el('recommendation').innerHTML = '<div class="risk-class-label cls-' + (risk.class || '') +
            '" style="display:inline-block;">' + title + '</div>' +
            '<p style="margin-top:.7rem;">' + text + '</p>' +
            (drivers.length ? '<p style="color:var(--muted);">Main causes: ' + drivers.join(' · ') + '</p>' : '');
    }

    function renderScience(r) {
        var a = r.analysis || {};
        var fd = r.fire_danger || {};
        var fs = a.fire_spread || {};
        var wuer = a.wuer || {};
        var html = '<div class="kv">';
        html += '<div><span class="k">Fuel model:</span> ' + (fs.fuel_model || '—') + '</div>';
        html += '<div><span class="k">MEFMI:</span> ' + fmt(a.mefmi_pct, ' %-pts', 1) + '</div>';
        html += '<div><span class="k">Probability of spread:</span> ' + fmt(a.probability_of_spread, '', 2) + '</div>';
        html += '<div><span class="k">ROS baseline (reference FMC):</span> ' + fmt(fs.ros_baseline_m_min, ' m/min', 2) + '</div>';
        html += '<div><span class="k">WUER:</span> ' + fmt(wuer.wuer, ' risk-pts/m³', 4) + '</div>';
        html += '<div><span class="k">Spread model:</span> simplified Rothermel-style ROS; ellipse = screening estimate</div>';
        html += '</div>';
        if (fd.available && fd.series) {
            html += '<h4 style="margin:1rem 0 .4rem;">FWI series (last days)</h4><div class="kv">' +
                fd.series.slice(-10).map(function (d) {
                    return '<div><span class="k">' + d.date + ':</span> FWI ' + d.fwi + ' (' + d.danger_class + ')</div>';
                }).join('') + '</div>';
            if (fd.forecast && fd.forecast.length) {
                html += '<h4 style="margin:1rem 0 .4rem;">FWI forecast ' + chip('forecast') + '</h4><div class="kv">' +
                    fd.forecast.map(function (d) {
                        return '<div><span class="k">' + d.date + ':</span> FWI ' + d.fwi + ' (' + d.danger_class + ')</div>';
                    }).join('') + '</div>';
            }
        }
        html += '<p class="footer-note">' + ((r.methodology || {}).note || '') + '</p>';
        el('scienceAnnex').innerHTML = html;
    }

    function renderProvenance(prov) {
        var rows = Object.keys(prov).map(function (k) {
            var p = prov[k] || {};
            return '<tr><td><b>' + k.replace(/_/g, ' ') + '</b></td><td>' + chip(p.kind) + '</td><td>' +
                (p.source || '—') + '</td><td>' + (p.acquired || '—') + '</td><td>' +
                (p.resolution || '—') + '</td><td style="color:var(--muted);">' + (p.limitations || '—') + '</td></tr>';
        }).join('');
        el('provTable').innerHTML =
            '<tr><th>Component</th><th>Kind</th><th>Source</th><th>Acquired</th><th>Resolution</th><th>Limitations</th></tr>' + rows;
    }

    // ------------------------------------------------------------------
    // Map (grouped, lazy layers; every popup carries provenance)
    // ------------------------------------------------------------------
    var osmFeaturesCache = null;
    var fireLayerDays = 5;

    function _resolutionControl() {
        var ctrl = L.control({ position: 'bottomright' });
        ctrl.onAdd = function () {
            var div = L.DomUtil.create('div');
            div.style.cssText = 'background:rgba(15,23,42,.82);color:#cbd5e1;font-size:.68rem;' +
                'padding:6px 9px;border-radius:8px;line-height:1.5;max-width:230px;';
            div.innerHTML = '<b>Layer resolutions</b><br>' +
                'Sentinel-2 NDMI · 10 m (micro)<br>' +
                'WorldCover · 10 m (micro)<br>' +
                'DEM terrain · 25–90 m (local)<br>' +
                'Weather / FWI · ~11 km (regional)<br>' +
                'OSM features · feature-level<br>' +
                'Population · 100 m grid (WorldPop, modelled)<br>' +
                'Smoke corridor · ~11 km NWP winds (screening envelope)<br>' +
                'Risk score · composite (not 10 m)';
            return div;
        };
        return ctrl;
    }

    function _firePopup(f) {
        return '<b>ACTIVE FIRE DETECTION</b><br>' +
            (f.source || f.sensor || 'NASA FIRMS') + (f.satellite ? ' · ' + f.satellite : '') + '<br>' +
            'Observed: ' + (f.acq_date || '—') + ' ' + (f.acq_time_utc || '') + ' UTC<br>' +
            'Confidence: ' + (f.confidence || '—') + ' · FRP: ' + fmt(f.frp_mw, ' MW', 1) +
            '<br><span style="color:#94a3b8">Observed satellite detection — not a confirmed fire perimeter.</span>';
    }

    function _buildFireLayer(evidence) {
        var group = L.layerGroup();
        (evidence.entries || []).forEach(function (entry) {
            (entry.detections || []).forEach(function (f) {
                f.source = entry.source_label || entry.source;
                group.addLayer(L.circleMarker([f.lat, f.lon], {
                    radius: 6, color: '#ff2d00', weight: 2,
                    fillColor: '#ff7a00', fillOpacity: 0.8
                }).bindPopup(_firePopup(f)));
            });
        });
        return group;
    }

    function _loadFireLayer(r, proxy) {
        fetch(API + '/fires?lat=' + r.location.latitude + '&lon=' + r.location.longitude +
              '&days=' + fireLayerDays)
            .then(function (res) { return res.json(); })
            .then(function (ev) {
                if (ev.status !== 'ok') {
                    el('mapNote').textContent = 'Fire observations unavailable — ' +
                        (((ev.entries || [])[0] || {}).reason || 'not configured');
                    el('fireDaysWrap').classList.add('hidden');
                    return;
                }
                var built = _buildFireLayer(ev);
                built.eachLayer(function (l) { proxy.addLayer(l); });
                el('mapNote').textContent = ev.disagreement ||
                    ('Fire detections from ' + ev.entries.filter(function (e) {
                        return e.status === 'ok'; }).map(function (e) { return e.source_label; }).join(' + '));
                el('fireDaysWrap').classList.remove('hidden');
            })
            .catch(function () { /* layer simply stays off */ });
    }

    var overlayGroups = {};
    var controlRef = null;

    function rebuildControl() {
        if (controlRef) { controlRef.remove(); controlRef = null; }
        controlRef = L.control.layers({}, overlayGroups, { collapsed: true }).addTo(map);
    }

    function _addOsmLayer(category, label, color) {
        // Lazy: fetch real OSM features only when the layer is first enabled.
        overlayGroups[label] = L.layerGroup();
        overlayGroups[label].on('add', function () {
            if (overlayGroups[label]._loaded || !lastResult) return;
            overlayGroups[label]._loaded = true;
            fetch(API + '/exposure-features?lat=' + lastResult.location.latitude +
                  '&lon=' + lastResult.location.longitude)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.error) return;
                    (data.features || []).forEach(function (f) {
                        if (f.category !== category) return;
                        overlayGroups[label].addLayer(L.circleMarker([f.lat, f.lon], {
                            radius: 6, color: color, weight: 2, fillOpacity: 0.7
                        }).bindPopup('<b>' + (f.name || label) + '</b><br>' + label +
                            '<br><span style="color:#94a3b8">OpenStreetMap (mapped feature; completeness varies)</span>'));
                    });
                })
                .catch(function () { /* layer stays empty, honestly */ });
        });
    }

    function renderMap(r) {
        var lat = r.location.latitude, lon = r.location.longitude;
        if (!map) {
            map = L.map('map').setView([lat, lon], 11);
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 18,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(map);
            _resolutionControl().addTo(map);
        } else {
            map.setView([lat, lon], 11);
            Object.keys(layers).forEach(function (k) {
                if (layers[k]) { map.removeLayer(layers[k]); layers[k] = null; }
            });
        }
        if (controlRef) { controlRef.remove(); controlRef = null; }
        overlayGroups = {};

        layers.marker = L.marker([lat, lon]).addTo(map)
            .bindPopup('<b>' + r.location.name + '</b>').openPopup();

        // ---- FIRE RISK: fire-danger grid (default on; real FWI per cell)
        var pad = 0.12;
        var gridUrl = API + '/risk-grid?south=' + (lat - pad) + '&west=' + (lon - pad) +
            '&north=' + (lat + pad) + '&east=' + (lon + pad) + '&n=6';
        el('mapNote').textContent = 'Loading fire-danger grid…';
        fetch(gridUrl).then(function (res) { return res.json(); }).then(function (g) {
            if (g.error) { el('mapNote').textContent = 'Fire-danger grid unavailable: ' + g.error; return; }
            var gridLayer = L.geoJSON(g, {
                style: function (f) {
                    var v = f.properties.risk;
                    return {
                        color: 'rgba(0,0,0,0.15)', weight: 1,
                        fillColor: v === null ? '#64748b' : riskColor(f.properties.risk_class),
                        fillOpacity: 0.35
                    };
                },
                onEachFeature: function (f, l) {
                    var p = f.properties;
                    l.bindPopup('<b>RISK CELL</b><br>HydraShield: ' +
                        (p.risk === null ? 'n/a' : p.risk + '/100 (' + p.risk_class + ')') +
                        '<br>FWI: ' + (p.fwi === null ? 'n/a' : p.fwi) +
                        ' · slope ' + p.slope_deg + '°' +
                        '<br><span style="color:#94a3b8">Composite indicator — not a probability of fire.<br>' +
                        'Cell ~' + g.grid.cell_size_km + ' km; FWI from real Open-Meteo data.</span>');
                }
            });
            layers.grid = gridLayer.addTo(map);
            overlayGroups['🔥 FIRE RISK — Fire-danger grid (~' + g.grid.cell_size_km + ' km cells)'] = gridLayer;
            rebuildControl();
            el('mapNote').textContent = 'Grid: FWI from Open-Meteo daily data (cell ~' +
                g.grid.cell_size_km + ' km), slope from DEM. Cached 1 h.';
        }).catch(function () { el('mapNote').textContent = 'Fire-danger grid request failed.'; });

        // ---- ENVIRONMENT: real Sentinel-2 NDMI scene window (default off)
        var sat = r.satellite || {};
        if (sat.ndmi_grid && sat.grid_bounds) {
            var b = sat.grid_bounds;
            var n = sat.ndmi_grid.length;
            var group = L.layerGroup();
            for (var i = 0; i < n; i++) {
                for (var j = 0; j < sat.ndmi_grid[i].length; j++) {
                    var v = sat.ndmi_grid[i][j];
                    if (v === null) continue;
                    var lat0 = b.lat_max - (i / n) * (b.lat_max - b.lat_min);
                    var lat1 = b.lat_max - ((i + 1) / n) * (b.lat_max - b.lat_min);
                    var lon0 = b.lon_min + (j / n) * (b.lon_max - b.lon_min);
                    var lon1 = b.lon_min + ((j + 1) / n) * (b.lon_max - b.lon_min);
                    group.addLayer(L.rectangle([[lat0, lon0], [lat1, lon1]], {
                        stroke: false, fillColor: ndmiColor(v), fillOpacity: 0.55
                    }).bindPopup('<b>SENTINEL-2</b><br>Observation: ' +
                        String(sat.observation_date || '').slice(0, 10) +
                        '<br>NDMI: ' + v.toFixed(2) + ' (fuel-moisture proxy)' +
                        '<br><span style="color:#94a3b8">10 m resolution · real scene pixels (OBSERVED)</span>'));
                }
            }
            layers.ndmi = group;
            overlayGroups['🌿 ENVIRONMENT — NDMI 10 m (' + String(sat.observation_date || '').slice(0, 10) + ')'] = group;
        }

        // ---- FIRE RISK: spread ellipse (screening)
        var fs = (r.analysis || {}).fire_spread || {};
        var se = fs.spread_ellipse;
        if (se && se.available && se.horizons && se.horizons['3h']) {
            layers.ellipse = L.polygon(
                ellipsePolygon(lat, lon, se.heading_deg, se.horizons['3h'].downwind_distance_m, se.horizons['3h'].max_width_m / 2),
                { color: '#ef4444', weight: 2, dashArray: '6 4', fillOpacity: 0.08 }
            ).addTo(map).bindPopup('<b>SPREAD SCENARIO (MODELLED)</b><br>3 h spread estimate<br>Area: ' +
                se.horizons['3h'].area_km2 + ' km²' +
                '<br><span style="color:#94a3b8">Screening estimate — no spotting, fuel breaks or suppression.</span>');
            overlayGroups['🔥 FIRE RISK — 3 h spread scenario (modelled)'] = layers.ellipse;
        }

        // ---- FIRE OBSERVATIONS: multi-source fire evidence (lazy, with day window)
        var fireProxy = L.layerGroup();
        fireProxy.on('add', function () { _loadFireLayer(r, fireProxy); });
        overlayGroups['🛰 FIRE OBSERVATIONS — NASA FIRMS (when configured)'] = fireProxy;

        // ---- EXPOSURE / INFRASTRUCTURE: real OSM features (lazy fetch)
        _addOsmLayer('hospitals', '🏥 EXPOSURE — Hospitals (OSM)', '#e11d48');
        _addOsmLayer('schools', '🏫 EXPOSURE — Schools (OSM)', '#7c3aed');
        _addOsmLayer('fire_stations', '🚒 INFRASTRUCTURE — Fire stations (OSM)', '#ea580c');
        _addOsmLayer('water_features', '💧 INFRASTRUCTURE — Water features (OSM)', '#0284c7');

        // ---- EXPOSURE: WorldPop population density grid (lazy fetch on first enable)
        var popLabel = '👥 EXPOSURE — Population density (WorldPop 100 m)';
        var popProxy = L.layerGroup();
        overlayGroups[popLabel] = popProxy;
        popProxy.on('add', function () {
            if (popProxy._loaded) return;
            popProxy._loaded = true;
            fetch(API + '/population-exposure?lat=' + lat + '&lon=' + lon)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    var cells = (data.population_grid || {}).cells || [];
                    if (data.error || !cells.length) {
                        // Honest unavailability: nothing fake is drawn.
                        el('mapNote').textContent = 'Population density grid unavailable — ' +
                            (data.error || 'no gridded population cells for this location') + '.';
                        return;
                    }
                    cells.forEach(function (c) {
                        popProxy.addLayer(L.rectangle([[c.south, c.west], [c.north, c.east]], {
                            stroke: false, fillColor: popColor(c.population), fillOpacity: 0.45
                        }).bindPopup('<b>Estimated population: ' + c.population + '</b>' +
                            '<br><span style="color:#94a3b8">WorldPop, reference year ' +
                            data.reference_year +
                            ' — modelled gridded estimate, not an exact count.</span>'));
                    });
                    // Re-register under the real reference year.
                    var fullLabel = '👥 EXPOSURE — Population density (WorldPop 100 m, ref ' +
                        data.reference_year + ')';
                    delete overlayGroups[popLabel];
                    overlayGroups[fullLabel] = popProxy;
                    rebuildControl();
                })
                .catch(function () {
                    el('mapNote').textContent = 'Population density grid request failed — layer left empty.';
                });
        });

        // ---- SMOKE: scenario transport corridor (modelled; default off)
        var smk = r.smoke_scenario || {};
        if (!smk.error && smk.status === 'ok' &&
            smk.transport && smk.transport.corridor_polygon) {
            var smokeGroup = L.layerGroup();
            smokeGroup.addLayer(L.polygon(smk.transport.corridor_polygon, {
                color: '#a855f7', weight: 1, dashArray: '4 4', fillOpacity: 0.12
            }));
            var traj = (smk.transport.trajectory || []).map(function (p) { return [p.lat, p.lon]; });
            if (traj.length > 1) {
                smokeGroup.addLayer(L.polyline(traj, {
                    color: '#a855f7', weight: 2, dashArray: '6 4'
                }).bindPopup('<b>' + (smk.mode_label || 'SMOKE SCENARIO (MODELLED)') + '</b><br>' +
                    'Dominant transport: ' + (smk.transport.dominant_transport_direction || '—') +
                    ' (' + fmt(smk.transport.dominant_transport_heading_deg, '°', 0) + ')' +
                    '<br>Confidence: ' + (smk.transport.confidence || '—') +
                    '<br><span style="color:#94a3b8">' + (smk.disclaimer || '') + '</span>'));
            }
            overlayGroups['💨 SMOKE — Scenario transport corridor (modelled)'] = smokeGroup;
        }

        rebuildControl();
    }

    function popColor(n) {
        // Estimated people per 100 m grid cell (WorldPop): pale -> dark red
        if (n < 50) return '#fef3c7';
        if (n < 500) return '#fcd34d';
        if (n < 2000) return '#f97316';
        return '#b91c1c';
    }

    function ndmiColor(v) {
        // NDMI -1 (dry) .. +1 (moist): brown -> green
        var t = Math.max(0, Math.min(1, (v + 0.2) / 0.8));
        var r = Math.round(180 - t * 150);
        var g = Math.round(90 + t * 110);
        return 'rgb(' + r + ',' + g + ',60)';
    }

    function ellipsePolygon(lat, lon, headingDeg, semiMajorM, semiMinorM) {
        var pts = [];
        var rad = headingDeg * Math.PI / 180;
        // Ellipse centred half a semi-major axis downwind of ignition.
        var cy = lat + (semiMajorM / 2) * Math.cos(rad) / 110540;
        var cx = lon + (semiMajorM / 2) * Math.sin(rad) / (111320 * Math.cos(lat * Math.PI / 180));
        for (var k = 0; k < 48; k++) {
            var t = (k / 48) * 2 * Math.PI;
            var ex = semiMinorM * Math.cos(t);
            var ey = semiMajorM * Math.sin(t);
            var rx = ex * Math.sin(rad) + ey * Math.cos(rad);
            var ry = ex * Math.cos(rad) - ey * Math.sin(rad);
            pts.push([cy + ry / 110540, cx + rx / (111320 * Math.cos(lat * Math.PI / 180))]);
        }
        return pts;
    }

    // ------------------------------------------------------------------
    // Watches
    // ------------------------------------------------------------------
    function setupWatch() {
        el('watchBtn').addEventListener('click', function () {
            if (!lastResult) return;
            var email = el('watchEmail').value.trim();
            var threshold = parseFloat(el('watchThreshold').value);
            var st = el('watchStatus');
            if (!email || email.indexOf('@') < 0) { st.textContent = 'Enter a valid email address.'; return; }
            st.textContent = 'Registering watch…';
            fetch(API + '/watch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lat: lastResult.location.latitude,
                    lon: lastResult.location.longitude,
                    email: email,
                    threshold_risk: threshold
                })
            }).then(function (r) { return r.json(); }).then(function (j) {
                if (j.error) { st.textContent = 'Watch failed: ' + j.error; return; }
                st.innerHTML = 'Watch created ✓ — alerts are checked periodically. Save this id to cancel: <code>' +
                    j.watch.id + '</code>';
            }).catch(function (e) { st.textContent = 'Watch request failed: ' + e; });
        });
    }

    // ------------------------------------------------------------------
    // Boot
    // ------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', function () {
        el('analyzeBtn').addEventListener('click', function () {
            var q = el('locationInput').value.trim();
            if (q) analyze(q);
        });
        el('locationInput').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { var q = e.target.value.trim(); if (q) analyze(q); }
        });
        el('historyBtn').addEventListener('click', loadHistory);
        el('fireDays').addEventListener('change', function (e) {
            fireLayerDays = parseInt(e.target.value, 10) || 5;
            // Refetch the real fire layer into its proxy (if it is enabled).
            Object.keys(overlayGroups).forEach(function (k) {
                if (k.indexOf('FIRE OBSERVATIONS') !== -1 && lastResult) {
                    var proxy = overlayGroups[k];
                    proxy.clearLayers();
                    _loadFireLayer(lastResult, proxy);
                }
            });
        });
        el('cancelBtn').addEventListener('click', function () {
            // Client-side cancel: the server-side job finishes and its result
            // is cached — nothing is lost or fabricated.
            stopPolling();
            currentJobId = null;
            el('progressPanel').classList.add('hidden');
            el('analyzeBtn').disabled = false;
            notice('Analysis cancelled. The server completes and caches finished analyses — ' +
                   'running the same search again will reuse them.', false);
        });
        setupWatch();
        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q) {
            el('locationInput').value = q;
            analyze(q);
        }
    });
})();
