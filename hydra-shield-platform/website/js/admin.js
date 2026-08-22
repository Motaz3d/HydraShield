/* HydraShield — Commercial Center (admin.html).
 *
 * Admin-only: GET /api/v2/admin/intel (cookie session; 401 shows a plain
 * sign-in hint, 403 the tier message). Sections: TODAY / CUSTOMERS /
 * MARKETING / AI COPILOT / ATTENTION / FUNNEL / targets / prospects /
 * relationships. Aggregate counts only — never individual visitors.
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

        el('prospectsBlock').innerHTML = ws.available
            ? tableRows(ws.leads || [], [
                { label: 'Organization', get: function (l) { return l.organization; } },
                { label: 'Segment', get: function (l) { return l.segment; } },
                { label: 'Country', get: function (l) { return l.country; } },
                { label: 'Priority', get: function (l) { return l.priority; } },
                { label: 'Status', get: function (l) { return l.outreach_status; } },
                { label: 'Next action', get: function (l) { return l.next_action; } },
            ])
            : '<div class="notice notice-empty">' + esc(ws.note || 'Workspace unavailable.') + '</div>';

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
