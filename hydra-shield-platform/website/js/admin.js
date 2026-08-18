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

    function render(d) {
        el('adminView').classList.remove('hidden');
        var t = d.today || {};

        el('todayCards').innerHTML =
            card('Visitors', t.visitors, 'pseudonymous sessions') +
            card('New accounts', t.new_users) +
            card('Repeat users', t.repeat_users, 'seen on >1 day') +
            card('Analyses', t.analyses) +
            card('Reports', t.reports) +
            card('Saved locations', t.saved_locations) +
            card('Monitoring rules', t.monitoring_rules) +
            card('SMS interest', t.sms_interest) +
            card('Subscriptions', t.subscriptions);

        el('customersBlock').innerHTML = chips(d.customers || {});
        el('marketingBlock').innerHTML = chips(d.marketing || {});

        // Priority markets (hazard-driven, three segments)
        var pm = d.priority_markets || {};
        el('marketsBlock').innerHTML = Object.keys(pm).map(function (label) {
            var leads = pm[label];
            return '<h3 style="margin:0 0 6px;">' + esc(label) + ' <span class="muted small">(' +
                leads.length + ')</span></h3>' +
                tableRows(leads.slice(0, 8), [
                    { label: 'Organization', get: function (l) { return l.organization; } },
                    { label: 'Country', get: function (l) { return l.country; } },
                    { label: 'Hazards', get: function (l) { return (l.hazards || []).join(', '); } },
                    { label: 'Product', get: function (l) { return l.product; } },
                    { label: 'Priority', get: function (l) { return l.priority; } },
                ]);
        }).join('') || '<div class="notice notice-empty">No priority-market leads yet.</div>';

        // AI Copilot — who to contact now + follow-ups + publish queue
        var cp = d.copilot || {};
        var copilotHtml = '';
        if ((cp.contact_now || []).length) {
            copilotHtml += '<h3 style="margin:0 0 8px;">Who to contact now</h3>' +
                tableRows(cp.contact_now, [
                    { label: 'Organization', get: function (l) { return l.organization; } },
                    { label: 'Why now', get: function (l) { return (l.why || '').slice(0, 120); } },
                    { label: 'Service', get: function (l) { return l.service; } },
                    { label: 'Next action', get: function (l) { return l.next_action; } },
                ]);
        }
        if ((cp.followups_due || []).length) {
            copilotHtml += '<h3 style="margin:14px 0 8px;">Follow-ups due</h3>' +
                tableRows(cp.followups_due, [
                    { label: 'Organization', get: function (l) { return l.organization; } },
                    { label: 'Due', get: function (l) { return l.next_followup; } },
                    { label: 'Action', get: function (l) { return l.next_action; } },
                ]);
        }
        if ((cp.publish_queue || []).length) {
            copilotHtml += '<h3 style="margin:14px 0 8px;">Publish queue (human-reviewed)</h3>' +
                '<p class="muted small">' + cp.publish_queue.map(esc).join('<br>') + '</p>';
        }
        el('copilotBlock').innerHTML = copilotHtml ||
            '<div class="notice notice-empty">Copilot answers appear here as the workspace fills.</div>';

        // Attention
        var at = d.attention || {};
        el('attentionBlock').innerHTML =
            '<p class="muted">High-priority prospects: ' +
            esc((at.high_priority_prospects || []).length) + '</p>' +
            '<p class="muted">SMS opportunity (verified phones): ' +
            esc(at.sms_opportunity_users || 0) + ' · SMS delivery configured: ' +
            esc(at.sms_delivery_configured ? 'yes' : 'no — provider not configured') + '</p>';

        // Funnel
        var f = d.funnel_stages || {};
        el('funnelBlock').innerHTML =
            '<div class="badge-row">' +
            ['visitor', 'analysis', 'repeat_analysis', 'account', 'saved_location',
             'monitoring', 'sms', 'subscription', 'professional', 'business']
                .map(function (k) {
                    return '<span class="chip chip-modelled">' + esc(k.replace(/_/g, ' ')) +
                        ': ' + esc(f[k] == null ? 0 : f[k]) + '</span>';
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

        // Hazard opportunities (hazard-first radar)
        var areas = d.hazard_areas || [];
        var opps = d.hazard_opportunities || [];
        el('hazardBlock').innerHTML =
            (areas.length
                ? '<p class="muted small">Current elevated areas (live snapshot): ' +
                  areas.map(function (a) {
                      return esc(a.area) + ' (' + esc(a.risk_class) + ')';
                  }).join(' · ') + '</p>'
                : '<p class="muted small">No elevated areas in the current snapshot.</p>') +
            tableRows(opps.slice(0, 12), [
                { label: 'Organization', get: function (o) { return o.organization; } },
                { label: 'Segment', get: function (o) { return o.segment_label; } },
                { label: 'Area', get: function (o) { return o.area; } },
                { label: 'Match', get: function (o) { return o.match; } },
                { label: 'Product fit', get: function (o) { return (o.product_fit || []).join(', '); } },
                { label: 'Next action', get: function (o) { return o.next_action; } },
            ]);

        var ws = d.workspace || {};
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
})();
