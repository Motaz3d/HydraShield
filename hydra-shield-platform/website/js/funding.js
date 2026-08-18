/* HydraShield — Funding Intelligence (funding.html).
 *
 * Hazard/sector/beneficiary/country context → GET /api/v2/funding →
 * matched programmes rendered with why_it_matches, funding type, what is
 * supported, who may apply, what is NOT verified, deadline, official
 * source and next action. The disclaimer is always visible.
 */
(function () {
    'use strict';

    var esc = HS.esc, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function loadHazards() {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) {
                el('hazardChecks').innerHTML =
                    '<span class="muted">Hazard registry unavailable.</span>';
                return;
            }
            var preselect = (new URLSearchParams(location.search).get('hazards') || '').split(',');
            el('hazardChecks').innerHTML = res.body.hazards.map(function (h) {
                var checked = preselect.indexOf(h.id) >= 0 ? ' checked' : '';
                return '<label style="display:inline-flex;align-items:center;gap:6px;' +
                    'border:1px solid rgba(0,0,0,0.12);border-radius:999px;padding:6px 14px;' +
                    'font-size:0.85rem;cursor:pointer;background:var(--white);">' +
                    '<input type="checkbox" value="' + esc(h.id) + '"' + checked + '> ' +
                    esc(h.name) + '</label>';
            }).join('');
        }).catch(function () {
            el('hazardChecks').innerHTML =
                '<span class="muted">Hazard registry could not be reached.</span>';
        });
    }

    function selectedHazards() {
        return Array.prototype.map.call(
            document.querySelectorAll('#hazardChecks input[type=checkbox]:checked'),
            function (cb) { return cb.value; });
    }

    function renderStatus(kind, html) {
        el('statusArea').innerHTML = '<div class="notice notice-' + kind + '">' + html + '</div>';
    }

    function match() {
        var params = [];
        var hazards = selectedHazards();
        if (hazards.length) params.push('hazards=' + encodeURIComponent(hazards.join(',')));
        var country = el('countrySel').value;
        if (country === 'other-eu') country = 'FR'; // any EU member exercises the EU rule
        if (country === 'non-eu') country = 'KE';   // any non-EU exercises the global rule
        [['sector', 'sectorSel'], ['beneficiary', 'beneficiarySel']].forEach(function (pair) {
            var v = el(pair[1]).value;
            if (v) params.push(pair[0] + '=' + encodeURIComponent(v));
        });
        if (country) params.push('country=' + encodeURIComponent(country));
        if (!hazards.length && !el('sectorSel').value) {
            renderStatus('error', 'Select at least one hazard or a sector — matching is evidence-gated.');
            return;
        }
        el('matchBtn').disabled = true;
        el('fundingArea').innerHTML = '';
        renderStatus('info', 'Matching funding programmes…');
        fetchJSON(API + '/v2/funding?' + params.join('&')).then(function (res) {
            el('matchBtn').disabled = false;
            render(res.body || {}, res.ok);
        }).catch(function () {
            el('matchBtn').disabled = false;
            renderStatus('error', 'The funding service could not be reached.');
        });
    }

    function matchCard(m) {
        var types = (m.funding_type || []).map(function (t) {
            return '<span class="chip chip-modelled">' + esc(t.replace(/_/g, ' ')) + '</span>';
        }).join('');
        var notVerified = (m.not_verified && m.not_verified.length)
            ? '<div class="notice notice-warn" style="margin-top:8px;">Not verified here: ' +
              m.not_verified.map(esc).join(' · ') + '</div>'
            : '';
        return '<div class="item-card">' +
            '<h3>' + esc(m.name) + '</h3>' +
            '<div class="badge-row">' + types +
            '<span class="chip chip-inferred">' + esc(m.jurisdiction || '') + '</span></div>' +
            '<p class="muted">' + esc(m.programme || '') + ' — ' + esc(m.funding_body || '') + '</p>' +
            '<p><strong>Why it matches:</strong> ' + esc(m.why_it_matches) + '</p>' +
            '<p class="muted small"><strong>Supports:</strong> ' +
            esc((m.what_is_supported || []).join('; ')) + '</p>' +
            '<p class="muted small"><strong>Who may apply:</strong> ' +
            esc((m.who_may_apply || []).join(', ')) + '</p>' +
            '<p class="muted small"><strong>Eligibility:</strong> ' + esc(m.eligibility || 'not stated') + '</p>' +
            '<p class="muted small"><strong>Deadline:</strong> ' + esc(m.deadline) + '</p>' +
            notVerified +
            '<p class="muted small"><strong>Limitations:</strong> ' + esc(m.limitations || '') + '</p>' +
            '<div class="card-actions">' +
            '<a class="text-link" href="' + esc(m.official_url) + '" target="_blank" rel="noopener">Official source →</a>' +
            (m.recommended_action ? '<span class="muted small">' + esc(m.recommended_action) + '</span>' : '') +
            '</div></div>';
    }

    function render(body, ok) {
        if (!ok || body.error) {
            renderStatus('error', 'Funding matching unavailable: ' + esc(body.error || 'request failed'));
            return;
        }
        if (body.status === 'insufficient_data') {
            renderStatus('warn', esc(body.message));
            return;
        }
        var matches = body.matches || [];
        if (!matches.length) {
            renderStatus('empty', 'No programmes matched this context. This is an honest ' +
                'empty result — the knowledge base was queried and nothing fitted.');
            return;
        }
        renderStatus('info', matches.length + ' potential programme(s) matched.');
        el('fundingArea').innerHTML =
            '<div class="card-grid">' + matches.map(matchCard).join('') + '</div>' +
            '<div class="disclaimer-box" style="margin-top:18px;">' + esc(body.disclaimer) + '</div>';
        if (window.HSConvert) HSConvert.show({
            mount: 'statusArea', context: 'funding_monitor',
            text: 'Calls and programmes change — save this context and get told when to re-check.',
            cta: 'Monitor funding opportunities', href: 'account.html'
        });
    }

    el('matchBtn').addEventListener('click', match);
    loadHazards();
})();
