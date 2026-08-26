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
    var contactsSlug = null;   // slug with contacts panel open
    var contactsCache = new Map();
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

    function closeFollowUpPanel() {
        if (!openSlug) return;
        var p = el('mkt-detail-' + openSlug);
        if (p) { p.classList.add('hidden'); p.innerHTML = ''; }
        openSlug = null;
    }

    function closeSendForm() {
        if (!sendFormSlug) return;
        var p = el('mkt-send-' + sendFormSlug);
        if (p) { p.classList.add('hidden'); p.innerHTML = ''; }
        sendFormSlug = null;
    }

    function closeContactsPanel() {
        if (!contactsSlug) return;
        var p = el('mkt-contacts-' + contactsSlug);
        if (p) { p.classList.add('hidden'); p.innerHTML = ''; }
        contactsSlug = null;
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
                '<div>' +
                '<h2 id="intersectionTitle">Intersection</h2>' +
                '<div class="mkt-filters" id="intersectionFilters"></div>' +
                '</div>' +
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
        contactsCache.clear();
        openSlug = null;
        sendFormSlug = null;
        contactsSlug = null;
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

    function treeRow(label, count, toggleAttrs, labelAttrs) {
        var toggle = toggleAttrs
            ? '<button class="mkt-toggle" ' + toggleAttrs + ' aria-expanded="false">▸</button>'
            : '<span class="mkt-toggle" style="visibility:hidden;">▸</span>';
        var countBadge = count !== undefined && count !== null
            ? '<span class="mkt-count">' + esc(String(count)) + '</span>'
            : '';
        var labelHtml = labelAttrs
            ? '<span class="mkt-label" ' + labelAttrs + '>' + esc(label) + '</span>'
            : '<span class="mkt-label">' + esc(label) + '</span>';
        return '<div class="mkt-row">' +
            toggle +
            labelHtml +
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
                treeRow(s.label, s.count,
                        'data-sector="' + esc(s.key) + '"',
                        'data-toggle-sector="' + esc(s.key) + '"') +
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
        Array.prototype.forEach.call(
            document.querySelectorAll('.mkt-label[data-toggle-sector]'),
            function (label) {
                label.addEventListener('click', function () {
                    var key = label.getAttribute('data-toggle-sector');
                    var btn = label.parentElement.querySelector('.mkt-toggle');
                    toggleSector(key, btn);
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
        if (key === 'more') {
            loadSubsectors(container, btn);
            return;
        }
        var cached = getFromCache({ segment: key });
        if (cached) {
            renderCountries(key, cached.countries || []);
            container.classList.remove('hidden');
            setExpanded(btn, true);
            return;
        }
        loadCountries(key, container, btn);
    }

    function loadSubsectors(container, btn) {
        var cached = getFromCache({ segment: 'more' });
        if (cached) {
            renderSubsectors(cached.subsectors || []);
            container.classList.remove('hidden');
            setExpanded(btn, true);
            return;
        }
        fetchJSON(BASE + '/tree?segment=more').then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                container.innerHTML = '<div class="muted small">Could not load sub-sectors.</div>';
                container.classList.remove('hidden');
                return;
            }
            setCache({ segment: 'more' }, res.body);
            renderSubsectors(res.body.subsectors || []);
            container.classList.remove('hidden');
            setExpanded(btn, true);
        }).catch(function () {
            container.innerHTML = '<div class="muted small">Could not load sub-sectors.</div>';
            container.classList.remove('hidden');
        });
    }

    function renderSubsectors(subsectors) {
        var container = el('mkt-sector-more');
        var html = subsectors.map(function (s) {
            var childrenId = 'mkt-sector-' + esc(s.key);
            return '<div class="mkt-node" style="margin-left:22px;">' +
                treeRow(s.label, s.count,
                        'data-sector="' + esc(s.key) + '"',
                        'data-toggle-sector="' + esc(s.key) + '"') +
                '<div id="' + childrenId + '" class="mkt-countries hidden"></div>' +
                '</div>';
        }).join('');
        container.innerHTML = html || '<div class="muted small">No additional sectors.</div>';

        Array.prototype.forEach.call(container.querySelectorAll('.mkt-toggle[data-sector]'), function (btn) {
            btn.addEventListener('click', function () {
                toggleSector(btn.getAttribute('data-sector'), btn);
            });
        });
        Array.prototype.forEach.call(container.querySelectorAll('.mkt-label[data-toggle-sector]'), function (label) {
            label.addEventListener('click', function () {
                var key = label.getAttribute('data-toggle-sector');
                var btn = label.parentElement.querySelector('.mkt-toggle');
                toggleSector(key, btn);
            });
        });
    }

    function loadCountries(segment, container, btn) {
        fetchJSON(BASE + '/tree?segment=' + encodeURIComponent(segment)).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                container.innerHTML = '<div class="muted small">Could not load countries.</div>';
                container.classList.remove('hidden');
                return;
            }
            setCache({ segment: segment }, res.body);
            renderCountries(segment, res.body.countries || []);
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
            var childrenId = 'mkt-country-' + esc(segment) + '-' + esc(c.country);
            return '<div class="mkt-node" style="margin-left:22px;">' +
                treeRow(c.country, c.count,
                        'data-country="' + esc(segment) + ':' + esc(c.country) + '"',
                        'data-open-country="' + esc(segment) + ':' + esc(c.country) + '"') +
                '<div id="' + childrenId + '" class="mkt-regions hidden"></div>' +
                '</div>';
        }).join('');
        el(containerId).innerHTML = html || '<div class="muted small">No countries.</div>';

        Array.prototype.forEach.call(el(containerId).querySelectorAll('.mkt-toggle[data-country]'), function (btn) {
            btn.addEventListener('click', function () {
                var parts = btn.getAttribute('data-country').split(':');
                toggleCountry(parts[0], parts[1], btn);
            });
        });
        Array.prototype.forEach.call(el(containerId).querySelectorAll('.mkt-label[data-open-country]'), function (label) {
            label.addEventListener('click', function () {
                var parts = label.getAttribute('data-open-country').split(':');
                openIntersection(parts[0], parts[1]);
            });
        });
    }

    function toggleCountry(segment, country, btn) {
        var containerId = 'mkt-country-' + segment + '-' + country;
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
        loadCountryIntersection(segment, country, container, btn);
    }

    function loadCountryIntersection(segment, country, container, btn) {
        var cached = getFromCache({ segment: segment, country: country });
        if (cached) {
            renderRegions(segment, country, cached.regions || []);
            container.classList.remove('hidden');
            setExpanded(btn, true);
            return;
        }
        fetchJSON(BASE + '/tree?segment=' + encodeURIComponent(segment) + '&country=' + encodeURIComponent(country)).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                container.innerHTML = '<div class="muted small">Could not load regions.</div>';
                container.classList.remove('hidden');
                return;
            }
            setCache({ segment: segment, country: country }, res.body);
            renderRegions(segment, country, (res.body.regions || []));
            container.classList.remove('hidden');
            setExpanded(btn, true);
        }).catch(function () {
            container.innerHTML = '<div class="muted small">Could not load regions.</div>';
            container.classList.remove('hidden');
        });
    }

    function renderRegions(segment, country, regions) {
        var containerId = 'mkt-country-' + segment + '-' + country;
        if (!regions.length) {
            el(containerId).innerHTML = '<div class="muted small" style="padding:2px 0 6px;">No sub-national regions.</div>';
            return;
        }
        var html = regions.map(function (r) {
            return '<button class="mkt-region" data-open-region="' + esc(segment) + ':' + esc(country) + ':' + esc(r.region) + '">' +
                esc(r.region) + ' <span class="mkt-count">' + esc(String(r.count)) + '</span></button>';
        }).join('');
        el(containerId).innerHTML = html;

        Array.prototype.forEach.call(el(containerId).querySelectorAll('[data-open-region]'), function (btn) {
            btn.addEventListener('click', function () {
                var parts = btn.getAttribute('data-open-region').split(':');
                openIntersection(parts[0], parts[1], parts[2]);
            });
        });
    }

    // ------------------------------------------------------------------
    // Intersection modal
    // ------------------------------------------------------------------

    function openIntersection(segment, country, region) {
        currentIntersection = { segment: segment, country: country, region: region || '', status: '' };
        var title = segment.replace(/_/g, ' ') + ' × ' + country;
        if (region) title += ' — ' + region;
        el('intersectionTitle').textContent = title;
        var filters = el('intersectionFilters');
        if (filters) filters.innerHTML = '';
        el('intersectionBody').innerHTML = '<div class="notice notice-empty">Loading targets…</div>';
        el('intersectionModal').classList.add('open');
        document.body.style.overflow = 'hidden';
        loadIntersection();
    }

    function closeIntersection() {
        el('intersectionModal').classList.remove('open');
        document.body.style.overflow = '';
        currentIntersection = { segment: '', country: '', region: '', status: '' };
    }

    function loadIntersection() {
        var segment = currentIntersection.segment;
        var country = currentIntersection.country;
        var region = currentIntersection.region;
        var status = currentIntersection.status;
        var params = 'segment=' + encodeURIComponent(segment) + '&country=' + encodeURIComponent(country);
        if (region) params += '&region=' + encodeURIComponent(region);
        if (status) params += '&status=' + encodeURIComponent(status);

        var cached = getFromCache({ segment: segment, country: country, region: region, status: status });
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
            setCache({ segment: segment, country: country, region: region, status: status }, res.body);
            renderIntersection(res.body);
        }).catch(function () {
            el('intersectionBody').innerHTML =
                '<div class="notice notice-error">Could not load targets.</div>';
        });
    }

    function renderIntersection(data) {
        var segment = data.segment || currentIntersection.segment;
        var country = data.country || currentIntersection.country;
        var region = data.region || currentIntersection.region;
        var activeStatus = data.status || currentIntersection.status;
        var statuses = data.statuses || [];
        var regions = data.regions || [];
        var allLeads = data.leads || [];

        var title = segment.replace(/_/g, ' ') + ' × ' + country;
        if (region) title += ' — ' + region;
        el('intersectionTitle').textContent = title;

        var total = statuses.reduce(function (sum, s) { return sum + (s.count || 0); }, 0);

        var filtersHtml = '<div class="mkt-filters">' +
            '<button class="mkt-filter' + (activeStatus ? '' : ' active') + '" data-filter="">All (' + esc(total) + ')</button>';
        statuses.forEach(function (s) {
            filtersHtml += '<button class="mkt-filter' + (activeStatus === s.status ? ' active' : '') + '" data-filter="' + esc(s.status) + '">' +
                esc(s.status.replace(/_/g, ' ')) + ' (' + esc(String(s.count)) + ')</button>';
        });
        filtersHtml += '</div>';

        if (regions.length) {
            filtersHtml += '<div class="mkt-filters" style="margin-top:8px;">' +
                '<button class="mkt-filter' + (region ? '' : ' active') + '" data-region="">All regions</button>';
            regions.forEach(function (r) {
                filtersHtml += '<button class="mkt-filter' + (region === r.region ? ' active' : '') + '" data-region="' + esc(r.region) + '">' +
                    esc(r.region) + ' (' + esc(String(r.count)) + ')</button>';
            });
            filtersHtml += '</div>';
        }

        filtersHtml += '<div style="margin-top:12px;">' +
            '<input type="text" class="mkt-textfilter" id="mkt-namefilter" placeholder="Filter by name…">' +
            '</div>' +
            '<div style="margin-top:8px;">' +
            '<button class="btn-action btn-quiet" id="mkt-bulk-discover">Discover contacts for this intersection</button>' +
            '</div>';

        var filters = el('intersectionFilters');
        if (filters) filters.innerHTML = filtersHtml;

        var html = '';
        if (allLeads.length) {
            html += '<div class="mkt-targets" id="mkt-targets-list">';
            allLeads.forEach(function (l) {
                html += renderTarget(segment, country, l);
            });
            html += '</div>';
        } else {
            html += '<div class="notice notice-empty">No targets match the selected filter.</div>';
        }

        el('intersectionBody').innerHTML = html;

        var filterContainer = filters || el('intersectionBody');
        Array.prototype.forEach.call(filterContainer.querySelectorAll('[data-filter]'), function (btn) {
            btn.addEventListener('click', function () {
                currentIntersection.status = btn.getAttribute('data-filter');
                loadIntersection();
            });
        });
        Array.prototype.forEach.call(filterContainer.querySelectorAll('[data-region]'), function (btn) {
            btn.addEventListener('click', function () {
                currentIntersection.region = btn.getAttribute('data-region');
                loadIntersection();
            });
        });

        var nameFilter = el('mkt-namefilter');
        if (nameFilter) {
            nameFilter.addEventListener('input', function () {
                filterLeadsByName(nameFilter.value);
            });
        }

        var bulkDiscoverBtn = el('mkt-bulk-discover');
        if (bulkDiscoverBtn) {
            bulkDiscoverBtn.addEventListener('click', function () {
                bulkDiscoverIntersection();
            });
        }

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

        Array.prototype.forEach.call(el('intersectionBody').querySelectorAll('[data-contacts]'), function (btn) {
            var slug = btn.getAttribute('data-contacts');
            btn.addEventListener('click', function () { toggleContacts(slug); });
        });

        Array.prototype.forEach.call(el('intersectionBody').querySelectorAll('[data-auto-send]'), function (btn) {
            var slug = btn.getAttribute('data-auto-send');
            var enabled = btn.getAttribute('data-enabled') !== '1';
            btn.addEventListener('click', function () { setAutoSend(slug, enabled); });
        });

        Array.prototype.forEach.call(el('intersectionBody').querySelectorAll('[data-unsubscribe]'), function (btn) {
            var slug = btn.getAttribute('data-unsubscribe');
            btn.addEventListener('click', function () { unsubscribeLead(slug); });
        });
    }

    function setAutoSend(slug, enabled) {
        postJSON(BASE + '/lead/' + encodeURIComponent(slug) + '/auto-send', { enabled: enabled }).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                status('error', esc((res.body && res.body.error) || 'Auto-send update failed.'));
                return;
            }
            status('info', 'Auto-send ' + (enabled ? 'enabled' : 'disabled') + '.');
            clearTreeCache();
            if (el('intersectionModal') && el('intersectionModal').classList.contains('open')) {
                loadIntersection();
            }
        }).catch(function () {
            status('error', 'Auto-send request could not be sent.');
        });
    }

    function unsubscribeLead(slug) {
        var reason = window.prompt('Unsubscribe reason (optional):');
        if (reason === null) return;
        postJSON(BASE + '/lead/' + encodeURIComponent(slug) + '/unsubscribe', { reason: reason }).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                status('error', esc((res.body && res.body.error) || 'Unsubscribe failed.'));
                return;
            }
            status('info', 'Lead unsubscribed.');
            clearTreeCache();
            if (el('intersectionModal') && el('intersectionModal').classList.contains('open')) {
                loadIntersection();
            }
        }).catch(function () {
            status('error', 'Unsubscribe request could not be sent.');
        });
    }

    function bulkDiscoverIntersection() {
        var segment = currentIntersection.segment;
        var country = currentIntersection.country;
        var region = currentIntersection.region;
        if (!segment || !country) return;
        var body = { segment: segment, country: country };
        if (region) body.region = region;
        var filters = el('intersectionFilters');
        if (filters) {
            var btn = el('mkt-bulk-discover');
            if (btn) { btn.disabled = true; btn.textContent = 'Discovering…'; }
        }
        postJSON(BASE + '/tree/discover', body).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                status('error', esc((res.body && res.body.error) || 'Bulk discovery failed.'));
                return;
            }
            var data = res.body || {};
            status('info', 'Bulk discovery added ' + (data.added || 0) + ' contacts (' + (data.domains || []).length + ' domains).');
            contactsCache.clear();
        }).catch(function () {
            status('error', 'Bulk discovery request could not be sent.');
        }).then(function () {
            var btn = el('mkt-bulk-discover');
            if (btn) { btn.disabled = false; btn.textContent = 'Discover contacts for this intersection'; }
        });
    }

    function filterLeadsByName(query) {
        var q = (query || '').toLowerCase();
        var list = el('mkt-targets-list');
        if (!list) return;
        Array.prototype.forEach.call(list.querySelectorAll('.mkt-target'), function (row) {
            var nameEl = row.querySelector('strong');
            var name = nameEl ? nameEl.textContent.toLowerCase() : '';
            row.style.display = (!q || name.indexOf(q) >= 0) ? '' : 'none';
        });
    }

    function renderTarget(segment, country, l) {
        var org = l.website
            ? '<a class="text-link" href="' + esc(l.website) + '" target="_blank" rel="noopener">' + esc(l.organization) + '</a>'
            : esc(l.organization);
        var unsub = l.unsubscribed ? ' <span class="chip chip-forecast">unsubscribed</span>' : '';
        var auto = l.auto_send ? ' <span class="chip chip-modelled">auto-send</span>' : '';
        return '<div class="mkt-target" id="mkt-leadwrap-' + esc(l.slug) + '">' +
            '<div class="mkt-target-head">' +
            '<div>' +
            '<strong>' + org + '</strong>' +
            (l.segment ? ' <span class="mkt-segment-tag">' + esc((l.segment || '').replace(/_/g, ' ')) + '</span>' : '') +
            '<div class="mkt-target-meta" style="margin-top:4px;">' +
            priorityChip(l.priority) +
            statusChip(l.outreach_status) +
            (l.score != null ? '<span class="chip chip-modelled">score ' + esc(l.score) + '</span>' : '') +
            auto + unsub +
            '</div>' +
            '</div>' +
            '<div class="mkt-actions" style="display:flex;gap:8px;">' +
            '<button class="btn-action btn-quiet" data-auto-send="' + esc(l.slug) + '" ' +
            'data-enabled="' + (l.auto_send ? '1' : '0') + '">' + (l.auto_send ? 'Disable auto-send' : 'Enable auto-send') + '</button> ' +
            '<button class="btn-action btn-quiet" data-unsubscribe="' + esc(l.slug) + '">Unsubscribe</button> ' +
            '<button class="btn-action btn-quiet" data-send="' + esc(l.slug) + '" ' +
            'data-sector="' + esc(segment) + '" data-role="' + esc(l.decision_maker_role || '') + '">Auto-send</button> ' +
            '<button class="btn-action btn-quiet" data-follow="' + esc(l.slug) + '" ' +
            'data-sector="' + esc(segment) + '" data-role="' + esc(l.decision_maker_role || '') + '">Follow-up</button> ' +
            '<button class="btn-action btn-quiet" data-contacts="' + esc(l.slug) + '" ' +
            'data-sector="' + esc(segment) + '" data-role="' + esc(l.decision_maker_role || '') + '">Contacts</button>' +
            '</div>' +
            '</div>' +
            '<div id="mkt-detail-' + esc(l.slug) + '" class="mkt-detail hidden"></div>' +
            '<div id="mkt-send-' + esc(l.slug) + '" class="mkt-sendform hidden"></div>' +
            '<div id="mkt-contacts-' + esc(l.slug) + '" class="mkt-detail hidden"></div>' +
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
        closeContactsPanel();
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
            if (res.body && res.body.contacts) {
                contactsCache.set(slug, { configured: true, contacts: res.body.contacts });
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
    // Contacts panel
    // ------------------------------------------------------------------

    function toggleContacts(slug) {
        var panel = el('mkt-contacts-' + slug);
        if (!panel) return;
        if (contactsSlug && contactsSlug !== slug) {
            var prev = el('mkt-contacts-' + contactsSlug);
            if (prev) { prev.classList.add('hidden'); prev.innerHTML = ''; }
        }
        if (contactsSlug === slug && !panel.classList.contains('hidden')) {
            panel.classList.add('hidden');
            panel.innerHTML = '';
            contactsSlug = null;
            return;
        }
        closeFollowUpPanel();
        closeSendForm();
        contactsSlug = slug;
        panel.classList.remove('hidden');
        panel.innerHTML = '<div class="muted small">Loading contacts…</div>';
        loadContacts(slug);
    }

    function loadContacts(slug) {
        var cached = contactsCache.get(slug);
        if (cached) {
            renderContactsPanel(slug, cached);
            return;
        }
        fetchJSON(BASE + '/lead/' + encodeURIComponent(slug) + '/contacts').then(function (res) {
            if (showAuthHint(res)) return;
            if (res.status === 404) {
                renderContactsError(slug, 'Lead not found.');
                return;
            }
            if (!res.ok) {
                renderContactsError(slug, 'Could not load contacts.');
                return;
            }
            var data = res.body || { configured: true, contacts: [] };
            contactsCache.set(slug, data);
            renderContactsPanel(slug, data);
        }).catch(function () {
            renderContactsError(slug, 'Could not load contacts.');
        });
    }

    function renderContactsError(slug, msg) {
        var panel = el('mkt-contacts-' + slug);
        if (panel) panel.innerHTML = '<div class="notice notice-error">' + esc(msg) + '</div>';
    }

    function renderContactsPanel(slug, data) {
        var panel = el('mkt-contacts-' + slug);
        if (!panel) return;
        var configured = data.configured !== false;
        var contacts = data.contacts || [];

        var html = '<div class="mkt-contact-header">' +
            '<h4>Contacts' +
            (contacts.length ? ' <span class="mkt-count">' + esc(String(contacts.length)) + '</span>' : '') +
            '</h4>' +
            '<div class="mkt-actions">' +
            '<button class="btn-action btn-quiet" data-find-email="' + esc(slug) + '"' +
            (configured ? '' : ' disabled') + '>Find email</button>' +
            '<button class="btn-action btn-quiet" data-discover="' + esc(slug) + '"' +
            (configured ? '' : ' disabled') + '>Discover via Hunter.io</button>' +
            '</div>' +
            '</div>';

        if (!configured && data.note) {
            html += '<div class="disclaimer-box">' + esc(data.note) + '</div>';
        }

        html += '<div id="mkt-contacts-result-' + esc(slug) + '" class="mkt-sendresult"></div>';

        html += '<div id="mkt-find-email-' + esc(slug) + '" class="mkt-findemail hidden">' +
            '<div class="mkt-field" style="display:inline-block;margin-right:8px;">' +
            '<input type="text" id="mkt-find-first-' + esc(slug) + '" placeholder="First name" style="width:120px;">' +
            '</div>' +
            '<div class="mkt-field" style="display:inline-block;margin-right:8px;">' +
            '<input type="text" id="mkt-find-last-' + esc(slug) + '" placeholder="Last name" style="width:120px;">' +
            '</div>' +
            '<button class="btn-action btn-quiet" data-find-run="' + esc(slug) + '">Find via Hunter.io</button>' +
            '</div>';

        if (contacts.length) {
            html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
                '<th>Email</th><th>Name</th><th>Position / Department</th><th>Confidence</th><th>Verification</th><th>Source</th><th></th>' +
                '</tr></thead><tbody>';
            contacts.forEach(function (c) {
                var pos = (c.position || '') + (c.department ? (c.position ? ' · ' : '') + c.department : '');
                html += '<tr>' +
                    '<td><strong>' + esc(c.email || '—') + '</strong></td>' +
                    '<td>' + esc(c.name || '—') + '</td>' +
                    '<td>' + esc(pos || '—') + '</td>' +
                    '<td>' + (c.confidence != null ? '<span class="chip chip-modelled">' + esc(c.confidence) + '%</span>' : '—') + '</td>' +
                    '<td>' + verificationChip(c.verification) + '</td>' +
                    '<td>' + esc(c.source || '—') + '</td>' +
                    '<td class="mkt-contact-actions">' +
                    '<button class="btn-action btn-quiet" data-verify-contact="' + esc(c.id) + '" data-lead="' + esc(slug) + '">Verify</button>' +
                    '<button class="btn-action btn-quiet" data-use-contact="' + esc(slug) + '" ' +
                    'data-email="' + esc(c.email || '') + '" data-name="' + esc(c.name || '') + '">Use</button>' +
                    '<button class="btn-action btn-quiet" data-delete-contact="' + esc(c.id) + '" data-lead="' + esc(slug) + '">×</button>' +
                    '</td>' +
                    '</tr>';
            });
            html += '</tbody></table></div>';
        } else {
            html += '<div class="notice notice-empty">' +
                (configured
                    ? 'No contacts stored — run discovery to fetch them from Hunter.io (results are kept here; lookups are quota-limited).'
                    : 'No contacts stored yet.') +
                '</div>';
        }

        panel.innerHTML = html;

        var discoverBtn = panel.querySelector('[data-discover]');
        if (discoverBtn && configured) {
            discoverBtn.addEventListener('click', function () { discoverContacts(slug); });
        }

        var findBtn = panel.querySelector('[data-find-email]');
        if (findBtn && configured) {
            findBtn.addEventListener('click', function () { toggleFindEmail(slug); });
        }

        var findRunBtn = panel.querySelector('[data-find-run]');
        if (findRunBtn) {
            findRunBtn.addEventListener('click', function () { runFindEmail(slug); });
        }

        Array.prototype.forEach.call(panel.querySelectorAll('[data-verify-contact]'), function (btn) {
            btn.addEventListener('click', function () {
                verifyContact(btn.getAttribute('data-verify-contact'), slug);
            });
        });

        Array.prototype.forEach.call(panel.querySelectorAll('[data-use-contact]'), function (btn) {
            btn.addEventListener('click', function () {
                useContact(slug, btn.getAttribute('data-email'), btn.getAttribute('data-name'));
            });
        });

        Array.prototype.forEach.call(panel.querySelectorAll('[data-delete-contact]'), function (btn) {
            btn.addEventListener('click', function () {
                var id = btn.getAttribute('data-delete-contact');
                if (!window.confirm('Delete this contact?')) return;
                deleteContact(id, slug);
            });
        });
    }

    function verificationChip(verification) {
        var v = (verification || 'unknown').toLowerCase();
        var kind = 'unknown';
        if (v === 'valid' || v === 'deliverable') kind = 'modelled';
        else if (v === 'risky') kind = 'observed';
        else if (v === 'invalid' || v === 'undeliverable') kind = 'forecast';
        return HS.chip(kind, v);
    }

    function toggleFindEmail(slug) {
        var box = el('mkt-find-email-' + slug);
        if (!box) return;
        box.classList.toggle('hidden');
        if (!box.classList.contains('hidden')) {
            var first = el('mkt-find-first-' + slug);
            if (first) first.focus();
        }
    }

    function runFindEmail(slug) {
        var resultBox = el('mkt-contacts-result-' + slug);
        var first = el('mkt-find-first-' + slug);
        var last = el('mkt-find-last-' + slug);
        var firstName = first ? first.value.trim() : '';
        var lastName = last ? last.value.trim() : '';
        if (!firstName || !lastName) {
            if (resultBox) resultBox.innerHTML = '<div class="mkt-err">Enter first and last name.</div>';
            return;
        }
        if (resultBox) resultBox.innerHTML = '<div class="muted small">Finding email…</div>';
        postJSON(BASE + '/lead/' + encodeURIComponent(slug) + '/find-email', {
            first_name: firstName,
            last_name: lastName
        }).then(function (res) {
            if (showAuthHint(res)) return;
            if (res.status === 503 || res.status === 502 || res.status === 422) {
                if (resultBox) resultBox.innerHTML = '<div class="mkt-err">' + esc((res.body && res.body.error) || 'Find failed.') + '</div>';
                return;
            }
            if (!res.ok) {
                if (resultBox) resultBox.innerHTML = '<div class="mkt-err">' + esc((res.body && res.body.error) || 'Find failed.') + '</div>';
                return;
            }
            var data = res.body || {};
            if (!data.found) {
                if (resultBox) resultBox.innerHTML = '<div class="mkt-err">No email found for that name.</div>';
                return;
            }
            contactsCache.set(slug, { configured: true, contacts: [data.contact] });
            renderContactsPanel(slug, { configured: true, contacts: [data.contact] });
            if (resultBox) resultBox.innerHTML = '<div class="mkt-ok">Found ' + esc(data.contact.email) + '.</div>';
        }).catch(function () {
            if (resultBox) resultBox.innerHTML = '<div class="mkt-err">Find request could not be sent.</div>';
        });
    }

    function verifyContact(id, slug) {
        var resultBox = el('mkt-contacts-result-' + slug);
        if (resultBox) resultBox.innerHTML = '<div class="muted small">Verifying…</div>';
        postJSON(BASE + '/contacts/' + encodeURIComponent(id) + '/verify', {}).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                if (resultBox) resultBox.innerHTML = '<div class="mkt-err">' + esc((res.body && res.body.error) || 'Verify failed.') + '</div>';
                return;
            }
            contactsCache.delete(slug);
            loadContacts(slug);
            if (resultBox) resultBox.innerHTML = '<div class="mkt-ok">Verification updated.</div>';
        }).catch(function () {
            if (resultBox) resultBox.innerHTML = '<div class="mkt-err">Verify request could not be sent.</div>';
        });
    }

    function discoverContacts(slug) {
        var panel = el('mkt-contacts-' + slug);
        if (!panel) return;
        var discoverBtn = panel.querySelector('[data-discover]');
        if (discoverBtn) {
            discoverBtn.disabled = true;
            discoverBtn.textContent = 'Searching Hunter.io…';
        }
        var resultBox = el('mkt-contacts-result-' + slug);
        if (resultBox) resultBox.innerHTML = '';

        postJSON(BASE + '/lead/' + encodeURIComponent(slug) + '/contacts/discover', {}).then(function (res) {
            if (showAuthHint(res)) return;
            if (res.status === 422 || res.status === 502) {
                if (resultBox) resultBox.innerHTML = '<div class="mkt-err">' + esc((res.body && res.body.error) || 'Discovery failed.') + '</div>';
                resetDiscoverButton(discoverBtn);
                return;
            }
            if (!res.ok) {
                if (resultBox) resultBox.innerHTML = '<div class="mkt-err">' + esc((res.body && res.body.error) || 'Discovery failed.') + '</div>';
                resetDiscoverButton(discoverBtn);
                return;
            }
            var data = res.body || { configured: true, contacts: [] };
            contactsCache.set(slug, data);
            if (resultBox && data.added != null && data.domain) {
                resultBox.innerHTML = '<div class="mkt-ok">Added ' + esc(data.added) + ' new contacts (' + esc(data.domain) + ').</div>';
            }
            renderContactsPanel(slug, data);
        }).catch(function () {
            if (resultBox) resultBox.innerHTML = '<div class="mkt-err">Discovery request could not be sent.</div>';
            resetDiscoverButton(discoverBtn);
        });
    }

    function resetDiscoverButton(btn) {
        if (!btn) return;
        btn.disabled = false;
        btn.textContent = 'Discover via Hunter.io';
    }

    function deleteContact(id, slug) {
        postJSON(BASE + '/contacts/' + encodeURIComponent(id) + '/delete', {}).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                status('error', esc((res.body && res.body.error) || 'Delete failed.'));
                return;
            }
            status('info', 'Contact deleted.');
            contactsCache.delete(slug);
            loadContacts(slug);
        }).catch(function () {
            status('error', 'Delete request could not be sent.');
        });
    }

    function useContact(slug, email, name) {
        closeContactsPanel();
        var wrap = el('mkt-leadwrap-' + slug);
        var sector = '', role = '';
        if (wrap) {
            var sendBtn = wrap.querySelector('[data-send]');
            if (sendBtn) {
                sector = sendBtn.getAttribute('data-sector') || '';
                role = sendBtn.getAttribute('data-role') || '';
            }
        }
        toggleSendForm(slug, sector, role, { email: email || '', name: name || '' });
    }

    // ------------------------------------------------------------------
    // Auto-send form
    // ------------------------------------------------------------------

    function toggleSendForm(slug, sector, role, prefill) {
        var form = el('mkt-send-' + slug);
        if (!form) return;
        if (sendFormSlug && sendFormSlug !== slug) {
            var prev = el('mkt-send-' + sendFormSlug);
            if (prev) {
                prev.classList.add('hidden');
                prev.innerHTML = '';
            }
        }
        closeContactsPanel();
        closeFollowUpPanel();
        if (sendFormSlug === slug && !form.classList.contains('hidden') && !prefill) {
            form.classList.add('hidden');
            form.innerHTML = '';
            sendFormSlug = null;
            return;
        }
        sendFormSlug = slug;
        form.classList.remove('hidden');

        var cached = contactsCache.get(slug);
        if (cached) {
            form.innerHTML = buildSendFormHTML(slug, sector, role, cached, prefill);
            bindSendFormActions(slug, form);
            focusMessage(slug);
            return;
        }

        form.innerHTML = '<div class="muted small">Loading contacts…</div>';
        fetchJSON(BASE + '/lead/' + encodeURIComponent(slug) + '/contacts').then(function (res) {
            if (!form.classList.contains('hidden')) {
                var data = (res.ok && res.body) ? res.body : { configured: true, contacts: [] };
                contactsCache.set(slug, data);
                form.innerHTML = buildSendFormHTML(slug, sector, role, data, prefill);
                bindSendFormActions(slug, form);
                focusMessage(slug);
            }
        }).catch(function () {
            if (!form.classList.contains('hidden')) {
                var data = { configured: true, contacts: [] };
                contactsCache.set(slug, data);
                form.innerHTML = buildSendFormHTML(slug, sector, role, data, prefill);
                bindSendFormActions(slug, form);
                focusMessage(slug);
            }
        });
    }

    function focusMessage(slug) {
        var msg = el('mkt-send-msg-' + slug);
        if (msg) msg.focus();
    }

    function buildSendFormHTML(slug, sector, role, contactsData, prefill) {
        contactsData = contactsData || { configured: true, contacts: [] };
        prefill = prefill || {};
        var contacts = contactsData.contacts || [];

        var html = '<h4>Auto-send: ' + esc(slug) + '</h4>' +
            '<p class="mkt-template-note">Message is generated from the pre-made ' +
            esc((sector || 'sector').replace(/_/g, ' ')) +
            ' template merged with this lead\'s country and evidence.</p>';

        if (contacts.length) {
            html += '<div class="mkt-field">' +
                '<label for="mkt-contact-select-' + esc(slug) + '">Stored contacts</label>' +
                '<select id="mkt-contact-select-' + esc(slug) + '">' +
                '<option value="">Manual entry</option>' +
                contacts.map(function (c) {
                    var val = esc(c.email || '') + ':' + esc(c.name || '');
                    var label = esc(c.email || '') + (c.name ? ' — ' + esc(c.name) : '');
                    return '<option value="' + val + '">' + label + '</option>';
                }).join('') +
                '</select>' +
                '</div>';
        }

        html += '<div class="mkt-field">' +
            '<label for="mkt-send-to-' + esc(slug) + '">To email *</label>' +
            '<input type="email" id="mkt-send-to-' + esc(slug) + '" required' +
            (prefill.email ? ' value="' + esc(prefill.email) + '"' : '') + '>' +
            '</div>' +
            '<div class="mkt-field">' +
            '<label for="mkt-send-name-' + esc(slug) + '">Contact name</label>' +
            '<input type="text" id="mkt-send-name-' + esc(slug) + '" placeholder="' + esc(role || '') + '"' +
            (prefill.name ? ' value="' + esc(prefill.name) + '"' : '') + '>' +
            '</div>' +
            '<div class="mkt-field">' +
            '<label for="mkt-send-msg-' + esc(slug) + '">Custom message</label>' +
            '<textarea id="mkt-send-msg-' + esc(slug) + '" placeholder="Added to the pre-made template body"></textarea>' +
            '</div>' +
            '<div class="mkt-sendactions">' +
            '<button class="btn-action" data-send-now>Send now</button>' +
            '<button class="btn-action btn-quiet" data-schedule-toggle>Schedule</button>' +
            '<button class="btn-action btn-quiet" data-preview>Preview</button>' +
            '</div>' +
            '<div class="mkt-previewwrap hidden" id="mkt-previewwrap-' + esc(slug) + '">' +
            '<div class="mkt-field"><label>Subject</label>' +
            '<div id="mkt-preview-subject-' + esc(slug) + '" class="mkt-previewbox"></div></div>' +
            '<div class="mkt-field"><label>Body</label>' +
            '<pre id="mkt-preview-body-' + esc(slug) + '" class="mkt-previewbox"></pre></div>' +
            '</div>' +
            '<div class="mkt-schedulewrap" id="mkt-schedulewrap-' + esc(slug) + '">' +
            '<div class="mkt-field">' +
            '<label for="mkt-send-at-' + esc(slug) + '">Send at</label>' +
            '<input type="datetime-local" id="mkt-send-at-' + esc(slug) + '">' +
            '</div>' +
            '<button class="btn-action" data-send-schedule>Confirm schedule</button>' +
            '</div>' +
            '<div id="mkt-sendresult-' + esc(slug) + '" class="mkt-sendresult"></div>';
        return html;
    }

    function bindSendFormActions(slug, form) {
        var nowBtn = form.querySelector('[data-send-now]');
        var scheduleToggle = form.querySelector('[data-schedule-toggle]');
        var scheduleBtn = form.querySelector('[data-send-schedule]');
        var previewBtn = form.querySelector('[data-preview]');
        var contactSelect = form.querySelector('[id^="mkt-contact-select-"]');
        if (nowBtn) {
            nowBtn.addEventListener('click', function () { doSend(slug, null); });
        }
        if (scheduleToggle) {
            scheduleToggle.addEventListener('click', function () {
                var wrap = el('mkt-schedulewrap-' + slug);
                if (wrap) wrap.classList.toggle('visible');
            });
        }
        if (previewBtn) {
            previewBtn.addEventListener('click', function () { loadPreview(slug); });
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
        if (contactSelect) {
            contactSelect.addEventListener('change', function () {
                var raw = contactSelect.value;
                var idx = raw.indexOf(':');
                var email = idx >= 0 ? raw.slice(0, idx) : raw;
                var name = idx >= 0 ? raw.slice(idx + 1) : '';
                var toInput = el('mkt-send-to-' + slug);
                var nameInput = el('mkt-send-name-' + slug);
                if (toInput) toInput.value = email;
                if (nameInput) nameInput.value = name;
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

    function loadPreview(slug) {
        var wrap = el('mkt-previewwrap-' + slug);
        var subjectBox = el('mkt-preview-subject-' + slug);
        var bodyBox = el('mkt-preview-body-' + slug);
        var resultBox = el('mkt-sendresult-' + slug);
        if (wrap) wrap.classList.remove('hidden');
        if (subjectBox) subjectBox.textContent = 'Loading…';
        if (bodyBox) bodyBox.textContent = '';
        var payload = getSendPayload(slug);
        fetchJSON(BASE + '/lead/' + encodeURIComponent(slug) + '/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (res) {
            if (showAuthHint(res)) return;
            if (!res.ok) {
                if (resultBox) resultBox.innerHTML = '<div class="mkt-err">' + esc((res.body && res.body.error) || 'Preview failed.') + '</div>';
                return;
            }
            var data = res.body || {};
            if (subjectBox) subjectBox.textContent = data.subject || '—';
            if (bodyBox) bodyBox.textContent = data.body || '—';
        }).catch(function () {
            if (resultBox) resultBox.innerHTML = '<div class="mkt-err">Preview request could not be sent.</div>';
        });
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
            if (res.status === 429) {
                showSendResult(slug, 'error', esc((res.body && res.body.error) || 'Daily cap reached.'));
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
