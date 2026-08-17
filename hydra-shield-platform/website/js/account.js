/* HydraShield — Account (account.html).
 *
 * Cookie-session auth against the Stage 6 API:
 *   POST /api/v2/auth/register · POST /api/v2/auth/login · POST /api/v2/auth/logout
 *   GET  /api/v2/account
 *   GET/POST /api/v2/account/locations · DELETE /api/v2/account/locations/<id>
 *   GET  /api/v2/account/history
 *   GET/POST /api/v2/account/alerts · DELETE /api/v2/account/alerts/<id>
 *
 * Any 401 shows the login/register view; 403 tier responses show their
 * upgrade message. Nothing is rendered from assumed state — every list is
 * fetched.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function status(kind, msg) {
        el('statusArea').innerHTML = msg
            ? '<div class="notice notice-' + kind + '">' + esc(msg) + '</div>'
            : '';
    }

    function showView(loggedIn) {
        el('authView').classList.toggle('hidden', loggedIn);
        el('accountView').classList.toggle('hidden', !loggedIn);
    }

    function postJSON(url, payload) {
        return fetchJSON(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    }

    // ------------------------------------------------------------------
    // Session bootstrap
    // ------------------------------------------------------------------

    function boot() {
        fetchJSON(API + '/v2/account').then(function (res) {
            if (res.status === 401) {
                showView(false);
                return;
            }
            if (!res.ok) {
                showView(false);
                status('error', res.body.error || 'Account service unavailable.');
                return;
            }
            status('', '');
            showView(true);
            renderProfile(res.body);
            loadLocations();
            loadAlerts();
            loadHistory();
            loadHazards();
        }).catch(function () {
            showView(false);
            status('error', 'The account service could not be reached.');
        });
    }

    // ------------------------------------------------------------------
    // Auth forms
    // ------------------------------------------------------------------

    function wireAuth() {
        el('loginForm').addEventListener('submit', function (e) {
            e.preventDefault();
            status('info', 'Signing in…');
            postJSON(API + '/v2/auth/login', {
                email: el('loginEmail').value,
                password: el('loginPassword').value
            }).then(function (res) {
                if (!res.ok) {
                    status(res.status === 403 ? 'warn' : 'error',
                        res.body.error || 'Sign-in failed.');
                    return;
                }
                status('', '');
                boot();
            }).catch(function () { status('error', 'Sign-in request failed.'); });
        });

        el('registerForm').addEventListener('submit', function (e) {
            e.preventDefault();
            if (!el('regConsent').checked) {
                status('error', 'Please tick the consent box — it is required to create an account.');
                return;
            }
            status('info', 'Registering…');
            postJSON(API + '/v2/auth/register', {
                email: el('regEmail').value,
                password: el('regPassword').value,
                display_name: el('regName').value || undefined,
                consent: el('regConsent').checked
            }).then(function (res) {
                if (!res.ok) {
                    status('error', res.body.error || 'Registration failed.');
                    return;
                }
                status('info', res.body.message ||
                    'Check your inbox for the verification link.');
            }).catch(function () { status('error', 'Registration request failed.'); });
        });

        // ---- Password reset (forgot → email link → reset form) ----------
        el('forgotLink').addEventListener('click', function (e) {
            e.preventDefault();
            el('forgotForm').classList.toggle('hidden');
        });

        el('forgotForm').addEventListener('submit', function (e) {
            e.preventDefault();
            status('info', 'Sending reset link…');
            postJSON(API + '/v2/auth/forgot-password', {
                email: el('forgotEmail').value
            }).then(function (res) {
                // The API answer is intentionally indistinguishable.
                status('info', (res.body && res.body.message) ||
                    'If the address is registered, a reset link is on its way.');
            }).catch(function () { status('error', 'Reset request failed.'); });
        });

        var resetToken = new URLSearchParams(location.search).get('reset_token');
        if (resetToken) {
            showView(false);
            el('resetForm').classList.remove('hidden');
            status('info', 'Enter a new password to complete the reset.');
        }
        el('resetForm').addEventListener('submit', function (e) {
            e.preventDefault();
            status('info', 'Updating password…');
            postJSON(API + '/v2/auth/reset-password', {
                token: resetToken,
                password: el('resetPassword').value
            }).then(function (res) {
                if (!res.ok) {
                    status('error', res.body.error || 'Reset failed.');
                    return;
                }
                status('info', res.body.message || 'Password updated. Please sign in.');
                el('resetForm').classList.add('hidden');
                history.replaceState(null, '', location.pathname);
            }).catch(function () { status('error', 'Reset request failed.'); });
        });

        el('logoutBtn').addEventListener('click', function () {
            postJSON(API + '/v2/auth/logout', {}).then(function () {
                status('info', 'Signed out.');
                showView(false);
            }).catch(function () {
                showView(false);
            });
        });
    }

    // ------------------------------------------------------------------
    // Profile
    // ------------------------------------------------------------------

    function renderProfile(body) {
        var u = body.user || {};
        el('profileBlock').innerHTML =
            '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Email</th><td>' + esc(u.email) + '</td></tr>' +
            (u.display_name ? '<tr><th>Name</th><td>' + esc(u.display_name) + '</td></tr>' : '') +
            '<tr><th>Tier</th><td>' + esc(u.role || 'registered') + '</td></tr>' +
            '<tr><th>Status</th><td>' + esc(u.status || '') + '</td></tr>' +
            '<tr><th>Saved locations</th><td>' + esc(body.locations != null ? body.locations : '—') + '</td></tr>' +
            '<tr><th>Alerts</th><td>' + esc(body.alerts != null ? body.alerts : '—') + '</td></tr>' +
            '</table></div>';
    }

    // ------------------------------------------------------------------
    // Saved locations
    // ------------------------------------------------------------------

    function loadLocations() {
        fetchJSON(API + '/v2/account/locations').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('locationsList').innerHTML =
                    '<div class="notice notice-error">Saved locations unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderLocations(res.body.locations || []);
        }).catch(function () {
            el('locationsList').innerHTML =
                '<div class="notice notice-error">Saved locations could not be loaded.</div>';
        });
    }

    function renderLocations(list) {
        if (!list.length) {
            el('locationsList').innerHTML =
                '<div class="notice notice-empty">No saved locations yet.</div>';
            return;
        }
        el('locationsList').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Name</th><th>Coordinates</th><th></th></tr></thead><tbody>' +
            list.map(function (l) {
                return '<tr><td>' + esc(l.name || 'Location') + '</td>' +
                    '<td><a class="text-link" href="map.html?location=' +
                    encodeURIComponent(l.lat + ',' + l.lon) + '">' +
                    esc(Number(l.lat).toFixed(4)) + ', ' + esc(Number(l.lon).toFixed(4)) + '</a></td>' +
                    '<td><button class="btn-action btn-quiet" data-del-location="' + l.id + '">Delete</button></td></tr>';
            }).join('') + '</tbody></table></div>';
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-del-location]'), function (btn) {
                btn.addEventListener('click', function () {
                    fetchJSON(API + '/v2/account/locations/' + btn.getAttribute('data-del-location'),
                        { method: 'DELETE' }).then(loadLocations);
                });
            });
    }

    function wireLocations() {
        var last = HS.lastLocation();
        if (last && last.lat != null && last.lon != null) {
            var btn = el('useMapLocBtn');
            btn.classList.remove('hidden');
            btn.textContent = 'Use last map location (' +
                (last.name || (last.lat + ', ' + last.lon)) + ')';
            btn.addEventListener('click', function () {
                el('locLat').value = last.lat;
                el('locLon').value = last.lon;
                if (!el('locName').value && last.name) el('locName').value = last.name;
            });
        }
        el('addLocBtn').addEventListener('click', function () {
            var lat = parseFloat(el('locLat').value);
            var lon = parseFloat(el('locLon').value);
            if (isNaN(lat) || isNaN(lon)) {
                status('error', 'Latitude and longitude must be numbers.');
                return;
            }
            postJSON(API + '/v2/account/locations', {
                name: el('locName').value || undefined,
                lat: lat, lon: lon
            }).then(function (res) {
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Could not save the location.');
                    if (res.body && res.body.upgrade) status('warn', res.body.error + ' ' + res.body.upgrade.unlocks);
                    return;
                }
                status('', '');
                el('locName').value = ''; el('locLat').value = ''; el('locLon').value = '';
                loadLocations();
            });
        });
    }

    // ------------------------------------------------------------------
    // Alerts
    // ------------------------------------------------------------------

    function loadHazards() {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) return;
            el('alertHazard').innerHTML = res.body.hazards.map(function (h) {
                return '<option value="' + esc(h.id) + '">' + esc(h.name) + '</option>';
            }).join('');
        }).catch(function () {
            el('alertHazard').innerHTML = '<option value="wildfire">Wildfire</option>';
        });
    }

    function loadAlerts() {
        fetchJSON(API + '/v2/account/alerts').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('alertsList').innerHTML =
                    '<div class="notice notice-error">Alerts unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderAlerts(res.body.alerts || []);
        }).catch(function () {
            el('alertsList').innerHTML =
                '<div class="notice notice-error">Alerts could not be loaded.</div>';
        });
    }

    function renderAlerts(list) {
        if (!list.length) {
            el('alertsList').innerHTML =
                '<div class="notice notice-empty">No alerts configured.</div>';
            return;
        }
        el('alertsList').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Hazard</th><th>Location</th><th>Threshold</th><th>Channel</th><th>State</th><th></th>' +
            '</tr></thead><tbody>' +
            list.map(function (a) {
                var thr = a.threshold || {};
                var thrText = Object.keys(thr).length
                    ? Object.keys(thr).map(function (k) { return k.replace(/_/g, ' ') + ' ' + thr[k]; }).join(', ')
                    : '—';
                return '<tr><td>' + esc(a.hazard) + '</td>' +
                    '<td>' + esc(Number(a.lat).toFixed(4)) + ', ' + esc(Number(a.lon).toFixed(4)) + '</td>' +
                    '<td>' + esc(thrText) + '</td>' +
                    '<td>' + esc(a.channel || 'email') + '</td>' +
                    '<td>' + (a.active ? chip('OBSERVED', 'ACTIVE') : chip('UNAVAILABLE', 'INACTIVE')) + '</td>' +
                    '<td><button class="btn-action btn-quiet" data-del-alert="' + a.id + '">Delete</button></td></tr>';
            }).join('') + '</tbody></table></div>';
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-del-alert]'), function (btn) {
                btn.addEventListener('click', function () {
                    fetchJSON(API + '/v2/account/alerts/' + btn.getAttribute('data-del-alert'),
                        { method: 'DELETE' }).then(loadAlerts);
                });
            });
    }

    function wireAlerts() {
        el('addAlertBtn').addEventListener('click', function () {
            var lat = parseFloat(el('alertLat').value);
            var lon = parseFloat(el('alertLon').value);
            if (isNaN(lat) || isNaN(lon)) {
                status('error', 'Alert latitude and longitude must be numbers.');
                return;
            }
            postJSON(API + '/v2/account/alerts', {
                hazard: el('alertHazard').value || 'wildfire',
                lat: lat, lon: lon,
                threshold: { risk_gte: parseInt(el('alertThreshold').value, 10) },
                channel: 'email'
            }).then(function (res) {
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Could not create the alert.');
                    return;
                }
                status('', '');
                loadAlerts();
            });
        });
    }

    // ------------------------------------------------------------------
    // History
    // ------------------------------------------------------------------

    function loadHistory() {
        fetchJSON(API + '/v2/account/history').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('historyBlock').innerHTML =
                    '<div class="notice notice-error">History unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderHistory(res.body || {});
        }).catch(function () {
            el('historyBlock').innerHTML =
                '<div class="notice notice-error">History could not be loaded.</div>';
        });
    }

    function renderHistory(h) {
        var analyses = h.analyses || [];
        var reports = h.reports || [];
        var html = '';
        if (!analyses.length && !reports.length) {
            el('historyBlock').innerHTML =
                '<div class="notice notice-empty">No analyses or reports recorded yet. ' +
                'Analyses you run while signed in appear here.</div>';
            return;
        }
        if (analyses.length) {
            html += '<h3>Analyses</h3><div class="table-scroll"><table class="data-table">' +
                '<thead><tr><th>When</th><th>Hazard</th><th>Location</th><th>Summary</th></tr></thead><tbody>' +
                analyses.map(function (a) {
                    var s = a.summary || {};
                    return '<tr><td>' + esc((a.created_at || '').slice(0, 16).replace('T', ' ')) + '</td>' +
                        '<td>' + esc(a.hazard) + '</td>' +
                        '<td><a class="text-link" href="map.html?location=' +
                        encodeURIComponent(a.lat + ',' + a.lon) + '">' +
                        esc(Number(a.lat).toFixed(3)) + ', ' + esc(Number(a.lon).toFixed(3)) + '</a></td>' +
                        '<td class="muted small">' + esc(s.summary || s.text || '') + '</td></tr>';
                }).join('') + '</tbody></table></div>';
        }
        if (reports.length) {
            html += '<h3>Reports</h3><div class="table-scroll"><table class="data-table">' +
                '<thead><tr><th>When</th><th>Type</th><th>Hazard</th><th>Location</th><th>Report ID</th></tr></thead><tbody>' +
                reports.map(function (r) {
                    var meta = r.report_meta || {};
                    return '<tr><td>' + esc((r.created_at || '').slice(0, 16).replace('T', ' ')) + '</td>' +
                        '<td>' + esc(r.report_type) + '</td><td>' + esc(r.hazard || '') + '</td>' +
                        '<td>' + esc(Number(r.lat).toFixed(3)) + ', ' + esc(Number(r.lon).toFixed(3)) + '</td>' +
                        '<td class="muted small">' + esc(meta.report_id || '—') + '</td></tr>';
                }).join('') + '</tbody></table></div>';
        }
        el('historyBlock').innerHTML = html;
    }

    // ------------------------------------------------------------------

    function init() {
        wireAuth();
        wireLocations();
        wireAlerts();
        boot();
    }

    init();
})();
