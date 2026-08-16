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
    // Analysis
    // ------------------------------------------------------------------
    function analyze(query) {
        var btn = el('analyzeBtn');
        btn.disabled = true;
        notice('Fetching real data (satellite, weather, terrain, fire danger)… this can take up to a minute on first request for a new area.');
        el('report').classList.add('hidden');

        var url = API + '/analyze?';
        if (/^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$/.test(query)) {
            var parts = query.split(',');
            url += 'lat=' + encodeURIComponent(parts[0].trim()) + '&lon=' + encodeURIComponent(parts[1].trim());
        } else {
            url += 'location=' + encodeURIComponent(query);
        }

        fetch(url)
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
            .then(function (res) {
                btn.disabled = false;
                if (!res.ok || res.body.error) {
                    notice(res.body.error || ('Request failed (' + res.ok + ')'), true);
                    return;
                }
                hideNotice();
                lastResult = res.body;
                render(res.body);
            })
            .catch(function (err) {
                btn.disabled = false;
                notice('Analysis request failed: ' + err, true);
            });
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
        renderProactive(r.recommendations || []);
        renderActionPlan(r.action_plan || {});
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
    // Map
    // ------------------------------------------------------------------
    function renderMap(r) {
        var lat = r.location.latitude, lon = r.location.longitude;
        if (!map) {
            map = L.map('map').setView([lat, lon], 11);
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 18,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(map);
        } else {
            map.setView([lat, lon], 11);
            ['grid', 'ndmi', 'fires', 'ellipse', 'marker'].forEach(function (k) {
                if (layers[k]) { map.removeLayer(layers[k]); layers[k] = null; }
            });
        }

        layers.marker = L.marker([lat, lon]).addTo(map)
            .bindPopup('<b>' + r.location.name + '</b>').openPopup();

        var overlays = {};

        // Risk grid (GeoJSON cells)
        var pad = 0.12;
        var gridUrl = API + '/risk-grid?south=' + (lat - pad) + '&west=' + (lon - pad) +
            '&north=' + (lat + pad) + '&east=' + (lon + pad) + '&n=6';
        el('mapNote').textContent = 'Loading fire-danger grid…';
        fetch(gridUrl).then(function (res) { return res.json(); }).then(function (g) {
            if (g.error) { el('mapNote').textContent = 'Fire-danger grid unavailable: ' + g.error; return; }
            layers.grid = L.geoJSON(g, {
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
                    l.bindPopup('Risk: ' + (p.risk === null ? 'n/a' : p.risk + '/100 (' + p.risk_class + ')') +
                        '<br>FWI: ' + (p.fwi === null ? 'n/a' : p.fwi) + '<br>Slope: ' + p.slope_deg + '°');
                }
            });
            overlays['Fire danger grid (FWI, ' + g.grid.cell_size_km + ' km cells)'] = layers.grid;
            layers.grid.addTo(map);
            refreshControl(overlays);
            el('mapNote').textContent = 'Grid: FWI from Open-Meteo daily data (cell size ~' +
                g.grid.cell_size_km + ' km), slope from DEM. Cached 1 h.';
        }).catch(function () { el('mapNote').textContent = 'Fire-danger grid request failed.'; });

        // NDMI overlay from the real Sentinel-2 scene window
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
                    }).bindPopup('NDMI ' + v.toFixed(2) + ' (fuel moisture proxy)'));
                }
            }
            layers.ndmi = group;
            overlays['Vegetation moisture — Sentinel-2 NDMI (' + (sat.observation_date || '').slice(0, 10) + ')'] = group;
        }

        // FIRMS fires
        var fires = r.active_fires || {};
        if (fires.available && fires.count) {
            var fg = L.layerGroup();
            fires.fires.forEach(function (f) {
                fg.addLayer(L.circleMarker([f.lat, f.lon], {
                    radius: 6, color: '#ff2d00', weight: 2, fillColor: '#ff7a00', fillOpacity: 0.8
                }).bindPopup('Active fire<br>' + (f.acq_date || '') + '<br>FRP ' + fmt(f.frp_mw, ' MW', 1)));
            });
            layers.fires = fg.addTo(map);
            overlays['Active fires (NASA FIRMS)'] = fg;
        }

        // Spread ellipse (3 h, baseline)
        var fs = (r.analysis || {}).fire_spread || {};
        var se = fs.spread_ellipse;
        if (se && se.available && se.horizons && se.horizons['3h']) {
            layers.ellipse = L.polygon(
                ellipsePolygon(lat, lon, se.heading_deg, se.horizons['3h'].downwind_distance_m, se.horizons['3h'].max_width_m / 2),
                { color: '#ef4444', weight: 2, dashArray: '6 4', fillOpacity: 0.08 }
            ).addTo(map).bindPopup('3 h spread estimate (screening)<br>Area: ' + se.horizons['3h'].area_km2 + ' km²');
            overlays['3 h spread estimate'] = layers.ellipse;
        }

        refreshControl(overlays);
    }

    var layerControl = null;
    function refreshControl(overlays) {
        if (layerControl) { map.removeControl(layerControl); layerControl = null; }
        var any = Object.keys(overlays).length > 0;
        if (any) layerControl = L.control.layers(null, overlays, { collapsed: false }).addTo(map);
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
        setupWatch();
        var params = new URLSearchParams(location.search);
        var q = params.get('location');
        if (q) {
            el('locationInput').value = q;
            analyze(q);
        }
    });
})();
