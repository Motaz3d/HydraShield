/* HydraShield — Operator Intelligence dashboard (admin.html).
 *
 * Admin-only: GET /api/v2/admin/intel (cookie session; 401 shows a plain
 * sign-in hint, 403 the tier message). Renders TODAY / DEMAND / PROSPECTS
 * / RELATIONSHIPS from aggregate data — never individual visitors.
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
            return '<div class="notice notice-empty">Nothing recorded yet — ' +
                'the workspace fills with real, source-checked records.</div>';
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

        el('todayCards').innerHTML =
            card('New users today', d.today.new_users) +
            card('New alert rules today', d.today.new_alert_rules) +
            card('Analytics events today', d.today.analytics_events) +
            card('Total accounts', d.accounts.total_users,
                 Object.keys(d.accounts.by_role || {}).map(function (r) {
                     return r + ': ' + d.accounts.by_role[r];
                 }).join(' · ')) +
            card('Active alert rules', d.alerts.active_rules) +
            card('Verified phones', d.alerts.verified_phones) +
            card('Alerts fired (7d)', d.alerts.records_last_7d);

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
            }).join(' · ') || '—') + '</p>' +
            '<p class="muted small">' + esc(d.demand.note || '') + '</p>';

        var ws = d.workspace || {};
        if (!ws.available) {
            el('prospectsBlock').innerHTML =
                '<div class="notice notice-empty">' + esc(ws.note ||
                'Marketing workspace not present in this deployment.') + '</div>';
            el('relationshipsBlock').innerHTML = '';
            return;
        }
        el('prospectsBlock').innerHTML = tableRows(ws.leads || [], [
            { label: 'Organization', get: function (l) { return l.organization; } },
            { label: 'Segment', get: function (l) { return l.segment; } },
            { label: 'Country', get: function (l) { return l.country; } },
            { label: 'Problem', get: function (l) { return l.identified_problem; } },
            { label: 'Priority', get: function (l) { return l.priority; } },
            { label: 'Urgency', get: function (l) { return l.urgency; } },
            { label: 'Last contact', get: function (l) { return l.last_contact; } },
            { label: 'Next action', get: function (l) { return l.next_action; } },
        ]);

        var interactions = [];
        (ws.leads || []).forEach(function (l) {
            (l.interactions || []).forEach(function (i) {
                interactions.push({
                    organization: l.organization, date: i.date,
                    type: i.type, summary: i.summary,
                    next_action: i.next_action
                });
            });
        });
        interactions.sort(function (a, b) {
            return (a.date || '') < (b.date || '') ? 1 : -1;
        });
        el('relationshipsBlock').innerHTML = tableRows(interactions, [
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
