/* Talaix — Marketing CRM module (embedded inside admin.html tabs).
 *
 * Exposes window.HSMarketing = { mountTargets(el), mountStats(el), refresh() }.
 * All DOM lookups use IDs created inside the mounted containers, so a single
 * page-wide instance works. Admin session required; 401/403 handled like admin.js.
 */
(function () {
    'use strict';

    var esc = HS.esc, fetchJSON = HS.fetchJSON, API = HS.API;
    var BASE = API + '/v2/admin/marketing';

    var OUTREACH_STATUSES = [
        'researched', 'qualified', 'draft_prepared',
        'contacted', 'responded', 'opportunity'
    ];

    var cache = new Map();
    var openSlug = null;       // slug with follow-up detail open
    var sendFormSlug = null;   // slug with auto-send form open
    var currentIntersection = { segment: '', country: '', status: '' };

    function el(id) { return document.getElementById(id); }

    function status(kind, msg) {
        var area = el('statusArea');
        if (!area) return;
        area.innerHTML = msg
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

    function cacheKey(params) {
        var parts = [];
        if (params.segment) parts.push('segment:' + params.segment);
        if (params.country) parts.push('country:' + params.country);
        if (params.status) parts.push('status:' + params.status);
        return parts.length ? parts.join(':') : 'root';
    }

    function getFromCache(params) { return cache.get(cacheKey(params)); }
    function setCache(params, data) { cache.set(cacheKey(params), data); }
    function clearTreeCache() { cache.clear(); }

    function showAuthHint(res) {
        if (res.status === 401) {
            status('info', 'Sign in with an operator account on the ' +
                   '<a href="account.html">account page</a> first.');
            return true;
        }
        if (res.status === 403) {
            status('warn', esc((res.body && res.body.error) ||
                   'This area requires the admin tier.'));
            return true;
        }
        return false;
    }

    // ------------------------------------------------------------------
    // Mounting
    // ------------------------------------------------------------------

    function mountTargets(container) {
        if (!el('treeContainer')) {
            container.innerHTML =
                '<div class="mkt-tree" id="treeContainer">' +
                '<div class="notice notice-empty" style="margin:12px 16px;">Loading sectors…</div>' +
                '</div>' +
                '<div class="mkt-modal" id="intersectionModal" role="dialog" aria-modal="true" aria-labelledby="intersectionTitle">' +
                '<div class="mkt-modal-panel">' +
                '<div class="mkt-modal-header">' +
                '<h2 id="intersectionTitle">Intersection</h2>' +
                '<button class="mkt-close" id="closeIntersection" aria-label="Close">✕</button>' +
                '</div>' +
                '<div class="mkt-modal-body" id="intersectionBody">' +
                '<div class="notice notice-empty">Loading targets…</div>' +
                '</div>' +
                '</div>' +
                '</div>';
            bindModalClose();
        }
        loadSectors();
    }

    function mountStats(container) {
        if (!el('statsContainer')) {
            container.innerHTML = '<div id="statsContainer">' +
                '<div class="notice notice-empty">Loading statistics…</div>' +
                '</div>';
        }
        loadStats();
    }

    function bindModalClose() {
        el('closeIntersection').addEventListener('click', closeIntersection);
        el('intersectionModal').addEventListener('click', function (e) {
            if (e.target === el('intersectionModal')) closeIntersection();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && el('intersectionModal').classList.contains('open')) {
                closeIntersection();
            }
        });
    }

    function refresh() {
        clearTreeCache();
        openSlug = null;
        sendFormSlug = null;
        if (el('treeContainer')) {
            el('treeContainer').innerHTML = '<div class="notice notice-empty" style="margin:12px 16px;">Loading sectors…</div>';
            loadSectors();
        }
        if (el('statsContainer')) {
            el('statsContainer').innerHTML = '<div class="notice notice-empty">Loading statistics…</div>';
            loadStats();
        }
        if (el('intersectionModal') && el('intersectionModal').classList.contains('open')) {
            loadIntersection();
        }
    }

    // ------------------------------------------------------------------
    // Site statistics
    // ------------------------------------------------------------------

    function statCard(value, label) {
        return '<div class="mkt-statcard">' +
            '<div class="value">' + esc(value != null ? value : '—') + '</div>' +
            '<div class="label">' + esc(label) + '</div>' +
            '</div>';
    }

    function loadStats() {
        fetchJSON(BASE + '/stats').then(function (res) {
            if (showAuthHint(res)) {
                el('statsContainer').innerHTML = '';
                return;
            }
            if (!res.ok) {
                el('statsContainer').innerHTML =
                    '<div class="notice notice-error">Site statistics unavailable.</div>';
                return;
            }
            renderStats(res.body || {});
        }).catch(function () {
            el('statsContainer').innerHTML =
                '<div class="notice notice-error">Site statistics could not be reached.</div>';
        });
    }

    function renderStats(data) {
        var visitors = data.visitors || {};
        var subscribers = data.subscribers || {};
        var activity = data.activity || {};
        var topPages = data.top_pages || [];
        var daily = data.daily || [];
        var referrers = data.top_referrers || [];
        var devices = data.devices || [];
        var languages = data.languages || [];
        var hazards = data.top_hazards || [];

        var html = '<div class="mkt-statgrid">' +
            statCard(visitors.today, 'Visitors today') +
            statCard(visitors.last_7_days, 'Visitors 7d') +
            statCard(visitors.last_30_days, 'Visitors 30d') +
            statCard(visitors.total_page_views, 'Total page views') +
            statCard(subscribers.active_subscriptions, 'Subscribers') +
            statCard(subscribers.accounts, 'Registered accounts') +
            statCard(activity.active_sessions_30d, 'Active visitors 30d') +
            '</div>';

        html += renderDetailsSection('Most visited areas', topPages.length
            ? '<div class="table-scroll"><table class="data-table"><thead><tr>' +
              '<th>Page</th><th>Views</th><th>Unique visitors</th>' +
              '</tr></thead><tbody>' +
              topPages.map(function (p) {
                  return '<tr>' +
                      '<td>' + esc(p.page || '—') + '</td>' +
                      '<td>' + esc(p.views != null ? p.views : '—') + '</td>' +
                      '<td>' + esc(p.unique_visitors != null ? p.unique_visitors : '—') + '</td>' +
                      '</tr>';
              }).join('') +
              '</tbody></table></div>'
            : '<p class="muted small">No page view data yet.</p>');

        html += renderDetailsSection('Daily visitors (30 days)', daily.length
            ? '<div class="table-scroll"><table class="data-table"><thead><tr>' +
              '<th>Date</th><th>Visitors</th><th>Page views</th>' +
              '</tr></thead><tbody>' +
              daily.map(function (d) {
                  return '<tr>' +
                      '<td>' + esc(d.date || '—') + '</td>' +
                      '<td>' + esc(d.visitors != null ? d.visitors : '—') + '</td>' +
                      '<td>' + esc(d.page_views != null ? d.page_views : '—') + '</td>' +
                      '</tr>';
              }).join('') +
              '</tbody></table></div>'
            : '<p class="muted small">No daily data yet.</p>');

        html += renderDetailsSection('Traffic sources', referrers.length
            ? '<div class="table-scroll"><table class="data-table"><thead><tr>' +
              '<th>Referrer</th><th>Count</th>' +
              '</tr></thead><tbody>' +
              referrers.map(function (r) {
                  return '<tr>' +
                      '<td>' + esc(r.referrer || '—') + '</td>' +
                      '<td>' + esc(r.count != null ? r.count : '—') + '</td>' +
                      '</tr>';
              }).join('') +
              '</tbody></table></div>'
            : '<p class="muted small">No referrer data yet.</p>');

        var devicesHtml = devices.length
            ? '<div class="badge-row" style="margin-bottom:12px;">' +
              devices.map(function (d) {
                  return HS.chip('modelled', esc(d.device || 'unknown') + ': ' + esc(d.count != null ? d.count : '—'));
              }).join('') + '</div>'
            : '<p class="muted small">No device data yet.</p>';
        var languagesHtml = languages.length
            ? '<div class="badge-row">' +
              languages.map(function (l) {
                  return HS.chip('observed', esc(l.language || 'unknown') + ': ' + esc(l.count != null ? l.count : '—'));
              }).join('') + '</div>'
            : '<p class="muted small">No language data yet.</p>';
        html += renderDetailsSection('Devices & languages',
            '<h4 style="margin:0 0 8px;font-size:0.85rem;">Devices</h4>' + devicesHtml +
            '<h4 style="margin:16px 0 8px;font-size:0.85rem;">Languages</h4>' + languagesHtml);

        html += renderDetailsSection('Risk interests', hazards.length
            ? '<div class="badge-row">' +
              hazards.map(function (h) {
                  return HS.chip('forecast', esc(h.hazard || '—') + ': ' + esc(h.count != null ? h.count : '—'));
              }).join('') + '</div>'
            : '<p class="muted small">No hazard interest data yet.</p>');

        if (data.note) {
            html += '<p class="muted small" style="margin-top:10px;">' + esc(data.note) +
                (data.generated_at ? ' · Generated at ' + esc(data.generated_at) : '') + '</p>';
        }

        el('statsContainer').innerHTML = html;
    }

    function renderDetailsSection(title, contentHtml) {
        return '<details class="mkt-details">' +
            '<summary>' + esc(title) + '</summary>' +
            '<div class="mkt-details-inner">' + contentHtml + '</div>' +
            '</details>';
    }

    // ------------------------------------------------------------------
    // Targets tree
    // ------------------------------------------------------------------

    function treeRow(label, count, toggleKey) {
        var toggle = toggleKey
            ? '<button class="mkt-toggle" data-sector="' + esc(toggleKey) + '" aria-expanded="false">▸</button>'
            : '<span class="mkt-toggle" style="visibility:hidden;">▸</span>';
        var countBadge = count !== undefined && count !== null
            ? '<span class="mkt-count">' + esc(String(count)) + '</span>'
            : '';
        return '<div class="mkt-row">' +
            toggle +
            '<span class="mkt-label">' + esc(label) + '</span>' +
            countBadge +
            '</div>';
    }

    function loadSectors() {
        fetchJSON(BASE + '/tree').then(function (res) {
            if (showAuthHint(res)) {
                el('treeContainer').innerHTML = '';
                return;
            }
            if (!res.ok) {
                status('error', 'Marketing tree unavailable.');
                return;
            }
            status('', '');
            renderSectors(res.body.sectors || []);
        }).catch(function () {
            status('error', 'Marketing tree could not be reached.');
        });
    }

    function renderSectors(sectors) {
        var html = '';
        sectors.forEach(function (s) {
            var childrenId = 'mkt-sector-' + esc(s.key);
            html += '<div class="mkt-node">' +
                treeRow(s.label, s.count, s.key) +
                '<div id="' + childrenId + '" class="mkt-countries hidden"></div>' +
                '</div>';
        });
        el('treeContainer').innerHTML = html ||
            '<div class="notice notice-empty" style="margin:12px 16px;">No sectors yet.</div>';
        bindSectorToggles();
    }

    function bindSectorToggles() {
        Array.prototype.forEach.call(
            document.querySelectorAll('.mkt-toggle[data-sector]'),
            function (btn) {
                btn.addEventListener('click', function () {
                    toggleSector(btn.getAttribute('data-sector'), btn);
                });
            });
    }

    function setExpanded(btn, expanded) {
        btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        btn.textContent = expanded ? '▾' : '▸';
    }

    function toggleSector(key, btn) {
        var containerId = 'mkt-sector-' + key;
        var container = el(containerId);
        if (!container) return;
        var expanded = btn.getAttribute('aria-expanded') === 'true';
        if (expanded) {
            container.classList.add('hidden');
            setExpanded(btn, false);
            return;
        }
        if (container.hasChildNodes() && container.innerHTML !== '') {
            container.classList.remove('hidden');
            setExpanded(btn, true);
            return;
        }
        var cached = getFromCache({ segment: key });
        if (cached) {
            renderCountries(key, cached.countries || []);
            container.classList.remove('hidden');
            setExpanded(btn, true);
            return;
        }
        fetchJSON(BASE + '/tree?segment=' + encodeURIComponent(key)).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                container.innerHTML = '<div class="muted small">Could not load countries.</div>';
                container.classList.remove('hidden');
                return;
            }
            setCache({ segment: key }, res.body);
            renderCountries(key, res.body.countries || []);
            container.classList.remove('hidden');
            setExpanded(btn, true);
        }).catch(function () {
            container.innerHTML = '<div class="muted small">Could not load countries.</div>';
            container.classList.remove('hidden');
        });
    }

    function renderCountries(segment, countries) {
        var containerId = 'mkt-sector-' + segment;
        var html = countries.map(function (c) {
            return '<button class="mkt-country" data-open="' + esc(segment) + ':' + esc(c.country) + '">' +
                esc(c.country) + ' <span class="mkt-count">' + esc(String(c.count)) + '</span></button>';
        }).join('');
        el(containerId).innerHTML = html || '<div class="muted small">No countries.</div>';

        Array.prototype.forEach.call(el(containerId).querySelectorAll('[data-open]'), function (btn) {
            btn.addEventListener('click', function () {
                var parts = btn.getAttribute('data-open').split(':');
                openIntersection(parts[0], parts[1]);
            });
        });
    }

    // ------------------------------------------------------------------
    // Intersection modal
    // ------------------------------------------------------------------

    function openIntersection(segment, country) {
        currentIntersection = { segment: segment, country: country, status: '' };
        el('intersectionTitle').textContent = segment.replace(/_/g, ' ') + ' × ' + country;
        el('intersectionBody').innerHTML = '<div class="notice notice-empty">Loading targets…</div>';
        el('intersectionModal').classList.add('open');
        document.body.style.overflow = 'hidden';
        loadIntersection();
    }

    function closeIntersection() {
        el('intersectionModal').classList.remove('open');
        document.body.style.overflow = '';
        currentIntersection = { segment: '', country: '', status: '' };
    }

    function loadIntersection() {
        var segment = currentIntersection.segment;
        var country = currentIntersection.country;
        var status = currentIntersection.status;
        var params = 'segment=' + encodeURIComponent(segment) + '&country=' + encodeURIComponent(country);
        if (status) params += '&status=' + encodeURIComponent(status);

        var cached = getFromCache({ segment: segment, country: country, status: status });
        if (cached) {
            renderIntersection(cached);
            return;
        }
        fetchJSON(BASE + '/tree?' + params).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                el('intersectionBody').innerHTML =
                    '<div class="notice notice-error">Could not load targets.</div>';
                return;
            }
            setCache({ segment: segment, country: country, status: status }, res.body);
            renderIntersection(res.body);
        }).catch(function () {
            el('intersectionBody').innerHTML =
                '<div class="notice notice-error">Could not load targets.</div>';
        });
    }

    function renderIntersection(data) {
        var segment = data.segment || currentIntersection.segment;
        var country = data.country || currentIntersection.country;
        var activeStatus = data.status || currentIntersection.status;
        var statuses = data.statuses || [];
        var leads = data.leads || [];

        var total = statuses.reduce(function (sum, s) { return sum + (s.count || 0); }, 0);

        var html = '<div class="mkt-filters">' +
            '<button class="mkt-filter' + (activeStatus ? '' : ' active') + '" data-filter="">All (' + esc(total) + ')</button>';
        statuses.forEach(function (s) {
            html += '<button class="mkt-filter' + (activeStatus === s.status ? ' active' : '') + '" data-filter="' + esc(s.status) + '">' +
                esc(s.status.replace(/_/g, ' ')) + ' (' + esc(String(s.count)) + ')</button>';
        });
        html += '</div>';

        if (leads.length) {
            html += '<div class="mkt-targets">';
            leads.forEach(function (l) {
                html += renderTarget(segment, country, l);
            });
            html += '</div>';
        } else {
            html += '<div class="notice notice-empty">No targets match the selected filter.</div>';
        }

        el('intersectionBody').innerHTML = html;

        Array.prototype.forEach.call(el('intersectionBody').querySelectorAll('[data-filter]'), function (btn) {
            btn.addEventListener('click', function () {
                currentIntersection.status = btn.getAttribute('data-filter');
                loadIntersection();
            });
        });

        Array.prototype.forEach.call(el('intersectionBody').querySelectorAll('[data-follow]'), function (btn) {
            var slug = btn.getAttribute('data-follow');
            btn.addEventListener('click', function () { toggleFollowUp(slug); });
        });

        Array.prototype.forEach.call(el('intersectionBody').querySelectorAll('[data-send]'), function (btn) {
            var slug = btn.getAttribute('data-send');
            var sec = btn.getAttribute('data-sector') || '';
            var role = btn.getAttribute('data-role') || '';
            btn.addEventListener('click', function () { toggleSendForm(slug, sec, role); });
        });
    }

    function renderTarget(segment, country, l) {
        var org = l.website
            ? '<a class="text-link" href="' + esc(l.website) + '" target="_blank" rel="noopener">' + esc(l.organization) + '</a>'
            : esc(l.organization);
        return '<div class="mkt-target" id="mkt-leadwrap-' + esc(l.slug) + '">' +
            '<div class="mkt-target-head">' +
            '<div>' +
            '<strong>' + org + '</strong>' +
            '<div class="mkt-target-meta" style="margin-top:4px;">' +
            priorityChip(l.priority) +
            statusChip(l.outreach_status) +
            (l.score != null ? '<span class="chip chip-modelled">score ' + esc(l.score) + '</span>' : '') +
            '</div>' +
            '</div>' +
            '<div class="mkt-actions" style="display:flex;gap:8px;">' +
            '<button class="btn-action btn-quiet" data-send="' + esc(l.slug) + '" ' +
            'data-sector="' + esc(segment) + '" data-role="' + esc(l.decision_maker_role || '') + '">Auto-send</button> ' +
            '<button class="btn-action btn-quiet" data-follow="' + esc(l.slug) + '">Follow-up</button>' +
            '</div>' +
            '</div>' +
            '<div id="mkt-detail-' + esc(l.slug) + '" class="mkt-detail hidden"></div>' +
            '<div id="mkt-send-' + esc(l.slug) + '" class="mkt-sendform hidden"></div>' +
            '</div>';
    }

    function priorityChip(p) {
        return HS.chip(p, p);
    }

    function statusChip(s) {
        return HS.chip(s, s);
    }

    // ------------------------------------------------------------------
    // Follow-up detail panel
    // ------------------------------------------------------------------

    function toggleFollowUp(slug) {
        var detail = el('mkt-detail-' + slug);
        if (!detail) return;
        if (openSlug && openSlug !== slug) {
            var prev = el('mkt-detail-' + openSlug);
            if (prev) {
                prev.classList.add('hidden');
                prev.innerHTML = '';
            }
        }
        if (openSlug === slug && !detail.classList.contains('hidden')) {
            detail.classList.add('hidden');
            detail.innerHTML = '';
            openSlug = null;
            return;
        }
        openSlug = slug;
        detail.classList.remove('hidden');
        detail.innerHTML = '<div class="muted small">Loading follow-up…</div>';
        fetchJSON(BASE + '/lead/' + encodeURIComponent(slug)).then(function (res) {
            if (showAuthHint(res)) return;
            if (res.status === 404) {
                detail.innerHTML = '<div class="notice notice-error">Lead not found.</div>';
                return;
            }
            if (!res.ok) {
                detail.innerHTML = '<div class="notice notice-error">Could not load follow-up.</div>';
                return;
            }
            detail.innerHTML = buildDetailHTML(slug, res.body);
            bindDetailActions(slug, detail);
        }).catch(function () {
            detail.innerHTML = '<div class="notice notice-error">Could not load follow-up.</div>';
        });
    }

    function buildDetailHTML(slug, data) {
        var lead = data.lead || {};
        var score = data.score;
        var followup = data.followup || null;
        var interactions = data.interactions || [];
        var scheduled = data.scheduled || [];

        var html = '<h4>Follow-up: ' + esc(lead.organization || slug) + '</h4>';

        var current = lead.outreach_status || 'researched';
        var currentIdx = OUTREACH_STATUSES.indexOf(current);
        html += '<div class="mkt-stepbar">';
        OUTREACH_STATUSES.forEach(function (s, idx) {
            var cls = 'mkt-step';
            if (s === current) cls += ' current';
            else if (idx < currentIdx) cls += ' past';
            html += '<div class="' + cls + '">' + esc(s.replace(/_/g, ' ')) + '</div>';
        });
        html += '</div>';

        html += '<div class="mkt-sub"><div class="mkt-sub-title">Opportunity analysis</div>' +
            '<dl class="mkt-kv">' +
            '<dt>Score</dt><dd>' + (score != null ? esc(score) : '—') + '</dd>' +
            '<dt>Priority</dt><dd>' + priorityChip(lead.priority) + '</dd>' +
            '<dt>Urgency</dt><dd>' + esc(lead.urgency != null ? lead.urgency : '—') + '</dd>' +
            '<dt>Fit score</dt><dd>' + esc(lead.fit_score != null ? lead.fit_score : '—') + '</dd>' +
            '</dl>';
        if (followup) {
            html += '<dl class="mkt-kv" style="margin-top:8px;">' +
                '<dt>Suggested action</dt><dd>' + esc(followup.suggested_action || '—') + '</dd>' +
                '<dt>Recommended product</dt><dd>' + esc((followup.recommended_product || '').replace(/_/g, ' ')) + '</dd>' +
                '<dt>Recommended message</dt><dd>' + esc(followup.recommended_message || '—') + '</dd>' +
                '<dt>Next follow-up</dt><dd>' + esc(followup.next_followup_date || '—') +
                (followup.is_overdue ? ' <span class="chip mkt-overdue">overdue</span>' : '') + '</dd>' +
                '<dt>Days until follow-up</dt><dd>' + esc(followup.days_until_followup != null ? followup.days_until_followup : '—') + '</dd>' +
                '<dt>Priority</dt><dd>' + priorityChip(followup.priority) + '</dd>' +
                '</dl>';
        } else {
            html += '<p class="muted small" style="margin-top:8px;">No follow-up record yet.</p>';
        }
        html += '</div>';

        html += '<div class="mkt-sub"><div class="mkt-sub-title">Correspondence log</div>';
        if (interactions.length) {
            html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Date</th><th>Type</th><th>Summary</th>' +
                '</tr></thead><tbody>';
            interactions.slice().reverse().forEach(function (i) {
                html += '<tr>' +
                    '<td>' + esc(i.date || '—') + '</td>' +
                    '<td>' + statusChip(i.type) + '</td>' +
                    '<td>' + esc(i.summary || '—') + '</td>' +
                    '</tr>';
            });
            html += '</tbody></table></div>';
        } else {
            html += '<p class="muted small">No correspondence logged yet.</p>';
        }
        html += '</div>';

        html += '<div class="mkt-sub"><div class="mkt-sub-title">Scheduled sends</div>' +
            renderScheduledList(slug, scheduled) +
            '</div>';

        return html;
    }

    function renderScheduledList(slug, scheduled) {
        if (!scheduled.length) {
            return '<p class="muted small">No scheduled sends.</p>';
        }
        var html = '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Send at</th><th>To</th><th>Contact</th><th>Status</th><th>Error</th><th></th>' +
            '</tr></thead><tbody>';
        scheduled.forEach(function (s) {
            var canCancel = s.status === 'scheduled';
            html += '<tr>' +
                '<td>' + esc(s.send_at || '—') + '</td>' +
                '<td>' + esc(s.to_email || '—') + '</td>' +
                '<td>' + esc(s.contact_name || '—') + '</td>' +
                '<td>' + statusChip(s.status) + '</td>' +
                '<td>' + (s.error ? '<span class="muted small" style="color:#991b1b;">' + esc(s.error) + '</span>' : '—') + '</td>' +
                '<td>' + (canCancel
                    ? '<button class="btn-action btn-quiet" data-cancel="' + esc(s.id) + '">Cancel</button>'
                    : '') + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    function bindDetailActions(slug, detail) {
        Array.prototype.forEach.call(detail.querySelectorAll('[data-cancel]'), function (btn) {
            btn.addEventListener('click', function () {
                var id = btn.getAttribute('data-cancel');
                if (!window.confirm('Cancel this scheduled send?')) return;
                cancelScheduled(id, slug);
            });
        });
    }

    function cancelScheduled(id, slug) {
        postJSON(BASE + '/scheduled/' + encodeURIComponent(id) + '/cancel', {}).then(function (res) {
            if (showAuthHint(res)) return;
            if (res.status === 409) {
                status('warn', esc((res.body && res.body.error) || 'This send cannot be cancelled.'));
                refreshFollowUp(slug);
                return;
            }
            if (!res.ok) {
                status('error', esc((res.body && res.body.error) || 'Cancel failed.'));
                refreshFollowUp(slug);
                return;
            }
            status('info', 'Scheduled send cancelled.');
            refreshFollowUp(slug);
        }).catch(function () {
            status('error', 'Cancel request could not be sent.');
        });
    }

    function refreshFollowUp(slug) {
        if (openSlug === slug) {
            toggleFollowUp(slug);
            toggleFollowUp(slug);
        }
    }

    // ------------------------------------------------------------------
    // Auto-send form
    // ------------------------------------------------------------------

    function toggleSendForm(slug, sector, role) {
        var form = el('mkt-send-' + slug);
        if (!form) return;
        if (sendFormSlug && sendFormSlug !== slug) {
            var prev = el('mkt-send-' + sendFormSlug);
            if (prev) {
                prev.classList.add('hidden');
                prev.innerHTML = '';
            }
        }
        if (sendFormSlug === slug && !form.classList.contains('hidden')) {
            form.classList.add('hidden');
            form.innerHTML = '';
            sendFormSlug = null;
            return;
        }
        sendFormSlug = slug;
        form.classList.remove('hidden');
        form.innerHTML = buildSendFormHTML(slug, sector, role);
        bindSendFormActions(slug, form);
    }

    function buildSendFormHTML(slug, sector, role) {
        return '<h4>Auto-send: ' + esc(slug) + '</h4>' +
            '<p class="mkt-template-note">Message is generated from the pre-made ' +
            esc((sector || 'sector').replace(/_/g, ' ')) +
            ' template merged with this lead\'s country and evidence.</p>' +
            '<div class="mkt-field">' +
            '<label for="mkt-send-to-' + esc(slug) + '">To email *</label>' +
            '<input type="email" id="mkt-send-to-' + esc(slug) + '" required>' +
            '</div>' +
            '<div class="mkt-field">' +
            '<label for="mkt-send-name-' + esc(slug) + '">Contact name</label>' +
            '<input type="text" id="mkt-send-name-' + esc(slug) + '" placeholder="' + esc(role || '') + '">' +
            '</div>' +
            '<div class="mkt-field">' +
            '<label for="mkt-send-msg-' + esc(slug) + '">Custom message</label>' +
            '<textarea id="mkt-send-msg-' + esc(slug) + '" placeholder="Added to the pre-made template body"></textarea>' +
            '</div>' +
            '<div class="mkt-sendactions">' +
            '<button class="btn-action" data-send-now>Send now</button>' +
            '<button class="btn-action btn-quiet" data-schedule-toggle>Schedule</button>' +
            '</div>' +
            '<div class="mkt-schedulewrap" id="mkt-schedulewrap-' + esc(slug) + '">' +
            '<div class="mkt-field">' +
            '<label for="mkt-send-at-' + esc(slug) + '">Send at</label>' +
            '<input type="datetime-local" id="mkt-send-at-' + esc(slug) + '">' +
            '</div>' +
            '<button class="btn-action" data-send-schedule>Confirm schedule</button>' +
            '</div>' +
            '<div id="mkt-sendresult-' + esc(slug) + '" class="mkt-sendresult"></div>';
    }

    function bindSendFormActions(slug, form) {
        var nowBtn = form.querySelector('[data-send-now]');
        var scheduleToggle = form.querySelector('[data-schedule-toggle]');
        var scheduleBtn = form.querySelector('[data-send-schedule]');
        if (nowBtn) {
            nowBtn.addEventListener('click', function () { doSend(slug, null); });
        }
        if (scheduleToggle) {
            scheduleToggle.addEventListener('click', function () {
                var wrap = el('mkt-schedulewrap-' + slug);
                if (wrap) wrap.classList.toggle('visible');
            });
        }
        if (scheduleBtn) {
            scheduleBtn.addEventListener('click', function () {
                var input = el('mkt-send-at-' + slug);
                var raw = input ? input.value : '';
                if (!raw) {
                    showSendResult(slug, 'error', 'Choose a send date and time.');
                    return;
                }
                var d = new Date(raw);
                if (isNaN(d.getTime())) {
                    showSendResult(slug, 'error', 'Invalid date/time.');
                    return;
                }
                doSend(slug, d.toISOString());
            });
        }
    }

    function getSendPayload(slug) {
        var to = el('mkt-send-to-' + slug);
        var name = el('mkt-send-name-' + slug);
        var msg = el('mkt-send-msg-' + slug);
        return {
            to_email: to ? to.value.trim() : '',
            contact_name: name && name.value.trim() ? name.value.trim() : undefined,
            custom_message: msg && msg.value.trim() ? msg.value.trim() : undefined
        };
    }

    function validatePayload(payload) {
        if (!payload.to_email) return 'To email is required.';
        if (!/^.+@.+\..+$/.test(payload.to_email)) return 'Enter a valid email address.';
        return null;
    }

    function doSend(slug, sendAt) {
        var resultBox = el('mkt-sendresult-' + slug);
        if (resultBox) resultBox.innerHTML = '';
        var payload = getSendPayload(slug);
        var err = validatePayload(payload);
        if (err) {
            showSendResult(slug, 'error', err);
            return;
        }
        var url = BASE + '/lead/' + encodeURIComponent(slug) + (sendAt ? '/schedule' : '/send');
        if (sendAt) payload.send_at = sendAt;
        postJSON(url, payload).then(function (res) {
            if (showAuthHint(res)) return;
            if (res.status === 400) {
                showSendResult(slug, 'error', esc((res.body && res.body.error) || 'Invalid input.'));
                return;
            }
            if (res.status === 502) {
                showSendResult(slug, 'error', esc((res.body && res.body.error) || 'Delivery failed.') +
                    (res.body && res.body.detail ? ' ' + esc(res.body.detail) : ''));
                return;
            }
            if (!res.ok) {
                showSendResult(slug, 'error', esc((res.body && res.body.error) || 'Request failed.'));
                return;
            }
            if (sendAt) {
                var scheduledAt = res.body.scheduled && res.body.scheduled.send_at
                    ? res.body.scheduled.send_at
                    : sendAt;
                showSendResult(slug, 'ok', 'Scheduled for ' + esc(scheduledAt) + '.');
            } else {
                var delivery = res.body.delivery || {};
                if (delivery.backend === 'smtp') {
                    showSendResult(slug, 'ok', 'Sent via SMTP to ' + esc(delivery.to || payload.to_email) + '.');
                } else if (delivery.backend === 'outbox') {
                    showSendResult(slug, 'outbox', 'SMTP not configured — message written to dev outbox (not actually sent).');
                } else {
                    showSendResult(slug, 'ok', 'Message queued.');
                }
            }
            clearTreeCache();
        }).catch(function () {
            showSendResult(slug, 'error', 'Send request could not be sent.');
        });
    }

    function showSendResult(slug, kind, msg) {
        var box = el('mkt-sendresult-' + slug);
        if (!box) return;
        var cls = 'mkt-' + kind;
        box.innerHTML = '<div class="' + cls + '">' + esc(msg) + '</div>';
    }

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    window.HSMarketing = {
        mountTargets: mountTargets,
        mountStats: mountStats,
        refresh: refresh
    };
})();
