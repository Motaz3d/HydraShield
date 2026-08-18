/* HydraShield — Commercial Center (admin.html).
 *
 * Admin-only: GET /api/v2/admin/intel (cookie session; 401 shows a plain
 * sign-in hint, 403 the tier message). Renders TODAY / TARGETS vs ACTUAL /
 * DEMAND / PROSPECTS / MARKETS / SIGNALS / RELATIONSHIPS from aggregate
 * data — never individual visitors. Targets are targets, never results.
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
        var ws = d.workspace || {};

        // TODAY
        el('todayCards').innerHTML =
            card('Visitors today', d.today.visitors, 'pseudonymous sessions') +
            card('New registrations today', d.today.new_users) +
            card('Total accounts', d.accounts.total_users,
                 Object.keys(d.accounts.by_role || {}).map(function (r) {
                     return r + ': ' + d.accounts.by_role[r];
                 }).join(' · ')) +
            card('Active alert rules', d.alerts.active_rules) +
            card('Verified phones', d.alerts.verified_phones) +
            card('Alerts fired (7d)', d.alerts.records_last_7d);

        // TARGETS vs ACTUAL (30-day experiment — targets are not results)
        el('targetsBlock').innerHTML = tableRows(
            Object.keys(d.targets || {}).map(function (k) {
                var t = d.targets[k];
                return { metric: k.replace(/_/g, ' '), target: t.target,
                         actual: t.actual,
                         progress: Math.min(100, Math.round(100 * t.actual / t.target)) + '%' };
            }),
            [{ label: 'Metric', get: function (r) { return r.metric; } },
             { label: 'Target', get: function (r) { return r.target; } },
             { label: 'Actual', get: function (r) { return r.actual; } },
             { label: 'Progress', get: function (r) { return r.progress; } }]
        );

        // DEMAND
        var funnel = d.demand.funnel || {};
        el('demandBlock').innerHTML =
            '<div class="badge-row">' +
            Object.keys(funnel).sort().map(function (ev) {
                return '<span class="chip chip-observed">' + esc(ev) + ': ' +
                    esc(funnel[ev]) + '</span>';
            }).join('') + '</div>' +
            '<p class="muted small">Top hazards: ' +
            (d.demand.top_hazards.map(function (h) {
                return esc(h.hazard) + ' (' + esc(h.count) + ')';
            }).join(' · ') || '—') + ' · ' + esc(d.demand.note || '') + '</p>';

        if (!ws.available) {
            el('prospectsBlock').innerHTML =
                '<div class="notice notice-empty">' + esc(ws.note ||
                'Marketing workspace not present in this deployment.') + '</div>';
            el('marketsBlock').innerHTML = '';
            el('signalsBlock').innerHTML = '';
            el('relationshipsBlock').innerHTML = '';
            return;
        }

        // PROSPECTS
        var p = ws.prospects || {};
        el('prospectsBlock').innerHTML =
            '<div class="badge-row">' +
            ['total', 'new', 'qualified', 'high_priority', 'contacted',
             'responded', 'opportunities'].map(function (k) {
                return '<span class="chip chip-inferred">' + k.replace(/_/g, ' ') +
                    ': ' + esc(p[k] == null ? 0 : p[k]) + '</span>';
            }).join('') + '</div>' +
            tableRows(ws.leads || [], [
                { label: 'Organization', get: function (l) { return l.organization; } },
                { label: 'Segment', get: function (l) { return l.segment; } },
                { label: 'Country', get: function (l) { return l.country; } },
                { label: 'Priority', get: function (l) { return l.priority; } },
                { label: 'Status', get: function (l) { return l.outreach_status; } },
                { label: 'Next action', get: function (l) { return l.next_action; } },
            ]);

        // MARKETS + SIGNALS
        el('marketsBlock').innerHTML =
            '<div class="badge-row">' +
            Object.keys(ws.markets || {}).sort().map(function (seg) {
                return '<span class="chip chip-modelled">' + esc(seg.replace(/_/g, ' ')) +
                    ': ' + esc(ws.markets[seg]) + '</span>';
            }).join('') + '</div>';
        var s = ws.signals || {};
        el('signalsBlock').innerHTML =
            '<p class="muted">Commercial signals: ' + esc(s.total || 0) +
            ' · EU funding records: ' + esc(s.eu_funding_records || 0) +
            ' · events tracked: ' + esc(s.events_tracked || 0) + '</p>';

        // RELATIONSHIPS
        el('relationshipsBlock').innerHTML = tableRows(ws.relationships || [], [
            { label: 'Date', get: function (i) { return i.date; } },
            { label: 'Organization', get: function (i) { return i.organization; } },
            { label: 'Type', get: function (i) { return i.type; } },
            { label: 'Summary', get: function (i) { return i.summary; } },
            { label: 'Next action', get: function (i) { return i.next_action; } },
        ]);
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
            status('error', 'Operator intelligence unavailable.');
            return;
        }
        status('', '');
        render(res.body);
    }).catch(function () {
        status('error', 'Operator intelligence could not be reached.');
    });
})();
