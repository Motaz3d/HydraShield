/* Talaix — Commercial Center (admin.html).
 *
 * Admin-only: GET /api/v2/admin/intel (cookie session; 401 shows a plain
 * sign-in hint, 403 the tier message). Sections: TODAY / progress board /
 * prospect map / inbound leads / AI COPILOT / hazard opportunities /
 * funding / campaigns / funnel / targets / prospects / relationships /
 * ATTENTION. Aggregate counts only — never individual visitors.
 */
(function () {
    'use strict';

    var esc = HS.esc, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function status(kind, msg) {
        el('statusArea').innerHTML = msg
            ? '<div class="notice notice-' + kind + '">' + msg + '</div>'
            : '';
    }

    function postJSON(url, payload) {
        return fetchJSON(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    }

    function card(title, value, note) {
        return '<div class="story-card"><h3>' + esc(title) + '</h3>' +
            '<p style="font-size:1.6rem;font-weight:700;margin:4px 0;">' + esc(value) + '</p>' +
            (note ? '<p class="muted small">' + esc(note) + '</p>' : '') + '</div>';
    }

    function chips(obj) {
        return '<div class="badge-row">' +
            Object.keys(obj).map(function (k) {
                return '<span class="chip chip-observed">' + esc(k.replace(/_/g, ' ')) +
                    ': ' + esc(obj[k]) + '</span>';
            }).join('') + '</div>';
    }

    function tableRows(items, columns) {
        if (!items.length) {
            return '<div class="notice notice-empty">Nothing recorded yet.</div>';
        }
        return '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            columns.map(function (c) { return '<th>' + esc(c.label) + '</th>'; }).join('') +
            '</tr></thead><tbody>' +
            items.map(function (item) {
                return '<tr>' + columns.map(function (c) {
                    return '<td>' + esc(c.get(item) == null ? '—' : c.get(item)) + '</td>';
                }).join('') + '</tr>';
            }).join('') + '</tbody></table></div>';
    }

    function renderCampaignPerf(d) {
        if (!d || !d.campaigns || !d.campaigns.length) {
            el('campaignPerfBlock').innerHTML = '<div class="notice notice-empty">No campaign data yet.</div>';
            return;
        }
        var html = '<p class="muted small">Overall engagement: ' +
            Math.round((d.overall_engagement_rate || 0) * 100) + '% · ' +
            d.total_engaged_leads + ' engaged / ' + d.total_targeted_leads + ' targeted across ' +
            d.total_campaigns + ' campaigns</p>';

        // Recommendations first
        if (d.recommendations && d.recommendations.length) {
            html += '<div class="badge-row" style="margin-bottom:12px;">';
            d.recommendations.forEach(function (rec) {
                var cls = rec.type === 'boost' ? 'chip-champion' : 'chip-observed';
                html += '<span class="chip ' + cls + '">' + esc(rec.campaign_name) +
                    ': ' + esc(rec.reason) + '</span>';
            });
            html += '</div>';
        }

        // Campaign table
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Campaign</th><th>Target leads</th><th>Engaged</th><th>Rate</th>' +
            '<th>Funnel</th><th>30d activity</th><th>Top countries</th></tr></thead><tbody>';

        d.campaigns.forEach(function (c) {
            var funnelStr = Object.keys(c.funnel || {})
                .map(function (k) { return esc(k.replace(/_/g, ' ')) + ': ' + c.funnel[k]; })
                .join(' · ');
            var countriesStr = (c.top_countries || []).slice(0, 3)
                .map(function (co) { return esc(co.country) + ' (' + co.count + ')'; })
                .join(', ');
            html += '<tr>' +
                '<td><strong>' + esc(c.id) + '</strong> ' + esc(c.name) + '</td>' +
                '<td>' + c.total_target_leads + '</td>' +
                '<td>' + c.engaged_count + '</td>' +
                '<td>' + Math.round(c.engagement_rate * 100) + '%</td>' +
                '<td style="font-size:0.85rem;">' + funnelStr + '</td>' +
                '<td>' + c.recent_interactions + '</td>' +
                '<td style="font-size:0.85rem;">' + countriesStr + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        el('campaignPerfBlock').innerHTML = html;
    }

    // ------------------------------------------------------------------
    // Progress board — what is done vs what must happen next
    // ------------------------------------------------------------------

    function boardItem(title, sub) {
        return '<div class="board-item"><strong>' + esc(title) + '</strong>' +
            (sub ? '<div class="muted">' + esc(sub) + '</div>' : '') + '</div>';
    }

    function renderBoard(d) {
        var cp = d.copilot || {};
        var m = d.marketing || {};
        var t = d.today || {};

        var done = [];
        (cp.interactions_today || []).forEach(function (i) {
            done.push(boardItem(i.organization + ' — ' + (i.type || 'interaction'),
                i.summary || ''));
        });
        if ((t.reports || 0) > 0) {
            done.push(boardItem(t.reports + ' report(s) generated today', ''));
        }
        if ((t.new_users || 0) > 0) {
            done.push(boardItem(t.new_users + ' new account(s) today', ''));
        }
        if ((m.campaigns || 0) > 0) {
            done.push(boardItem(m.campaigns + ' campaign(s) defined and running',
                m.email_queued + ' outreach draft(s) queued for human review'));
        }
        if (!done.length) done.push(boardItem('No completed actions recorded yet today', ''));

        var next = [];
        (cp.followups_due || []).forEach(function (f) {
            next.push(boardItem('Follow up: ' + f.organization,
                'due ' + (f.next_followup || '—') + ' · ' + (f.next_action || '')));
        });
        (cp.publish_queue || []).forEach(function (p) {
            next.push(boardItem('Publish: ' + p, 'content draft awaiting review'));
        });
        if ((m.email_queued || 0) > 0) {
            next.push(boardItem('Review ' + m.email_queued + ' queued outreach draft(s)',
                'nothing sends automatically — human gate'));
        }
        if (!next.length) next.push(boardItem('Nothing pending — the queue is clear', ''));

        el('boardBlock').innerHTML =
            '<div class="board-2col">' +
            '<div class="board-col"><h3>✅ Done</h3>' + done.join('') + '</div>' +
            '<div class="board-col"><h3>⏭ Next</h3>' + next.join('') + '</div>' +
            '</div>';
    }

    // ------------------------------------------------------------------
    // Prospect map — country-level lead positions, priority-coloured
    // ------------------------------------------------------------------

    var leadsMap = null;

    function priorityColor(p) {
        return { high: '#ef4444', medium: '#f59e0b', low: '#64748b' }[p] || '#64748b';
    }

    function renderLeadsMap(d) {
        var points = d.leads_map || [];
        el('leadsMapNote').textContent = d.leads_map_note ||
            'Country-level positions; rule-based score (priority + urgency + outreach progress).';
        if (!window.L) {
            el('leadsMap').innerHTML =
                '<div class="notice notice-error">Map library could not be loaded.</div>';
            return;
        }
        if (!leadsMap) {
            leadsMap = L.map('leadsMap', { scrollWheelZoom: false }).setView([38, 12], 2);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors', maxZoom: 8
            }).addTo(leadsMap);
        }
        points.forEach(function (p) {
            var marker = L.circleMarker([p.lat, p.lon], {
                radius: 7 + Math.min(6, (p.score || 0) / 20),
                color: '#fff', weight: 1.5,
                fillColor: priorityColor(p.priority), fillOpacity: 0.85
            });
            marker.bindPopup(
                '<div class="lead-pop"><strong>' + esc(p.organization) + '</strong>' +
                '<table>' +
                '<tr><th>Segment</th><td>' + esc((p.segment || '').replace(/_/g, ' ')) + '</td></tr>' +
                '<tr><th>Priority</th><td>' + esc(p.priority || '—') + ' · score ' + esc(p.score) + '/100</td></tr>' +
                '<tr><th>Status</th><td>' + esc((p.outreach_status || '').replace(/_/g, ' ')) + '</td></tr>' +
                '<tr><th>Product</th><td>' + esc((p.recommended_product || '—').replace(/_/g, ' ')) + '</td></tr>' +
                '<tr><th>Next</th><td>' + esc(p.next_action || '—') + '</td></tr>' +
                '</table></div>');
            marker.addTo(leadsMap);
        });
        if (!points.length) {
            el('leadsMapNote').textContent =
                'No mappable prospects yet (workspace unavailable or no known countries).';
        }
    }

    // ------------------------------------------------------------------
    // Inbound leads — contact-form messages with a pipeline status
    // ------------------------------------------------------------------

    function loadContacts() {
        fetchJSON(API + '/v2/admin/contacts').then(function (res) {
            if (!res.ok) {
                el('contactsBlock').innerHTML =
                    '<div class="notice notice-empty">No inbound messages yet.</div>';
                return;
            }
            renderContacts(res.body.contacts || []);
        }).catch(function () {
            el('contactsBlock').innerHTML =
                '<div class="notice notice-error">Inbound leads could not be loaded.</div>';
        });
    }

    function renderContacts(list) {
        if (!list.length) {
            el('contactsBlock').innerHTML =
                '<div class="notice notice-empty">No inbound messages yet — the contact ' +
                'form feeds this inbox automatically.</div>';
            return;
        }
        el('contactsBlock').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>When</th><th>Name</th><th>Organization</th><th>Email</th>' +
            '<th>Interest</th><th>Message</th><th>Status</th><th></th>' +
            '</tr></thead><tbody>' +
            list.map(function (c) {
                return '<tr>' +
                    '<td>' + esc((c.created_at || '').slice(0, 10)) + '</td>' +
                    '<td>' + esc(c.name || '—') + '</td>' +
                    '<td>' + esc(c.organization || '—') + '</td>' +
                    '<td><a class="text-link" href="mailto:' + esc(c.email) + '">' +
                        esc(c.email) + '</a></td>' +
                    '<td>' + esc(c.interest || '—') + '</td>' +
                    '<td class="muted small">' + esc((c.message || '').slice(0, 120)) +
                        ((c.message || '').length > 120 ? '…' : '') + '</td>' +
                    '<td>' + esc(c.status) + '</td>' +
                    '<td><select data-contact-status="' + c.id + '">' +
                    ['new', 'contacted', 'qualified', 'closed'].map(function (s) {
                        return '<option value="' + s + '"' +
                            (s === c.status ? ' selected' : '') + '>' + s + '</option>';
                    }).join('') + '</select></td>' +
                    '</tr>';
            }).join('') + '</tbody></table></div>';
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-contact-status]'), function (sel) {
                sel.addEventListener('change', function () {
                    fetchJSON(API + '/v2/admin/contacts/' + sel.getAttribute('data-contact-status'), {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ status: sel.value })
                    }).then(function (res) {
                        if (!res.ok) status('error', 'Status update failed.');
                    });
                });
            });
    }

    // ------------------------------------------------------------------
    // Prospects — the working pipeline table (marketing operations)
    // ------------------------------------------------------------------

    var OUTREACH_STATUSES = ['researched', 'qualified', 'draft_prepared',
                             'contacted', 'responded', 'opportunity'];
    var LEAD_STATUSES = ['open', 'won', 'lost'];

    function statusSelect(kind, slug, current, options) {
        return '<select data-lead-' + kind + '="' + esc(slug) + '">' +
            options.map(function (s) {
                return '<option value="' + s + '"' + (s === current ? ' selected' : '') +
                    '>' + s.replace(/_/g, ' ') + '</option>';
            }).join('') + '</select>';
    }

    function renderProspects(leads) {
        if (!leads.length) {
            el('prospectsBlock').innerHTML =
                '<div class="notice notice-empty">No prospects yet.</div>';
            return;
        }
        el('prospectsBlock').innerHTML =
            '<p class="muted small">Work the pipeline directly: change a stage, ' +
            'mark won/lost, or log an interaction — every change is audited.</p>' +
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Organization</th><th>Segment</th><th>Country</th><th>Priority</th>' +
            '<th>Outreach</th><th>Deal</th><th>Next action</th><th></th>' +
            '</tr></thead><tbody>' +
            leads.map(function (l) {
                return '<tr>' +
                    '<td><strong>' + esc(l.organization) + '</strong></td>' +
                    '<td>' + esc((l.segment || '').replace(/_/g, ' ')) + '</td>' +
                    '<td>' + esc(l.country || '—') + '</td>' +
                    '<td>' + esc(l.priority || '—') + '</td>' +
                    '<td>' + statusSelect('outreach', l.id, l.outreach_status || 'researched', OUTREACH_STATUSES) + '</td>' +
                    '<td>' + statusSelect('deal', l.id, l.status || 'open', LEAD_STATUSES) + '</td>' +
                    '<td class="muted small">' + esc(l.next_action || '—') + '</td>' +
                    '<td><button class="btn-action btn-quiet" data-lead-note="' + esc(l.id) + '" ' +
                        'data-org="' + esc(l.organization) + '">+ Note</button></td>' +
                    '</tr>';
            }).join('') + '</tbody></table></div>';

        Array.prototype.forEach.call(
            document.querySelectorAll('[data-lead-outreach]'), function (sel) {
                sel.addEventListener('change', function () {
                    patchLead(sel.getAttribute('data-lead-outreach'),
                              { outreach_status: sel.value });
                });
            });
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-lead-deal]'), function (sel) {
                sel.addEventListener('change', function () {
                    patchLead(sel.getAttribute('data-lead-deal'),
                              { status: sel.value });
                });
            });
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-lead-note]'), function (btn) {
                btn.addEventListener('click', function () {
                    var summary = window.prompt(
                        'Log an interaction with ' + btn.getAttribute('data-org') +
                        ' (e.g. "sent the wildfire screening proposal")');
                    if (!summary || !summary.trim()) return;
                    postJSON(API + '/v2/admin/leads/' +
                             encodeURIComponent(btn.getAttribute('data-lead-note')) +
                             '/interactions',
                             { type: 'note', summary: summary.trim() })
                        .then(function (res) {
                            if (!res.ok) {
                                status('error', (res.body && res.body.error) || 'Could not log the interaction.');
                                return;
                            }
                            status('info', 'Interaction logged.');
                            refreshIntel();
                        });
                });
            });
    }

    function patchLead(slug, fields) {
        fetchJSON(API + '/v2/admin/leads/' + encodeURIComponent(slug), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(fields)
        }).then(function (res) {
            if (!res.ok) {
                status('error', (res.body && res.body.error) || 'Update failed.');
                return;
            }
            status('info', 'Pipeline updated.');
            refreshIntel();
        });
    }

    function refreshIntel() {
        fetchJSON(API + '/v2/admin/intel').then(function (res) {
            if (res.ok) { render(res.body); renderBoard(res.body); renderLeadsMap(res.body); }
        });
    }

    function render(d) {
        el('adminView').classList.remove('hidden');
        var t = d.today || {};
        var cp = d.copilot || {};
        var ws = d.workspace || {};

        el('todayCards').innerHTML =
            card('Visitors', t.visitors, 'pseudonymous sessions') +
            card('New accounts', t.new_users) +
            card('Repeat users', t.repeat_users, 'seen on >1 day') +
            card('Analyses', t.analyses) +
            card('Reports', t.reports) +
            card('Saved locations', t.saved_locations) +
            card('Monitoring rules', t.monitoring_rules) +
            card('SMS interest', t.sms_interest) +
            card('Subscriptions', t.subscriptions) +
            card('New leads today', (cp.new_leads_today || []).length) +
            card('Interactions today', (cp.interactions_today || []).length);

        // Who to contact now — the daily centerpiece
        el('contactNowBlock').innerHTML = tableRows(cp.contact_now || [], [
            { label: 'Organization', get: function (l) { return l.organization; } },
            { label: 'Segment', get: function (l) { return (l.segment || '').replace(/_/g, ' '); } },
            { label: 'Why now', get: function (l) { return (l.why || '').slice(0, 140); } },
            { label: 'Hazards', get: function (l) { return (l.hazards || []).join(', '); } },
            { label: 'Product', get: function (l) { return l.service; } },
            { label: 'Message', get: function (l) { return (l.message || '').slice(0, 120); } },
            { label: 'Next action', get: function (l) { return l.next_action; } },
        ]);

        el('followupsBlock').innerHTML = tableRows(cp.followups_due || [], [
            { label: 'Organization', get: function (l) { return l.organization; } },
            { label: 'Due', get: function (l) { return l.next_followup; } },
            { label: 'Action', get: function (l) { return l.next_action; } },
        ]);

        // Hazard opportunities
        var areas = d.hazard_areas || [];
        var opps = d.hazard_opportunities || [];
        el('hazardBlock').innerHTML =
            (areas.length
                ? '<p class="muted small">Elevated now: ' +
                  areas.map(function (a) { return esc(a.area) + ' (' + esc(a.risk_class) + ')'; }).join(' · ') + '</p>'
                : '<p class="muted small">No elevated areas in the current snapshot.</p>') +
            tableRows(opps.slice(0, 12), [
                { label: 'Organization', get: function (o) { return o.organization; } },
                { label: 'Segment', get: function (o) { return o.segment_label; } },
                { label: 'Area', get: function (o) { return o.area; } },
                { label: 'Match', get: function (o) { return o.match; } },
                { label: 'Product fit', get: function (o) { return (o.product_fit || []).join(', '); } },
                { label: 'Next action', get: function (o) { return o.next_action; } },
            ]);

        // Funding & procurement
        var fr = d.funding_radar || {};
        var prog = (fr.programmes || []).map(function (p) {
            return { what: p.name, kind: (p.funding_type || []).join(', '),
                     geo: p.jurisdiction, deadline: p.deadline,
                     checked: p.date_checked, next: p.next_action };
        });
        var eu = (fr.eu_funding || []).map(function (r) {
            return { what: (r.call || r.programme), kind: 'EU project',
                     geo: r.institution, deadline: r.deadline,
                     checked: r.date_checked, next: r.next_action };
        });
        var proc = (fr.procurement || []).map(function (r) {
            return { what: r.title, kind: r.type, geo: r.geography,
                     deadline: r.deadline, checked: r.date_checked, next: r.next_action };
        });
        el('fundingBlock').innerHTML =
            '<p class="muted small">' + prog.length + ' programmes · ' + eu.length +
            ' EU project records · ' + proc.length + ' tenders</p>' +
            tableRows(prog.concat(eu, proc), [
                { label: 'Programme / record', get: function (r) { return r.what; } },
                { label: 'Type', get: function (r) { return r.kind; } },
                { label: 'Geography', get: function (r) { return r.geo; } },
                { label: 'Deadline', get: function (r) { return r.deadline; } },
                { label: 'Checked', get: function (r) { return r.checked; } },
                { label: 'Next action', get: function (r) { return r.next; } },
            ]);

        // Campaigns
        el('campaignsBlock').innerHTML = tableRows(cp.campaigns || [], [
            { label: 'ID', get: function (c) { return c.id; } },
            { label: 'Campaign', get: function (c) { return c.name; } },
            { label: 'CTA', get: function (c) { return c.cta; } },
            { label: 'Goal', get: function (c) { return c.conversion_goal; } },
        ]);

        // Funnel
        var f = d.funnel_stages || {};
        el('funnelBlock').innerHTML =
            '<div class="badge-row">' +
            Object.keys(f).map(function (k) {
                return '<span class="chip chip-modelled">' + esc(k.replace(/_/g, ' ')) +
                    ': ' + esc(f[k]) + '</span>';
            }).join(' → ') + '</div>';

        // Targets vs actual
        el('targetsBlock').innerHTML = tableRows(
            Object.keys(d.targets || {}).map(function (k) {
                var tg = d.targets[k];
                return { metric: k.replace(/_/g, ' '), target: tg.target,
                         actual: tg.actual,
                         progress: Math.min(100, Math.round(100 * tg.actual / tg.target)) + '%' };
            }),
            [{ label: 'Metric', get: function (r) { return r.metric; } },
             { label: 'Target', get: function (r) { return r.target; } },
             { label: 'Actual', get: function (r) { return r.actual; } },
             { label: 'Progress', get: function (r) { return r.progress; } }]
        );

        el('customersBlock').innerHTML = chips(d.customers || {});
        el('marketingBlock').innerHTML = chips(d.marketing || {});

        // Priority markets
        var pm = d.priority_markets || {};
        el('marketsBlock').innerHTML = Object.keys(pm).map(function (label) {
            var leads = pm[label];
            return '<h3 style="margin:0 0 6px;">' + esc(label) + ' <span class="muted small">(' +
                leads.length + ')</span></h3>' +
                tableRows(leads.slice(0, 6), [
                    { label: 'Organization', get: function (l) { return l.organization; } },
                    { label: 'Country', get: function (l) { return l.country; } },
                    { label: 'Product', get: function (l) { return l.product; } },
                    { label: 'Priority', get: function (l) { return l.priority; } },
                ]);
        }).join('') || '<div class="notice notice-empty">No priority-market leads yet.</div>';

        // Prospects — the working table: pipeline selects + interaction log
        if (ws.available) {
            renderProspects(ws.leads || []);
        } else {
            el('prospectsBlock').innerHTML =
                '<div class="notice notice-empty">' + esc(ws.note || 'Workspace unavailable.') + '</div>';
        }

        el('relationshipsBlock').innerHTML = ws.available
            ? tableRows(ws.relationships || [], [
                { label: 'Date', get: function (i) { return i.date; } },
                { label: 'Organization', get: function (i) { return i.organization; } },
                { label: 'Type', get: function (i) { return i.type; } },
                { label: 'Summary', get: function (i) { return i.summary; } },
            ])
            : '';

        var at = d.attention || {};
        el('attentionBlock').innerHTML =
            '<p class="muted">High-priority prospects: ' +
            esc((at.high_priority_prospects || []).length) + ' · SMS delivery configured: ' +
            esc(at.sms_delivery_configured ? 'yes' : 'no') + '</p>';
    }

    fetchJSON(API + '/v2/admin/intel').then(function (res) {
        if (res.status === 401) {
            status('info', 'Sign in with an operator account on the ' +
                   '<a href="account.html">account page</a> first.');
            return;
        }
        if (res.status === 403) {
            status('warn', esc((res.body && res.body.error) ||
                   'This area requires the admin tier.'));
            return;
        }
        if (!res.ok) {
            status('error', 'Commercial Center unavailable.');
            return;
        }
        status('', '');
        render(res.body);
        renderBoard(res.body);
        renderLeadsMap(res.body);
        loadContacts();
    }).catch(function () {
        status('error', 'Commercial Center could not be reached.');
    });

    // Load campaign performance separately
    fetchJSON(API + '/v2/admin/campaigns').then(function (res) {
        if (res.ok && res.body) {
            renderCampaignPerf(res.body);
        }
    }).catch(function () {
        el('campaignPerfBlock').innerHTML =
            '<div class="notice notice-empty">Campaign performance unavailable.</div>';
    });
})();
